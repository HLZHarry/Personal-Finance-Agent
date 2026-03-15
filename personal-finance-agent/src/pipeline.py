"""
Full ingestion pipeline orchestrating parsers, vector store, and SQL store.
"""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

from src.models.transaction import TransactionSet
from src.parsers.csv_parser import parse_csv
from src.embeddings.store import FinanceSQLStore, FinanceVectorStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scan_files(data_dir: str) -> tuple[list[Path], list[Path]]:
    """Return (csv_files, pdf_files) found under data_dir."""
    root = Path(data_dir)
    if not root.exists():
        raise FileNotFoundError(f"Data directory not found: {data_dir}")
    csv_files = sorted(root.rglob("*.csv"))
    pdf_files = sorted(root.rglob("*.pdf"))
    return csv_files, pdf_files


def _reset_stores(chroma_dir: str, db_path: str) -> None:
    """Delete ChromaDB directory and SQLite file so stores start fresh."""
    chroma_path = Path(chroma_dir)
    if chroma_path.exists():
        shutil.rmtree(chroma_path)
        print(f"[reset] Removed ChromaDB directory: {chroma_dir}")
    db = Path(db_path)
    if db.exists():
        db.unlink()
        print(f"[reset] Removed SQLite database: {db_path}")


def _print_divider(title: str = "") -> None:
    width = 60
    if title:
        pad = (width - len(title) - 2) // 2
        print(f"\n{'=' * pad} {title} {'=' * (width - pad - len(title) - 2)}")
    else:
        print("=" * width)


# ---------------------------------------------------------------------------
# run_ingestion
# ---------------------------------------------------------------------------

def run_ingestion(
    data_dir: str = "data/mock",
    chroma_dir: str = "data/chroma",
    db_path: str = "data/finance.db",
) -> None:
    """
    Scan data_dir for CSV/PDF files, parse each one, and ingest into both
    ChromaDB and SQLite.  Prints a structured summary report when done.
    """
    csv_files, pdf_files = _scan_files(data_dir)
    all_files = csv_files + pdf_files

    if not all_files:
        print(f"[pipeline] No CSV or PDF files found in '{data_dir}'")
        return

    print(f"\n[pipeline] Found {len(csv_files)} CSV + {len(pdf_files)} PDF files in '{data_dir}'")

    # --- Initialise stores --------------------------------------------------
    sql_store = FinanceSQLStore(db_path=db_path)

    vector_store: FinanceVectorStore | None = None
    try:
        vector_store = FinanceVectorStore(persist_dir=chroma_dir)
    except Exception as exc:
        print(f"[pipeline] WARNING: ChromaDB/Ollama unavailable — vector ingestion skipped ({exc})")

    # --- Parse & ingest each file -------------------------------------------
    processed: list[TransactionSet] = []
    skipped: list[str] = []

    for path in csv_files:
        print(f"[pipeline] Parsing CSV: {path.name} …")
        try:
            ts = parse_csv(str(path))
            sql_store.ingest_transactions(ts)
            if vector_store is not None:
                try:
                    vector_store.ingest_transactions(ts)
                except Exception as exc:
                    print(f"           WARNING: vector ingest failed for {path.name}: {exc}")
            processed.append(ts)
        except Exception as exc:
            print(f"           ERROR: {exc}")
            skipped.append(str(path.name))

    for path in pdf_files:
        print(f"[pipeline] Skipping PDF (parser not yet implemented): {path.name}")
        skipped.append(str(path.name))

    sql_store.close()

    # --- Summary report -----------------------------------------------------
    _print_divider("INGESTION SUMMARY")

    # Files processed
    print(f"\nFiles processed : {len(processed)}")
    for ts in processed:
        print(f"  • {ts.source}")
    if skipped:
        print(f"\nFiles skipped   : {len(skipped)}")
        for name in skipped:
            print(f"  • {name}")

    if not processed:
        print("\n[pipeline] Nothing to report — no files were successfully parsed.")
        return

    # Aggregate counts
    all_tx = [tx for ts in processed for tx in ts.transactions]
    total = len(all_tx)
    print(f"\nTotal transactions ingested : {total}")

    # Date range
    dates = [tx.date for tx in all_tx]
    print(f"Date range                  : {min(dates)}  →  {max(dates)}")

    # Per-file counts
    print("\nTransaction count by source file:")
    for ts in processed:
        print(f"  {ts.source:<45} {ts.count:>5}")

    # Per-account-type counts
    from collections import Counter
    by_type: Counter[str] = Counter(tx.account_type.value for tx in all_tx)
    print("\nTransaction count by account type:")
    for acct_type, count in sorted(by_type.items()):
        print(f"  {acct_type:<20} {count:>5}")

    _print_divider()


# ---------------------------------------------------------------------------
# run_demo_queries
# ---------------------------------------------------------------------------

def run_demo_queries(
    chroma_dir: str = "data/chroma",
    db_path: str = "data/finance.db",
) -> None:
    """Run pre-defined vector and SQL demo queries and print the results."""

    _print_divider("DEMO QUERIES")

    # --- Vector search queries ----------------------------------------------
    vector_store: FinanceVectorStore | None = None
    try:
        vector_store = FinanceVectorStore(persist_dir=chroma_dir)
    except Exception as exc:
        print(f"\n[query] WARNING: ChromaDB unavailable — vector queries skipped ({exc})")

    vector_queries = [
        "dining out expenses",
        "large purchases over 500 dollars",
    ]

    if vector_store is not None:
        for query_text in vector_queries:
            print(f"\n[Vector Search] \"{query_text}\"")
            print("-" * 55)
            try:
                results = vector_store.search(query_text, n_results=5)
                if not results:
                    print("  (no results)")
                else:
                    for i, r in enumerate(results, 1):
                        dist = r.get("distance", 0.0)
                        print(f"  {i}. {r['document']}")
                        print(f"     similarity: {1 - dist:.3f}  |  id: {r['id']}")
            except Exception as exc:
                print(f"  ERROR: {exc}")

    # --- SQL queries --------------------------------------------------------
    sql_store = FinanceSQLStore(db_path=db_path)

    sql_queries = [
        (
            "Spending by Category",
            (
                "SELECT category, "
                "SUM(amount) as total, "
                "COUNT(*) as count "
                "FROM transactions "
                "GROUP BY category "
                "ORDER BY total"
            ),
        ),
        (
            "Monthly Spending Totals",
            (
                "SELECT strftime('%Y-%m', date) as month, "
                "SUM(amount) as total "
                "FROM transactions "
                "GROUP BY month "
                "ORDER BY month"
            ),
        ),
    ]

    for title, sql in sql_queries:
        print(f"\n[SQL Query] {title}")
        print(f"  {sql}")
        print("-" * 55)
        try:
            df = sql_store.query(sql)
            if df.empty:
                print("  (no results)")
            else:
                # Format numeric columns to 2 decimal places
                for col in df.select_dtypes(include="number").columns:
                    df[col] = df[col].map(lambda v: f"{v:,.2f}")
                print(df.to_string(index=False))
        except Exception as exc:
            print(f"  ERROR: {exc}")

    sql_store.close()
    _print_divider()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Personal Finance Agent — ingestion pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m src.pipeline\n"
            "  python -m src.pipeline --data-dir data/mock --reset\n"
            "  python -m src.pipeline --query-only\n"
        ),
    )
    p.add_argument(
        "--data-dir",
        default="data/mock",
        metavar="PATH",
        help="Path to directory containing CSV/PDF statements (default: data/mock)",
    )
    p.add_argument(
        "--chroma-dir",
        default="data/chroma",
        metavar="PATH",
        help="Path to ChromaDB persistence directory (default: data/chroma)",
    )
    p.add_argument(
        "--db-path",
        default="data/finance.db",
        metavar="PATH",
        help="Path to SQLite database file (default: data/finance.db)",
    )
    p.add_argument(
        "--reset",
        action="store_true",
        help="Clear existing ChromaDB and SQLite data before ingesting",
    )
    p.add_argument(
        "--query-only",
        action="store_true",
        help="Skip ingestion and run demo queries on existing data",
    )
    return p


if __name__ == "__main__":
    args = _build_parser().parse_args()

    if args.reset and not args.query_only:
        _reset_stores(chroma_dir=args.chroma_dir, db_path=args.db_path)

    if not args.query_only:
        run_ingestion(
            data_dir=args.data_dir,
            chroma_dir=args.chroma_dir,
            db_path=args.db_path,
        )

    run_demo_queries(
        chroma_dir=args.chroma_dir,
        db_path=args.db_path,
    )
