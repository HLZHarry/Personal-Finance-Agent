"""
src/agents/tools.py

LangGraph/LangChain tools that wrap the project's existing components.

Each tool is decorated with @tool so the LLM can reason about which one to
call.  Docstrings are the primary signal the model uses when selecting tools,
so they are written to be maximally informative about *when* to use each one.

Tool summary
------------
vector_search           Semantic search over ChromaDB (needs Ollama).
sql_query               Exact aggregations via SQLite — totals, trends, etc.
run_categorizer         Apply pattern-based category labels to a CSV file.
detect_recurring        Find recurring bills/subscriptions in the database.
load_skill_instructions Load a SKILL.md for detailed agent instructions.

All tools return plain strings so they can be injected directly into the
LLM's context as tool-call results.  Errors are returned as "[ERROR] ..."
strings rather than raised, keeping the graph running on partial failures.
"""

from __future__ import annotations

import calendar
import io
import math
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Optional

import pandas as pd
from langchain_core.tools import tool

# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------

_ROOT    = Path(__file__).parent.parent.parent          # …/personal-finance-agent/
_DB_PATH = str(_ROOT / "data" / "finance.db")
_CHROMA  = str(_ROOT / "data" / "chroma")

# ---------------------------------------------------------------------------
# Lazy store singletons
# The stores are created on first use so importing this module never fails
# even when Ollama is offline or the database doesn't yet exist.
# ---------------------------------------------------------------------------

_sql_store    = None
_vector_store = None


def _get_sql_store():
    """Return the module-level FinanceSQLStore, creating it on first call."""
    global _sql_store
    if _sql_store is None:
        from src.embeddings.store import FinanceSQLStore
        _sql_store = FinanceSQLStore(db_path=_DB_PATH)
    return _sql_store


def _get_vector_store():
    """Return the module-level FinanceVectorStore, creating it on first call."""
    global _vector_store
    if _vector_store is None:
        from src.embeddings.store import FinanceVectorStore
        _vector_store = FinanceVectorStore(persist_dir=_CHROMA)
    return _vector_store


# ---------------------------------------------------------------------------
# Shared SQL helpers
# ---------------------------------------------------------------------------

def _raw_conn() -> sqlite3.Connection:
    """
    Open a direct sqlite3 connection with SQRT registered.

    Used by sql_query to avoid re-using the FinanceSQLStore connection when
    we need custom aggregation functions or pandas formatting control.
    """
    if not Path(_DB_PATH).exists():
        raise FileNotFoundError(
            f"Database not found at {_DB_PATH}. "
            "Run `python -m src.pipeline` to ingest statements first."
        )
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.create_function("SQRT", 1, lambda x: math.sqrt(x) if x and x > 0 else 0.0)
    return conn


def _q(conn: sqlite3.Connection, sql: str) -> pd.DataFrame:
    return pd.read_sql_query(sql, conn)


def _fmt_exp(v) -> str:
    """Unsigned expense amount: $X,XXX.XX"""
    if v is None or (isinstance(v, float) and v != v):
        return "n/a"
    return f"${abs(float(v)):>10,.2f}"


def _fmt_delta(v) -> str:
    """Signed delta: +$X.XX or -$X.XX"""
    if v is None or (isinstance(v, float) and v != v):
        return "n/a"
    sign = "+" if v >= 0 else "-"
    return f"{sign}${abs(float(v)):>9,.2f}"


def _fmt_pct(v) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return "n/a"
    return f"{float(v):+.1f}%"


# ---------------------------------------------------------------------------
# Tool 1 — Semantic / vector search
# ---------------------------------------------------------------------------

@tool
def vector_search(query: str, n_results: int = 10) -> str:
    """Search financial transactions by semantic meaning.

    Good for: finding specific types of purchases, identifying unusual
    transactions, or retrieving transactions that match a natural-language
    description (e.g. "coffee shop visits", "online subscriptions",
    "large purchases in December").

    Returns the top matching transactions ranked by relevance, with their
    date, description, amount, and category.

    Requires Ollama to be running (`ollama serve`).  Falls back gracefully
    if the vector store is unavailable.

    Parameters
    ----------
    query:
        Natural-language description of the transactions to find.
    n_results:
        Maximum number of results to return (default 10).
    """
    try:
        store = _get_vector_store()
    except Exception as exc:
        return (
            f"[ERROR] Could not connect to vector store: {exc}\n"
            "Make sure `ollama serve` is running and the data has been ingested."
        )

    try:
        hits = store.search(query, n_results=n_results)
    except Exception as exc:
        return f"[ERROR] Vector search failed: {exc}"

    if not hits:
        return "No transactions found matching that query."

    lines = [f"Vector search results for: \"{query}\" ({len(hits)} matches)\n"]
    lines.append(f"  {'Relevance':>9}  {'Date':<12}  {'Description':<38}  {'Amount':>10}  Category")
    lines.append(f"  {'-'*9}  {'-'*12}  {'-'*38}  {'-'*10}  --------")

    for r in hits:
        # document format: "DATE | DESCRIPTION | $AMOUNT | CATEGORY | ACCOUNT"
        parts    = r["document"].split(" | ")
        date     = parts[0] if len(parts) > 0 else ""
        desc     = parts[1][:38] if len(parts) > 1 else ""
        amount   = parts[2] if len(parts) > 2 else ""
        category = parts[3] if len(parts) > 3 else ""
        sim      = 1.0 - r["distance"]        # cosine distance → similarity

        lines.append(
            f"  {sim:>8.3f}   {date:<12}  {desc:<38}  {amount:>10}  {category}"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 2 — SQL / structured queries
# ---------------------------------------------------------------------------

# Allowed query types (validated before executing SQL)
_SQL_QUERY_TYPES = {
    "period_summary",
    "category_breakdown",
    "top_expenses",
    "monthly_trend",
    "category_comparison",
}


@tool
def sql_query(
    query_type: str,
    start_date: str = "",
    end_date: str = "",
    category: str = "",
) -> str:
    """Query financial data with exact calculations.

    Good for: totals, averages, transaction counts, period comparisons,
    category breakdowns, monthly trends, and detecting anomalies.  Use
    this tool over vector_search whenever the user asks for specific
    numbers, percentages, or comparisons between time periods.

    Query types
    -----------
    "period_summary"
        Total spending by category for a date range.
        Requires: start_date (YYYY-MM-DD), end_date (YYYY-MM-DD).

    "category_breakdown"
        All individual transactions in one category for a date range.
        Requires: category (e.g. "GROCERIES"), start_date, end_date.

    "top_expenses"
        The largest expense transactions, ranked by amount.
        Optional: start_date, end_date, category.

    "monthly_trend"
        Month-by-month spending totals over time.
        Optional: category (e.g. "DINING") to filter to one category;
        start_date and end_date to limit the range.

    "category_comparison"
        Compare spending across all categories between two calendar months.
        Uses start_date as period A and end_date as period B, both in
        YYYY-MM format (e.g. start_date="2025-01", end_date="2025-02").

    Parameters
    ----------
    query_type:
        One of the five types listed above.
    start_date:
        Start of the date range.  Format depends on query_type (see above).
    end_date:
        End of the date range.  Format depends on query_type (see above).
    category:
        Category filter in uppercase, e.g. "GROCERIES", "DINING",
        "TRANSPORTATION".  Only used by some query types.
    """
    if query_type not in _SQL_QUERY_TYPES:
        return (
            f"[ERROR] Unknown query_type '{query_type}'. "
            f"Choose from: {', '.join(sorted(_SQL_QUERY_TYPES))}"
        )

    try:
        conn = _raw_conn()
    except FileNotFoundError as exc:
        return f"[ERROR] {exc}"

    try:
        out = io.StringIO()
        _dispatch_sql(conn, query_type, start_date, end_date, category, out)
        return out.getvalue().strip() or "Query returned no results."
    except Exception as exc:
        return f"[ERROR] SQL query failed: {exc}"
    finally:
        conn.close()


def _dispatch_sql(
    conn: sqlite3.Connection,
    query_type: str,
    start_date: str,
    end_date: str,
    category: str,
    out: io.StringIO,
) -> None:
    """Route to the appropriate SQL runner and write results to *out*."""
    w = lambda s: out.write(s + "\n")   # noqa: E731

    if query_type == "period_summary":
        _sql_period_summary(conn, start_date, end_date, w)

    elif query_type == "category_breakdown":
        if not category:
            out.write("[ERROR] category_breakdown requires a category parameter.\n")
            return
        _sql_category_breakdown(conn, category.upper(), start_date, end_date, w)

    elif query_type == "top_expenses":
        _sql_top_expenses(conn, start_date or None, end_date or None,
                          category.upper() if category else None, w)

    elif query_type == "monthly_trend":
        _sql_monthly_trend(conn, category.upper() if category else None,
                           start_date or None, end_date or None, w)

    elif query_type == "category_comparison":
        # start_date / end_date are YYYY-MM period strings
        if not start_date or not end_date:
            out.write(
                "[ERROR] category_comparison requires start_date and end_date "
                "as YYYY-MM period strings (e.g. '2025-01').\n"
            )
            return
        _sql_category_comparison(conn, start_date, end_date, w)


def _month_bounds(ym: str) -> tuple[str, str]:
    y, m = int(ym[:4]), int(ym[5:7])
    last = calendar.monthrange(y, m)[1]
    return f"{ym}-01", f"{ym}-{last:02d}"


def _sql_period_summary(conn, start_date, end_date, w):
    df = _q(conn, f"""
        SELECT category,
               COUNT(*) AS txns,
               ROUND(SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END), 2) AS expenses,
               ROUND(SUM(CASE WHEN amount > 0 THEN amount      ELSE 0 END), 2) AS income,
               ROUND(AVG(CASE WHEN amount < 0 THEN ABS(amount) END), 2)        AS avg_expense
        FROM transactions
        WHERE date BETWEEN '{start_date}' AND '{end_date}'
          AND account_type != 'mortgage'
        GROUP BY category
        ORDER BY expenses DESC
    """)
    if df.empty:
        w(f"No transactions found between {start_date} and {end_date}.")
        return

    expense_rows = df[~df["category"].isin({"INCOME", "TRANSFER"})]
    total_exp    = expense_rows["expenses"].sum()
    df["pct"]    = df["expenses"].apply(
        lambda e: (e / total_exp * 100) if total_exp > 0 else 0.0
    )

    w(f"Period Summary: {start_date} to {end_date}")
    w(f"  {'Category':<18}  {'Txns':>5}  {'Expenses':>12}  {'% Total':>8}  {'Avg/Txn':>12}")
    w(f"  {'-'*18}  {'-'*5}  {'-'*12}  {'-'*8}  {'-'*12}")
    for _, row in df.iterrows():
        if row["category"] in {"INCOME", "TRANSFER"}:
            continue
        w(f"  {row['category']:<18}  {int(row['txns']):>5}  "
          f"{_fmt_exp(row['expenses']):>12}  {row['pct']:>7.1f}%  "
          f"{_fmt_exp(row['avg_expense']):>12}")
    w(f"  {'TOTAL':<18}  {'':>5}  {_fmt_exp(total_exp):>12}  {'100.0%':>8}")

    income_row = df[df["category"] == "INCOME"]
    if not income_row.empty:
        inc = income_row["income"].sum()
        w(f"\n  Income: {_fmt_exp(inc)}   Net: {_fmt_delta(inc - total_exp)}")


def _sql_category_breakdown(conn, category, start_date, end_date, w):
    h = _q(conn, f"""
        SELECT COUNT(*) AS txns,
               ROUND(SUM(ABS(amount)), 2) AS total,
               ROUND(AVG(ABS(amount)), 2) AS avg_txn,
               ROUND(MAX(ABS(amount)), 2) AS largest
        FROM transactions
        WHERE date BETWEEN '{start_date}' AND '{end_date}'
          AND category = '{category}'
          AND amount < 0
    """).iloc[0]

    detail = _q(conn, f"""
        SELECT date, description, ROUND(ABS(amount), 2) AS amount
        FROM transactions
        WHERE date BETWEEN '{start_date}' AND '{end_date}'
          AND category = '{category}'
          AND amount < 0
        ORDER BY amount DESC
    """)

    w(f"Category Breakdown: {category}  ({start_date} to {end_date})")
    w(f"  Transactions: {int(h['txns'])}   "
      f"Total: {_fmt_exp(h['total'])}   "
      f"Avg: {_fmt_exp(h['avg_txn'])}   "
      f"Largest: {_fmt_exp(h['largest'])}")
    if detail.empty:
        w("  (no expense transactions in this period)")
        return
    w(f"\n  {'Date':<12}  {'Description':<38}  {'Amount':>12}")
    w(f"  {'-'*12}  {'-'*38}  {'-'*12}")
    for _, row in detail.iterrows():
        desc = str(row["description"])[:38]
        w(f"  {row['date']:<12}  {desc:<38}  {_fmt_exp(row['amount']):>12}")


def _sql_top_expenses(conn, start_date, end_date, category, w, n=10):
    cat_filter  = f"AND category = '{category}'" if category else ""
    date_filter = (f"AND date BETWEEN '{start_date}' AND '{end_date}'"
                   if start_date and end_date else "")
    df = _q(conn, f"""
        SELECT date, description, category,
               ROUND(ABS(amount), 2) AS amount
        FROM transactions
        WHERE amount < 0
          AND category NOT IN ('INCOME', 'TRANSFER')
          {cat_filter}
          {date_filter}
        ORDER BY amount DESC
        LIMIT {n}
    """)

    title = f"Top {n} Expenses"
    if category:
        title += f" in {category}"
    if start_date and end_date:
        title += f" ({start_date} to {end_date})"
    w(title)
    w(f"  {'#':>3}  {'Date':<12}  {'Description':<38}  {'Category':<18}  {'Amount':>12}")
    w(f"  {'-'*3}  {'-'*12}  {'-'*38}  {'-'*18}  {'-'*12}")
    for rank, (_, row) in enumerate(df.iterrows(), 1):
        desc = str(row["description"])[:38]
        w(f"  {rank:>3}  {row['date']:<12}  {desc:<38}  "
          f"{row['category']:<18}  {_fmt_exp(row['amount']):>12}")


def _sql_monthly_trend(conn, category, start_date, end_date, w):
    cat_filter  = f"AND category = '{category}'" if category else ""
    date_filter = (f"AND date BETWEEN '{start_date}' AND '{end_date}'"
                   if start_date and end_date else "")
    df = _q(conn, f"""
        SELECT substr(date,1,7) AS month,
               COUNT(*)                           AS txns,
               ROUND(SUM(ABS(amount)), 2)         AS total
        FROM transactions
        WHERE amount < 0
          AND category NOT IN ('INCOME', 'TRANSFER')
          {cat_filter}
          {date_filter}
        GROUP BY month
        ORDER BY month
    """)
    if df.empty:
        w("No data found for monthly trend query.")
        return

    df["mom_delta"] = df["total"].diff()
    df["mom_pct"]   = df["total"].pct_change() * 100

    title = f"Monthly Trend: {category if category else 'All Expenses'}"
    w(title)
    w(f"  {'Month':<9}  {'Txns':>5}  {'Total':>12}  {'MoM Delta':>12}  {'MoM %':>8}")
    w(f"  {'-'*9}  {'-'*5}  {'-'*12}  {'-'*12}  {'-'*8}")
    for _, row in df.iterrows():
        delta = _fmt_delta(row["mom_delta"]) if not pd.isna(row["mom_delta"]) else "          --"
        pct   = _fmt_pct(row["mom_pct"])     if not pd.isna(row["mom_pct"])   else "    --"
        w(f"  {row['month']:<9}  {int(row['txns']):>5}  {_fmt_exp(row['total']):>12}  "
          f"{delta:>12}  {pct:>8}")


def _sql_category_comparison(conn, period_a, period_b, w):
    sa, ea = _month_bounds(period_a)
    sb, eb = _month_bounds(period_b)

    def _period_df(start, end, label):
        df = _q(conn, f"""
            SELECT category,
                   ROUND(SUM(ABS(amount)), 2) AS expenses
            FROM transactions
            WHERE date BETWEEN '{start}' AND '{end}'
              AND amount < 0
              AND category NOT IN ('INCOME', 'TRANSFER')
            GROUP BY category
        """)
        return df.set_index("category").rename(columns={"expenses": label})

    a = _period_df(sa, ea, period_a)
    b = _period_df(sb, eb, period_b)
    merged = a.join(b, how="outer").fillna(0.0)
    merged["delta"] = merged[period_b] - merged[period_a]
    merged["pct"]   = merged.apply(
        lambda r: (r["delta"] / r[period_a] * 100) if r[period_a] != 0 else float("nan"),
        axis=1,
    )
    merged = merged.sort_values(period_b, ascending=False)

    w(f"Category Comparison: {period_a} vs {period_b}")
    w(f"  {'Category':<18}  {period_a:>12}  {period_b:>12}  {'Delta':>12}  {'Change':>8}  Flag")
    w(f"  {'-'*18}  {'-'*12}  {'-'*12}  {'-'*12}  {'-'*8}  ----")
    for cat, row in merged.iterrows():
        flag = "(!) >20%" if not pd.isna(row["pct"]) and abs(row["pct"]) > 20 else ""
        w(f"  {str(cat):<18}  {_fmt_exp(row[period_a]):>12}  "
          f"{_fmt_exp(row[period_b]):>12}  {_fmt_delta(row['delta']):>12}  "
          f"{_fmt_pct(row['pct']):>8}  {flag}")


# ---------------------------------------------------------------------------
# Tool 3 — Pattern categorizer
# ---------------------------------------------------------------------------

@tool
def run_categorizer(filepath: str = "") -> str:
    """Categorize transactions into spending categories.

    Use when transactions need category labels — for example, after importing
    a new bank statement, or when the user asks what type of spending each
    transaction represents.

    Applies deterministic regex patterns against a library of Canadian
    merchants (groceries, dining, transit, subscriptions, etc.) to assign
    categories such as GROCERIES, DINING, TRANSPORTATION, SUBSCRIPTIONS.
    Transactions that don't match any pattern are flagged for LLM review.

    Parameters
    ----------
    filepath:
        Path to a CSV bank statement file to categorize.  Accepts RBC
        chequing CSV format (columns: Date, Description, Debit, Credit,
        Balance).  If empty, uses the default mock chequing file.
    """
    from src.skills.registry import run_skill_script

    input_path = filepath if filepath else str(_ROOT / "data" / "mock" / "rbc_chequing_2025.csv")

    if not Path(input_path).exists():
        return f"[ERROR] File not found: {input_path}"

    try:
        output = run_skill_script(
            "transaction-categorizer",
            "pattern_categorize.py",
            ["--input", input_path, "--stats"],
        )
        return output.strip() or "Categorization completed (no output captured)."
    except (ValueError, FileNotFoundError) as exc:
        return f"[ERROR] {exc}"


# ---------------------------------------------------------------------------
# Tool 4 — Recurring transaction detection
# ---------------------------------------------------------------------------

@tool
def detect_recurring(months: int = 3) -> str:
    """Detect recurring transactions like subscriptions, bills, and regular payments.

    Use for cash flow forecasting, understanding fixed monthly costs, or
    when the user asks about recurring charges, subscriptions, or regular
    bill payments.

    Scans the transaction history and identifies series that repeat on a
    consistent schedule (weekly, bi-weekly, monthly, or quarterly) with a
    consistent amount.  Each series is classified as FIXED (same amount
    every time) or VARIABLE (predictable frequency but fluctuating amount).

    Examples of what this detects:
    - FIXED MONTHLY: Netflix, Rogers Internet, mortgage payment
    - VARIABLE MONTHLY: Toronto Hydro, Enbridge Gas, grocery runs
    - FIXED BI_WEEKLY: payroll deposits

    Parameters
    ----------
    months:
        Minimum number of occurrences required to classify a transaction as
        recurring.  Higher values reduce false positives but may miss
        recently-started subscriptions.  Default 3 (three occurrences needed).
    """
    from src.skills.registry import run_skill_script

    # Use a temp file for the JSON output; we return the human-readable stdout
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix="recurring_")
    os.close(tmp_fd)

    try:
        output = run_skill_script(
            "cashflow-forecaster",
            "detect_recurring.py",
            ["--output", tmp_path, "--min-occurrences", str(months), "--show-skipped"],
        )
        return output.strip() or "Detection completed (no output captured)."
    except (ValueError, FileNotFoundError) as exc:
        return f"[ERROR] {exc}"
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Tool 5 — Skill instruction loader
# ---------------------------------------------------------------------------

@tool
def load_skill_instructions(skill_name: str) -> str:
    """Load detailed step-by-step instructions for a specific skill.

    Use this when you need the full how-to guide for a skill before
    executing a complex task.  Each skill's instructions include decision
    rules, edge cases, output formats, and example commands to run.

    Available skills
    ----------------
    "statement-parser"
        How to parse RBC chequing, Visa, and mortgage CSV files into
        standardized transaction records.

    "transaction-categorizer"
        Two-pass pipeline (regex patterns + LLM) for labelling transactions
        with spending categories.  Includes confidence scoring.

    "spend-analyzer"
        Six query types for answering spending questions: period summary,
        category breakdown, comparison, top-N, trend, anomaly detection.

    "cashflow-forecaster"
        Detect recurring transactions and project the account balance
        forward 30/60/90 days.  Includes risk-flag logic.

    Parameters
    ----------
    skill_name:
        One of the four skill names listed above.
    """
    from src.skills.registry import load_skill

    try:
        return load_skill(skill_name)
    except ValueError:
        available = ["statement-parser", "transaction-categorizer",
                     "spend-analyzer", "cashflow-forecaster"]
        return (
            f"[ERROR] Skill '{skill_name}' not found. "
            f"Available skills: {', '.join(available)}"
        )


# ---------------------------------------------------------------------------
# Public registry
# ---------------------------------------------------------------------------

def get_all_tools() -> list:
    """Return all agent tools as a list.

    Pass directly to a LangGraph ToolNode or bind to an LLM:

        from src.agents.tools import get_all_tools
        tools = get_all_tools()
        llm_with_tools = llm.bind_tools(tools)
    """
    return [
        vector_search,
        sql_query,
        run_categorizer,
        detect_recurring,
        load_skill_instructions,
    ]
