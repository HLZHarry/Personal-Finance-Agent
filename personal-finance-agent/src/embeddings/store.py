"""
Vector and relational storage for personal-finance transactions.

Two complementary backends
--------------------------
FinanceVectorStore  – ChromaDB + Ollama embeddings
                      Enables semantic / natural-language search
                      ("show me grocery runs before Christmas")

FinanceSQLStore     – SQLite
                      Enables exact aggregations and period roll-ups
                      ("total spending by category in Q1")

Both accept the same TransactionSet objects produced by src.parsers.csv_parser.
"""

from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

import chromadb
import pandas as pd
from langchain_ollama import OllamaEmbeddings

from src.models.transaction import TransactionSet
from src.parsers.csv_parser import parse_csv

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _emit(msg: str) -> None:
    """UTF-8-safe print that survives Windows cp1252 consoles."""
    sys.stdout.buffer.write((msg + "\n").encode("utf-8", errors="replace"))


def _tx_document(date: Any, description: str, amount: float,
                 category: str, account_type: str) -> str:
    """Build the plain-text string that gets embedded."""
    sign = "+" if amount >= 0 else ""
    return f"{date} | {description} | {sign}${amount:.2f} | {category} | {account_type}"


# ============================================================================
# FinanceVectorStore
# ============================================================================

class FinanceVectorStore:
    """Persistent ChromaDB vector store backed by Ollama embeddings.

    Transactions are stored as embedded plain-text documents so that
    natural-language queries can retrieve semantically related records.

    Parameters
    ----------
    persist_dir:
        Directory where ChromaDB stores its on-disk data.
    embedding_model:
        Ollama model name used for embedding.  Must be pulled locally
        (``ollama pull nomic-embed-text``).

    Examples
    --------
    >>> store = FinanceVectorStore("data/chroma")
    >>> store.ingest_from_file("data/mock/rbc_chequing_2025.csv")
    >>> results = store.search("grocery stores in winter")
    """

    _COLLECTION = "transactions"

    def __init__(self, persist_dir: str,
                 embedding_model: str = "nomic-embed-text") -> None:
        self._embed_model = embedding_model
        self._embeddings  = OllamaEmbeddings(model=embedding_model)
        self._client      = chromadb.PersistentClient(path=persist_dir)
        # cosine similarity suits semantic search better than L2
        self._collection  = self._client.get_or_create_collection(
            name=self._COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        _emit(f"[ChromaDB] collection '{self._COLLECTION}' ready "
              f"({self._collection.count()} existing docs) in {persist_dir}")

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def ingest_transactions(self, transaction_set: TransactionSet) -> None:
        """Embed and upsert all transactions from a TransactionSet.

        Uses ``upsert`` so repeated calls are idempotent – existing IDs are
        updated rather than causing errors.

        ID scheme: ``{source_file}_{index:04d}`` so IDs are stable across
        re-ingests as long as the file name and row order are unchanged.

        Parameters
        ----------
        transaction_set:
            Parsed transactions to store.
        """
        if not transaction_set.transactions:
            _emit("[ChromaDB] Nothing to ingest – TransactionSet is empty.")
            return

        source = transaction_set.source
        ids, documents, metadatas = [], [], []

        for i, tx in enumerate(transaction_set.transactions):
            ids.append(f"{source}_{i:04d}")
            documents.append(_tx_document(
                tx.date, tx.description, tx.amount,
                tx.category.value, tx.account_type.value,
            ))
            metadatas.append({
                "date_str":     str(tx.date),     # ISO string for range filtering
                "amount":       tx.amount,
                "category":     tx.category.value,
                "account_type": tx.account_type.value,
                "source_file":  tx.source_file,
                "account_name": transaction_set.account_name,
                "institution":  transaction_set.institution,
            })

        # Embed in one batch – faster than one-by-one
        embeddings = self._embeddings.embed_documents(documents)

        self._collection.upsert(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )
        _emit(f"[ChromaDB] Ingested {len(ids)} transactions from '{source}'")

    def ingest_from_file(self, filepath: str) -> None:
        """Parse a file and ingest it in one step.

        Supports CSV formats auto-detected by :func:`src.parsers.csv_parser.parse_csv`.
        PDF parsing is not yet implemented.

        Parameters
        ----------
        filepath:
            Path to a CSV statement file.
        """
        path = Path(filepath)
        if path.suffix.lower() == ".pdf":
            raise NotImplementedError(
                "PDF ingestion is not yet supported. "
                "Use src.parsers.pdf_parser (coming soon) to extract "
                "transactions first, then call ingest_transactions()."
            )
        ts = parse_csv(str(path))
        self.ingest_transactions(ts)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, query: str, n_results: int = 10) -> list[dict[str, Any]]:
        """Semantic search over all embedded transactions.

        Parameters
        ----------
        query:
            Natural-language query, e.g. ``"grocery shopping in January"``.
        n_results:
            Maximum number of results to return.

        Returns
        -------
        list of dict
            Each dict has keys ``id``, ``document``, ``metadata``,
            ``distance``.  Sorted by ascending distance (most similar first).
        """
        count = self._collection.count()
        if count == 0:
            _emit("[ChromaDB] Collection is empty – nothing to search.")
            return []

        k = min(n_results, count)
        query_embedding = self._embeddings.embed_query(query)
        raw = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=k,
            include=["documents", "metadatas", "distances"],
        )

        results = []
        for doc, meta, dist, rid in zip(
            raw["documents"][0],
            raw["metadatas"][0],
            raw["distances"][0],
            raw["ids"][0],
        ):
            results.append({
                "id":       rid,
                "document": doc,
                "metadata": meta,
                "distance": round(dist, 6),
            })
        return results

    def search_by_date_range(self, start_date: str,
                             end_date: str) -> list[dict[str, Any]]:
        """Retrieve all transactions whose date falls within [start_date, end_date].

        ISO-format strings (``"YYYY-MM-DD"``).  Uses metadata filtering –
        no embedding call needed.

        Returns
        -------
        list of dict
            Each dict has keys ``id``, ``document``, ``metadata``.
        """
        raw = self._collection.get(
            where={
                "$and": [
                    {"date_str": {"$gte": start_date}},
                    {"date_str": {"$lte": end_date}},
                ]
            },
            include=["documents", "metadatas"],
        )
        return [
            {"id": rid, "document": doc, "metadata": meta}
            for rid, doc, meta in zip(
                raw["ids"], raw["documents"], raw["metadatas"]
            )
        ]

    def search_by_category(self, category: str,
                           n_results: int = 20) -> list[dict[str, Any]]:
        """Retrieve transactions by exact category match.

        Parameters
        ----------
        category:
            A :class:`src.models.transaction.Category` value string,
            e.g. ``"GROCERIES"`` or ``"DINING"``.

        Returns
        -------
        list of dict
            Each dict has keys ``id``, ``document``, ``metadata``.
        """
        raw = self._collection.get(
            where={"category": {"$eq": category.upper()}},
            limit=n_results,
            include=["documents", "metadatas"],
        )
        return [
            {"id": rid, "document": doc, "metadata": meta}
            for rid, doc, meta in zip(
                raw["ids"], raw["documents"], raw["metadatas"]
            )
        ]

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Return high-level statistics about the collection.

        Returns
        -------
        dict
            Keys: ``total_documents``, ``date_min``, ``date_max``,
            ``unique_sources``, ``categories``, ``embedding_model``.
        """
        count = self._collection.count()
        if count == 0:
            return {
                "total_documents": 0,
                "date_min":        None,
                "date_max":        None,
                "unique_sources":  [],
                "categories":      [],
                "embedding_model": self._embed_model,
            }

        raw    = self._collection.get(include=["metadatas"])
        metas  = raw["metadatas"]
        dates  = sorted(m["date_str"]     for m in metas if "date_str"    in m)
        sources = sorted({m["source_file"] for m in metas if "source_file" in m})
        cats    = sorted({m["category"]    for m in metas if "category"    in m})

        return {
            "total_documents": count,
            "date_min":        dates[0]  if dates else None,
            "date_max":        dates[-1] if dates else None,
            "unique_sources":  sources,
            "categories":      cats,
            "embedding_model": self._embed_model,
        }


# ============================================================================
# FinanceSQLStore
# ============================================================================

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS transactions (
    id               TEXT PRIMARY KEY,
    date             TEXT NOT NULL,
    description      TEXT NOT NULL,
    amount           REAL NOT NULL,
    category         TEXT NOT NULL,
    account_type     TEXT NOT NULL,
    source_file      TEXT NOT NULL,
    raw_description  TEXT NOT NULL,
    account_name     TEXT NOT NULL,
    institution      TEXT NOT NULL
);
"""
_CREATE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_date     ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_category ON transactions(category);
CREATE INDEX IF NOT EXISTS idx_amount   ON transactions(amount);
"""


class FinanceSQLStore:
    """SQLite store for personal-finance transactions.

    Provides exact-match queries and aggregation on top of the same data
    that :class:`FinanceVectorStore` embeds semantically.

    Parameters
    ----------
    db_path:
        File path for the SQLite database.

    Examples
    --------
    >>> sql = FinanceSQLStore("data/finance.db")
    >>> sql.ingest_transactions(transaction_set)
    >>> df = sql.get_summary(group_by="category")
    """

    def __init__(self, db_path: str = "data/finance.db") -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._conn    = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._bootstrap()
        _emit(f"[SQLite]   database ready at {db_path}")

    def _bootstrap(self) -> None:
        self._conn.executescript(_CREATE_TABLE + _CREATE_INDEXES)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def ingest_transactions(self, transaction_set: TransactionSet) -> None:
        """Insert transactions using ``INSERT OR REPLACE`` (idempotent).

        The primary key ``{source_file}_{index:04d}`` matches the ChromaDB
        ID scheme so records can be cross-referenced between stores.

        Parameters
        ----------
        transaction_set:
            Parsed transactions to persist.
        """
        if not transaction_set.transactions:
            _emit("[SQLite]   Nothing to ingest – TransactionSet is empty.")
            return

        source = transaction_set.source
        rows = [
            (
                f"{source}_{i:04d}",
                str(tx.date),
                tx.description,
                tx.amount,
                tx.category.value,
                tx.account_type.value,
                tx.source_file,
                tx.raw_description,
                transaction_set.account_name,
                transaction_set.institution,
            )
            for i, tx in enumerate(transaction_set.transactions)
        ]

        self._conn.executemany(
            """
            INSERT OR REPLACE INTO transactions
              (id, date, description, amount, category,
               account_type, source_file, raw_description,
               account_name, institution)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            rows,
        )
        self._conn.commit()
        _emit(f"[SQLite]   Ingested {len(rows)} transactions from '{source}'")

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def query(self, sql: str) -> pd.DataFrame:
        """Run arbitrary SQL and return results as a DataFrame.

        Parameters
        ----------
        sql:
            Any ``SELECT`` statement.
        """
        return pd.read_sql_query(sql, self._conn)

    def get_summary(self, group_by: str = "category",
                    period: str | None = None) -> pd.DataFrame:
        """Aggregate spending / income by a given dimension.

        Parameters
        ----------
        group_by:
            Any column in the ``transactions`` table.  Allowed values:
            ``category``, ``account_type``, ``source_file``,
            ``account_name``, ``institution``, ``date``.
        period:
            Optional ISO period filter: ``"2025"`` (year) or
            ``"2025-03"`` (month).

        Returns
        -------
        pd.DataFrame
            Columns: group column, ``transaction_count``,
            ``total_expenses``, ``total_income``, ``net``.
        """
        allowed = {
            "category", "account_type", "source_file",
            "account_name", "institution", "date",
        }
        safe_col = re.sub(r"[^\w]", "", group_by)
        if safe_col not in allowed:
            raise ValueError(
                f"group_by must be one of {sorted(allowed)}, got {group_by!r}"
            )

        where_clause = ""
        if period:
            p = period.strip()
            if len(p) == 7:
                where_clause = f"WHERE substr(date,1,7) = '{p}'"
            elif len(p) == 4:
                where_clause = f"WHERE substr(date,1,4) = '{p}'"

        sql = f"""
            SELECT
                {safe_col}                                                    AS {safe_col},
                COUNT(*)                                                      AS transaction_count,
                ROUND(SUM(CASE WHEN amount < 0 THEN  amount ELSE 0 END), 2)  AS total_expenses,
                ROUND(SUM(CASE WHEN amount > 0 THEN  amount ELSE 0 END), 2)  AS total_income,
                ROUND(SUM(amount), 2)                                         AS net
            FROM transactions
            {where_clause}
            GROUP BY {safe_col}
            ORDER BY total_expenses ASC
        """
        return self.query(sql)

    def close(self) -> None:
        """Close the SQLite connection."""
        self._conn.close()


# ============================================================================
# __main__ – ingest all mock data, demo both stores
# ============================================================================

if __name__ == "__main__":
    ROOT     = Path(__file__).parent.parent.parent          # personal-finance-agent/
    MOCK_DIR = ROOT / "data" / "mock"
    DATA_DIR = ROOT / "data"

    CHROMA_DIR = str(DATA_DIR / "chroma")
    SQLITE_DB  = str(DATA_DIR / "finance.db")

    csv_files = sorted(MOCK_DIR.glob("*.csv"))
    if not csv_files:
        _emit(f"No CSV files found in {MOCK_DIR}")
        sys.exit(1)

    # ----------------------------------------------------------------
    # 1. Parse all mock CSVs
    # ----------------------------------------------------------------
    _emit("\n=== Step 1: Parsing mock data files ===")
    transaction_sets = []
    for f in csv_files:
        try:
            ts = parse_csv(str(f))
            transaction_sets.append(ts)
        except Exception as exc:
            _emit(f"  [SKIP] {f.name}: {exc}")

    total_tx = sum(ts.count for ts in transaction_sets)
    _emit(f"  Loaded {len(transaction_sets)} statement(s), {total_tx} transactions total.")

    # ----------------------------------------------------------------
    # 2. SQLite – always works, no Ollama needed
    # ----------------------------------------------------------------
    _emit("\n=== Step 2: Ingesting into SQLite ===")
    sql_store = FinanceSQLStore(db_path=SQLITE_DB)
    for ts in transaction_sets:
        sql_store.ingest_transactions(ts)

    # ----------------------------------------------------------------
    # 3. ChromaDB + Ollama – graceful fallback if server is offline
    # ----------------------------------------------------------------
    _emit("\n=== Step 3: Ingesting into ChromaDB (requires `ollama serve`) ===")
    vector_store: FinanceVectorStore | None = None
    try:
        vector_store = FinanceVectorStore(persist_dir=CHROMA_DIR)
        for ts in transaction_sets:
            vector_store.ingest_transactions(ts)
        stats = vector_store.get_stats()
        _emit(f"  Stats: {stats['total_documents']} docs | "
              f"{stats['date_min']} -> {stats['date_max']} | "
              f"sources: {stats['unique_sources']}")
    except Exception as exc:
        _emit(f"  [WARN] Skipping ChromaDB: {exc}")
        _emit("  To enable: run `ollama serve` then `ollama pull nomic-embed-text`")

    # ----------------------------------------------------------------
    # 4. Vector search demo
    # ----------------------------------------------------------------
    _emit("\n=== Step 4: Vector search — 'grocery purchases' ===")
    if vector_store is not None:
        try:
            hits = vector_store.search("grocery purchases", n_results=8)
            _emit(f"  Top {len(hits)} results:")
            for r in hits:
                _emit(f"    [{r['distance']:.4f}]  {r['document']}")
        except Exception as exc:
            _emit(f"  [ERROR] {exc}")
    else:
        _emit("  Skipped – ChromaDB not available.")

    # ----------------------------------------------------------------
    # 5. SQL: total spending by category
    # ----------------------------------------------------------------
    _emit("\n=== Step 5: SQL — spending by category ===")
    df = sql_store.get_summary(group_by="category")
    exp = df[df["total_expenses"] < 0].copy()
    exp["total_expenses"] = exp["total_expenses"].abs()
    exp = exp.sort_values("total_expenses", ascending=False)

    col_w = max(len(str(c)) for c in exp["category"]) + 2
    _emit(f"  {'Category':<{col_w}} {'Txns':>6} {'Expenses (CAD)':>16}")
    _emit("  " + "-" * (col_w + 24))
    for _, row in exp.iterrows():
        _emit(f"  {row['category']:<{col_w}} {int(row['transaction_count']):>6}"
              f"   ${row['total_expenses']:>12,.2f}")
    _emit("  " + "-" * (col_w + 24))
    _emit(f"  {'TOTAL':<{col_w}} {int(exp['transaction_count'].sum()):>6}"
          f"   ${exp['total_expenses'].sum():>12,.2f}")

    # ----------------------------------------------------------------
    # 6. SQL: monthly cash flow for 2025
    # ----------------------------------------------------------------
    _emit("\n=== Step 6: SQL — monthly net cash flow (2025) ===")
    monthly = sql_store.query("""
        SELECT
            substr(date, 1, 7)                                          AS month,
            ROUND(SUM(CASE WHEN amount > 0 THEN  amount ELSE 0 END), 2) AS income,
            ROUND(SUM(CASE WHEN amount < 0 THEN -amount ELSE 0 END), 2) AS expenses,
            ROUND(SUM(amount), 2)                                        AS net
        FROM transactions
        WHERE substr(date, 1, 4) = '2025'
        GROUP BY month
        ORDER BY month
    """)
    _emit(f"  {'Month':<10} {'Income':>12} {'Expenses':>12} {'Net':>12}")
    _emit("  " + "-" * 50)
    for _, row in monthly.iterrows():
        _emit(f"  {row['month']:<10} ${row['income']:>10,.2f}"
              f"  ${row['expenses']:>10,.2f}  ${row['net']:>10,.2f}")

    sql_store.close()
    _emit("\nDone.")
