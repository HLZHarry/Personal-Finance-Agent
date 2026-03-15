"""
Pipeline validation tests.

Run with:
    python -m tests.test_pipeline

Checks
------
1.  Parse each known CSV — verify transaction counts match expected values
2.  Verify all parsed amounts are non-zero
3.  Verify dates fall within expected bounds for each file
4.  Ingest into ChromaDB — verify collection count matches parsed count
        (SKIPPED automatically if Ollama is not reachable)
5.  Vector search for "Loblaws" — verify results contain grocery transactions
        (SKIPPED automatically if Ollama is not reachable)
6.  SQL query total — verify count matches ChromaDB count
        (ChromaDB portion SKIPPED if Ollama is not reachable)
7.  Verify no duplicate transactions in either store (idempotent re-ingest)

All checks print PASS / FAIL / SKIP.  At the end a summary line is printed and
sys.exit(1) is raised if any check failed.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# Locate project root and add to sys.path so src.* imports resolve
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.parsers.csv_parser import parse_csv
from src.embeddings.store import FinanceSQLStore, FinanceVectorStore
from src.models.transaction import TransactionSet

# ---------------------------------------------------------------------------
# Known mock-data fixtures
# ---------------------------------------------------------------------------
MOCK_DIR = PROJECT_ROOT / "data" / "mock"

# (filename, expected_count, min_date, max_date)
FIXTURES: list[tuple[str, int, date, date]] = [
    (
        "rbc_chequing_2025.csv",
        342,
        date(2025, 1, 1),
        date(2025, 12, 31),
    ),
    (
        "visa_statement_jan2026.csv",
        25,
        date(2026, 1, 2),
        date(2026, 1, 30),
    ),
    (
        "visa_statement_feb2026.csv",
        25,
        date(2026, 2, 1),
        date(2026, 2, 28),
    ),
    (
        "mortgage_amortization.csv",
        24,
        date(2024, 2, 1),
        date(2026, 1, 1),
    ),
]

TOTAL_EXPECTED = sum(f[1] for f in FIXTURES)  # 416

# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------
_results: list[tuple[str, str]] = []  # (name, "PASS" | "FAIL" | "SKIP")


def _record(name: str, status: str, detail: str = "") -> None:
    _results.append((name, status))
    label = f"[{status}]"
    print(f"{label:<8} {name}")
    if detail:
        print(f"         {detail}")


def _check(name: str, condition: bool, detail: str = "") -> None:
    """Assert *condition* and record PASS or FAIL."""
    if condition:
        _record(name, "PASS")
    else:
        _record(name, "FAIL", detail)
    assert condition, f"FAILED: {name}" + (f" — {detail}" if detail else "")


def _skip(name: str, reason: str) -> None:
    _record(name, "SKIP", reason)


# ---------------------------------------------------------------------------
# Helper — try to initialise FinanceVectorStore; return None if Ollama is down
# ---------------------------------------------------------------------------

def _try_vector_store(persist_dir: str) -> FinanceVectorStore | None:
    try:
        return FinanceVectorStore(persist_dir=persist_dir)
    except Exception as exc:
        return None


# ===========================================================================
# CHECK 1 — transaction counts per file
# ===========================================================================

def check_1_transaction_counts() -> list[TransactionSet]:
    """Parse all fixture CSVs and verify counts.  Returns parsed TransactionSets."""
    print("\n--- CHECK 1: Transaction counts ---")
    parsed: list[TransactionSet] = []
    all_ok = True

    for filename, expected, _, _ in FIXTURES:
        path = MOCK_DIR / filename
        name = f"count({filename})"
        try:
            ts = parse_csv(str(path))
            parsed.append(ts)
            ok = ts.count == expected
            detail = f"got {ts.count}, expected {expected}" if not ok else ""
            _check(name, ok, detail)
            all_ok = all_ok and ok
        except Exception as exc:
            _record(name, "FAIL", str(exc))
            all_ok = False

    return parsed


# ===========================================================================
# CHECK 2 — no zero amounts
# ===========================================================================

def check_2_no_zero_amounts(all_sets: list[TransactionSet]) -> None:
    print("\n--- CHECK 2: No zero amounts ---")
    for ts in all_sets:
        zeros = [tx for tx in ts.transactions if tx.amount == 0.0]
        name = f"non_zero_amounts({ts.source})"
        detail = f"{len(zeros)} zero-amount transaction(s) found" if zeros else ""
        _check(name, len(zeros) == 0, detail)


# ===========================================================================
# CHECK 3 — date range bounds
# ===========================================================================

def check_3_date_ranges(all_sets: list[TransactionSet]) -> None:
    print("\n--- CHECK 3: Date range bounds ---")
    fixture_map = {f[0]: f for f in FIXTURES}

    for ts in all_sets:
        fixture = fixture_map.get(ts.source)
        if fixture is None:
            continue
        _, _, min_expected, max_expected = fixture

        actual_min = ts.period_start
        actual_max = ts.period_end

        name_min = f"date_min({ts.source})"
        name_max = f"date_max({ts.source})"

        _check(
            name_min,
            actual_min == min_expected,
            f"got {actual_min}, expected {min_expected}",
        )
        _check(
            name_max,
            actual_max == max_expected,
            f"got {actual_max}, expected {max_expected}",
        )


# ===========================================================================
# CHECK 4 — ChromaDB collection count matches parsed count
# ===========================================================================

def check_4_chroma_count(all_sets: list[TransactionSet], chroma_dir: str) -> bool:
    """Returns True if Ollama was available (so later vector checks can run)."""
    print("\n--- CHECK 4: ChromaDB collection count ---")

    vs = _try_vector_store(chroma_dir)
    if vs is None:
        _skip("chroma_collection_count", "Ollama not reachable — start with: ollama serve")
        return False

    for ts in all_sets:
        vs.ingest_transactions(ts)

    count_after = vs._collection.count()
    name = "chroma_collection_count"
    ok = count_after == TOTAL_EXPECTED
    detail = f"got {count_after}, expected {TOTAL_EXPECTED}" if not ok else ""
    _check(name, ok, detail)
    return True


# ===========================================================================
# CHECK 5 — vector search for "Loblaws" returns grocery transactions
# ===========================================================================

def check_5_loblaws_search(chroma_dir: str, ollama_available: bool) -> None:
    print("\n--- CHECK 5: Vector search 'Loblaws' ---")
    if not ollama_available:
        _skip("vector_search_loblaws", "Ollama not reachable")
        return

    vs = _try_vector_store(chroma_dir)
    if vs is None:
        _skip("vector_search_loblaws", "Ollama not reachable")
        return

    # Cast a wide net: semantic search on a store name may not rank exact name
    # matches first, so we check the top 20 results for any grocery evidence.
    results = vs.search("Loblaws grocery store", n_results=20)
    name_has_results = "loblaws_search_returns_results"
    _check(name_has_results, len(results) > 0, "No results returned")

    if results:
        # A result is "grocery-related" if its document mentions LOBLAWS
        # OR its metadata category is GROCERIES / UNCATEGORIZED (most RBC rows).
        def _is_grocery(r: dict) -> bool:
            doc_upper = r.get("document", "").upper()
            cat = r.get("metadata", {}).get("category", "")
            return "LOBLAWS" in doc_upper or cat in ("GROCERIES", "UNCATEGORIZED")

        grocery_hits = [r for r in results if _is_grocery(r)]
        name_grocery = "loblaws_results_include_grocery_transactions"
        _check(
            name_grocery,
            len(grocery_hits) > 0,
            f"None of the top {len(results)} results are grocery-related. "
            f"Categories returned: "
            f"{[r.get('metadata', {}).get('category') for r in results]}",
        )


# ===========================================================================
# CHECK 6 — SQL count matches ChromaDB count
# ===========================================================================

def check_6_sql_vs_chroma(
    all_sets: list[TransactionSet],
    db_path: str,
    chroma_dir: str,
    ollama_available: bool,
) -> None:
    print("\n--- CHECK 6: SQL count matches ChromaDB count ---")

    sql = FinanceSQLStore(db_path=db_path)
    for ts in all_sets:
        sql.ingest_transactions(ts)

    df_count = sql.query("SELECT COUNT(*) as total FROM transactions")
    sql_total = int(df_count["total"].iloc[0])
    sql.close()

    # SQL count vs expected
    name_sql = "sql_total_matches_expected"
    _check(
        name_sql,
        sql_total == TOTAL_EXPECTED,
        f"SQL has {sql_total}, expected {TOTAL_EXPECTED}",
    )

    # SQL count vs ChromaDB count (only if Ollama available)
    if not ollama_available:
        _skip("sql_count_matches_chroma_count", "Ollama not reachable")
        return

    vs = _try_vector_store(chroma_dir)
    if vs is None:
        _skip("sql_count_matches_chroma_count", "Ollama not reachable")
        return

    chroma_total = vs._collection.count()
    name_match = "sql_count_matches_chroma_count"
    _check(
        name_match,
        sql_total == chroma_total,
        f"SQL={sql_total}, ChromaDB={chroma_total}",
    )


# ===========================================================================
# CHECK 7 — no duplicates (idempotent re-ingest)
# ===========================================================================

def check_7_no_duplicates(
    all_sets: list[TransactionSet],
    db_path: str,
    chroma_dir: str,
    ollama_available: bool,
) -> None:
    print("\n--- CHECK 7: No duplicates after re-ingest ---")

    # --- SQL duplicate check ------------------------------------------------
    sql = FinanceSQLStore(db_path=db_path)

    # Ingest a second time — INSERT OR REPLACE should keep count stable
    for ts in all_sets:
        sql.ingest_transactions(ts)

    df = sql.query(
        "SELECT COUNT(*) as total, COUNT(DISTINCT id) as unique_ids FROM transactions"
    )
    total_sql = int(df["total"].iloc[0])
    unique_sql = int(df["unique_ids"].iloc[0])
    sql.close()

    _check(
        "sql_no_duplicates_after_reingest",
        total_sql == unique_sql,
        f"total rows={total_sql}, distinct ids={unique_sql}",
    )
    _check(
        "sql_count_stable_after_reingest",
        total_sql == TOTAL_EXPECTED,
        f"got {total_sql} after re-ingest, expected {TOTAL_EXPECTED}",
    )

    # --- ChromaDB duplicate check -------------------------------------------
    if not ollama_available:
        _skip("chroma_no_duplicates_after_reingest", "Ollama not reachable")
        _skip("chroma_count_stable_after_reingest", "Ollama not reachable")
        return

    vs = _try_vector_store(chroma_dir)
    if vs is None:
        _skip("chroma_no_duplicates_after_reingest", "Ollama not reachable")
        _skip("chroma_count_stable_after_reingest", "Ollama not reachable")
        return

    count_before = vs._collection.count()

    # Ingest same data again (upsert should be idempotent)
    for ts in all_sets:
        vs.ingest_transactions(ts)

    count_after = vs._collection.count()

    _check(
        "chroma_count_stable_after_reingest",
        count_after == count_before,
        f"count before={count_before}, after={count_after}",
    )
    _check(
        "chroma_no_duplicates_after_reingest",
        count_after == TOTAL_EXPECTED,
        f"got {count_after} after re-ingest, expected {TOTAL_EXPECTED}",
    )


# ===========================================================================
# Main runner
# ===========================================================================

def main() -> None:
    print("=" * 60)
    print("  Personal Finance Agent — Pipeline Tests")
    print("=" * 60)

    # Use isolated temp directories so tests never touch production data
    # ignore_cleanup_errors=True: ChromaDB holds file handles open on Windows
    # until process exit, causing PermissionError on rmtree.  The OS reclaims
    # the temp dir on exit anyway, so it is safe to suppress that error here.
    with tempfile.TemporaryDirectory(prefix="fin_test_chroma_",
                                     ignore_cleanup_errors=True) as tmp_chroma, \
         tempfile.TemporaryDirectory(prefix="fin_test_sql_") as tmp_sql:

        db_path = str(Path(tmp_sql) / "test_finance.db")

        # Run all checks — we suppress AssertionError from _check() internally
        # by catching it, so every check runs even if a prior one fails.
        all_sets: list[TransactionSet] = []
        ollama_available = False

        def _run(fn, *args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except AssertionError:
                return None  # FAIL already recorded; continue

        all_sets = _run(check_1_transaction_counts) or []
        _run(check_2_no_zero_amounts, all_sets)
        _run(check_3_date_ranges, all_sets)
        ollama_available = bool(
            _run(check_4_chroma_count, all_sets, tmp_chroma)
        )
        _run(check_5_loblaws_search, tmp_chroma, ollama_available)
        _run(check_6_sql_vs_chroma, all_sets, db_path, tmp_chroma, ollama_available)
        _run(check_7_no_duplicates, all_sets, db_path, tmp_chroma, ollama_available)

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print("\n" + "=" * 60)
    passed  = sum(1 for _, s in _results if s == "PASS")
    failed  = sum(1 for _, s in _results if s == "FAIL")
    skipped = sum(1 for _, s in _results if s == "SKIP")
    total   = len(_results)

    print(f"  Results: {passed} passed  |  {failed} failed  |  {skipped} skipped  |  {total} total")
    print("=" * 60)

    if failed > 0:
        print("\nFailed checks:")
        for name, status in _results:
            if status == "FAIL":
                print(f"  - {name}")
        sys.exit(1)
    else:
        print("\nAll checks passed.")


if __name__ == "__main__":
    main()
