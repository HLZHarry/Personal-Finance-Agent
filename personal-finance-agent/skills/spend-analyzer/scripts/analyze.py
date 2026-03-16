"""
Spend-Analyzer CLI helper.

Executes one of six parameterized query types against data/finance.db,
prints a formatted table to stdout, and exits.

Usage
-----
    python skills/spend-analyzer/scripts/analyze.py --query-type period-summary \\
        --start-date 2025-01-01 --end-date 2025-01-31

    python skills/spend-analyzer/scripts/analyze.py --query-type comparison \\
        --period-a 2026-01 --period-b 2026-02

    python skills/spend-analyzer/scripts/analyze.py --query-type top-n --n 10

    python skills/spend-analyzer/scripts/analyze.py --query-type trend \\
        --category DINING

    python skills/spend-analyzer/scripts/analyze.py --query-type anomaly

    python skills/spend-analyzer/scripts/analyze.py --query-type category-breakdown \\
        --category GROCERIES --start-date 2025-01-01 --end-date 2025-01-31

Query types
-----------
    period-summary      category totals for a date range
    category-breakdown  individual transactions in one category
    comparison          two periods side-by-side
    top-n               largest N expense transactions
    trend               monthly totals for one category over time
    anomaly             transactions > 2 SD above category mean
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import math

import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_DB = str(Path(__file__).parent.parent.parent.parent / "data" / "finance.db")

# Width at which to truncate description strings in tables
DESC_WIDTH = 38

# Categories excluded from expense-focused views
_EXCLUDE_FROM_EXPENSES = {"INCOME", "TRANSFER"}


# ---------------------------------------------------------------------------
# Currency / percentage formatters
# ---------------------------------------------------------------------------

def _fmt_cad(v) -> str:
    """Signed formatter: -$X.XX for expenses, +$X.XX for income, used for deltas."""
    if v is None or (isinstance(v, float) and v != v):   # NaN check
        return "n/a"
    sign = "-" if v < 0 else ("+" if v > 0 else " ")
    return f"{sign}${abs(float(v)):>9,.2f}"


def _fmt_exp(v) -> str:
    """Unsigned expense formatter: $X.XX — for columns that are already ABS values."""
    if v is None or (isinstance(v, float) and v != v):
        return "n/a"
    return f" ${abs(float(v)):>9,.2f}"


def _fmt_pct(v) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return "   n/a"
    return f"{float(v):+6.1f}%"


def _fmt_trend(pct) -> str:
    if pct is None or (isinstance(pct, float) and pct != pct):
        return "  —"
    return "[+]" if pct > 2 else ("[-]" if pct < -2 else "[=]")


def _trunc(s: str, width: int = DESC_WIDTH) -> str:
    s = str(s)
    return s if len(s) <= width else s[: width - 1] + "~"


# ---------------------------------------------------------------------------
# DB connection
# ---------------------------------------------------------------------------

def _connect(db_path: str) -> sqlite3.Connection:
    p = Path(db_path)
    if not p.exists():
        print(
            f"[ERROR] Database not found: {db_path}\n"
            "        Run `python -m src.pipeline` to ingest statements first.",
            file=sys.stderr,
        )
        sys.exit(1)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # SQLite omits math functions; register the ones the queries need.
    conn.create_function("SQRT", 1, lambda x: math.sqrt(x) if x and x > 0 else 0.0)
    return conn


def _q(conn: sqlite3.Connection, sql: str) -> pd.DataFrame:
    return pd.read_sql_query(sql, conn)


# ---------------------------------------------------------------------------
# Query runners
# ---------------------------------------------------------------------------

def run_period_summary(conn, start_date: str, end_date: str) -> None:
    sql = f"""
        SELECT
            category,
            COUNT(*)                                                         AS txns,
            ROUND(SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END), 2) AS expenses,
            ROUND(SUM(CASE WHEN amount > 0 THEN amount      ELSE 0 END), 2) AS income,
            ROUND(AVG(CASE WHEN amount < 0 THEN ABS(amount) END), 2)        AS avg_expense
        FROM transactions
        WHERE date BETWEEN '{start_date}' AND '{end_date}'
          AND account_type != 'mortgage'
        GROUP BY category
        ORDER BY expenses DESC
    """
    df = _q(conn, sql)
    if df.empty:
        print(f"No transactions found between {start_date} and {end_date}.")
        return

    expense_rows = df[~df["category"].isin(_EXCLUDE_FROM_EXPENSES)]
    total_exp = expense_rows["expenses"].sum()

    df["pct"] = df["expenses"].apply(
        lambda e: (e / total_exp * 100) if total_exp > 0 else 0.0
    )

    print(f"\n  Period Summary: {start_date} to {end_date}")
    print(f"  {'Category':<18} {'Txns':>5}  {'Expenses':>12}  {'% Total':>8}  {'Avg/Txn':>12}")
    print(f"  {'-'*18}  {'-'*5}  {'-'*12}  {'-'*8}  {'-'*12}")
    for _, row in df.iterrows():
        if row["category"] in _EXCLUDE_FROM_EXPENSES:
            continue
        print(
            f"  {row['category']:<18} {int(row['txns']):>5}  "
            f"{_fmt_exp(row['expenses']):>12}  {row['pct']:>7.1f}%  "
            f"{_fmt_exp(row['avg_expense']):>12}"
        )
    print(f"  {'-'*18}  {'-'*5}  {'-'*12}  {'-'*8}  {'-'*12}")
    print(f"  {'TOTAL':<18} {'':>5}  {_fmt_exp(total_exp):>12}  {'100.0%':>8}")

    income_rows = df[df["category"] == "INCOME"]
    if not income_rows.empty:
        total_inc = income_rows["income"].sum()
        print(f"\n  Income: {_fmt_exp(total_inc)}   Net: {_fmt_cad(total_inc - total_exp)}")

    uncategorized = df[df["category"] == "UNCATEGORIZED"]
    if not uncategorized.empty and uncategorized["txns"].values[0] > 0:
        print(
            f"\n  * {int(uncategorized['txns'].values[0])} UNCATEGORIZED transactions "
            "excluded from breakdown — run transaction-categorizer for full accuracy."
        )


def run_category_breakdown(conn, category: str, start_date: str, end_date: str) -> None:
    header_sql = f"""
        SELECT COUNT(*) AS txns,
               ROUND(SUM(ABS(amount)), 2) AS total,
               ROUND(AVG(ABS(amount)), 2) AS avg_txn,
               ROUND(MAX(ABS(amount)), 2) AS largest
        FROM transactions
        WHERE date BETWEEN '{start_date}' AND '{end_date}'
          AND category = '{category.upper()}'
          AND amount < 0
    """
    detail_sql = f"""
        SELECT date, description, ROUND(ABS(amount), 2) AS amount
        FROM transactions
        WHERE date BETWEEN '{start_date}' AND '{end_date}'
          AND category = '{category.upper()}'
          AND amount < 0
        ORDER BY amount DESC
    """
    h = _q(conn, header_sql).iloc[0]
    detail = _q(conn, detail_sql)

    print(f"\n  Category Breakdown: {category.upper()}  ({start_date} to {end_date})")
    print(f"  Transactions: {int(h['txns'])}   Total: {_fmt_cad(h['total'])}   "
          f"Avg: {_fmt_cad(h['avg_txn'])}   Largest: {_fmt_cad(h['largest'])}")
    if detail.empty:
        print("  (no expense transactions)")
        return
    print(f"\n  {'Date':<12} {'Description':<{DESC_WIDTH+2}} {'Amount':>12}")
    print(f"  {'-'*12}  {'-'*(DESC_WIDTH+2)}  {'-'*12}")
    for _, row in detail.iterrows():
        print(f"  {row['date']:<12}  {_trunc(row['description']):<{DESC_WIDTH+2}}  "
              f"{_fmt_exp(row['amount']):>12}")


def run_comparison(conn, period_a: str, period_b: str) -> None:
    def _month_bounds(ym: str) -> tuple[str, str]:
        import calendar
        y, m = int(ym[:4]), int(ym[5:7])
        last = calendar.monthrange(y, m)[1]
        return f"{ym}-01", f"{ym}-{last:02d}"

    sa, ea = _month_bounds(period_a)
    sb, eb = _month_bounds(period_b)

    def _period_df(start, end, label):
        sql = f"""
            SELECT category,
                   ROUND(SUM(ABS(amount)), 2) AS expenses
            FROM transactions
            WHERE date BETWEEN '{start}' AND '{end}'
              AND amount < 0
            GROUP BY category
        """
        df = _q(conn, sql).rename(columns={"expenses": label})
        return df.set_index("category")

    a = _period_df(sa, ea, period_a)
    b = _period_df(sb, eb, period_b)
    merged = a.join(b, how="outer").fillna(0.0)
    merged["delta"] = merged[period_b] - merged[period_a]
    merged["change_pct"] = merged.apply(
        lambda r: (r["delta"] / r[period_a] * 100) if r[period_a] != 0 else float("nan"),
        axis=1,
    )
    merged = merged.sort_values(period_b, ascending=False)

    print(f"\n  Comparison: {period_a} vs {period_b}")
    print(f"  {'Category':<18} {period_a:>12}  {period_b:>12}  {'Delta':>12}  {'Change':>8}")
    print(f"  {'-'*18}  {'-'*12}  {'-'*12}  {'-'*12}  {'-'*8}")
    for cat, row in merged.iterrows():
        if cat in _EXCLUDE_FROM_EXPENSES:
            continue
        flag = " (!)" if abs(row["change_pct"]) > 20 and row[period_a] > 0 else "    "
        print(
            f"  {str(cat):<18}  {_fmt_exp(row[period_a]):>12}  "
            f"{_fmt_exp(row[period_b]):>12}  {_fmt_cad(row['delta']):>12}  "
            f"{_fmt_pct(row['change_pct']):>8}{flag}"
        )


def run_top_n(conn, n: int, category: str | None, start_date: str | None,
              end_date: str | None) -> None:
    cat_filter  = f"AND category = '{category.upper()}'" if category else ""
    date_filter = (f"AND date BETWEEN '{start_date}' AND '{end_date}'"
                   if start_date and end_date else "")
    sql = f"""
        SELECT date, description, category,
               ROUND(ABS(amount), 2) AS amount
        FROM transactions
        WHERE amount < 0
          {cat_filter}
          {date_filter}
        ORDER BY amount DESC
        LIMIT {n}
    """
    df = _q(conn, sql)
    title_parts = [f"Top {n} Expenses"]
    if category:
        title_parts.append(f"in {category.upper()}")
    if start_date and end_date:
        title_parts.append(f"({start_date} to {end_date})")
    print(f"\n  {' '.join(title_parts)}")
    print(f"  {'#':>3}  {'Date':<12}  {'Description':<{DESC_WIDTH}}  {'Category':<16}  {'Amount':>12}")
    print(f"  {'-'*3}  {'-'*12}  {'-'*DESC_WIDTH}  {'-'*16}  {'-'*12}")
    for rank, (_, row) in enumerate(df.iterrows(), 1):
        print(
            f"  {rank:>3}  {row['date']:<12}  {_trunc(row['description']):<{DESC_WIDTH}}  "
            f"{row['category']:<16}  {_fmt_exp(row['amount']):>12}"
        )


def run_trend(conn, category: str | None, start_date: str | None,
              end_date: str | None) -> None:
    cat_filter  = f"AND category = '{category.upper()}'" if category else ""
    date_filter = (f"AND date BETWEEN '{start_date}' AND '{end_date}'"
                   if start_date and end_date else "")
    sql = f"""
        SELECT substr(date,1,7) AS month,
               COUNT(*) AS txns,
               ROUND(SUM(ABS(amount)), 2) AS total
        FROM transactions
        WHERE amount < 0
          {cat_filter}
          {date_filter}
        GROUP BY month
        ORDER BY month
    """
    df = _q(conn, sql)
    if df.empty:
        print("No data found for trend query.")
        return

    df["mom_delta"] = df["total"].diff()
    df["mom_pct"]   = df["total"].pct_change() * 100
    df["trend"]     = df["mom_pct"].apply(_fmt_trend)

    title = f"Monthly Trend: {category.upper() if category else 'All Expenses'}"
    if start_date and end_date:
        title += f" ({start_date[:7]} to {end_date[:7]})"
    print(f"\n  {title}")
    print(f"  {'Month':<9}  {'Txns':>5}  {'Total':>12}  {'MoM Delta':>12}  {'MoM %':>8}  Trend")
    print(f"  {'-'*9}  {'-'*5}  {'-'*12}  {'-'*12}  {'-'*8}  {'-'*5}")
    for _, row in df.iterrows():
        delta_str = _fmt_cad(row["mom_delta"]) if not pd.isna(row["mom_delta"]) else "           --"
        pct_str   = _fmt_pct(row["mom_pct"])   if not pd.isna(row["mom_pct"])   else "      --"
        trend_str = row["trend"] if not pd.isna(row["mom_pct"]) else "  --"
        print(
            f"  {row['month']:<9}  {int(row['txns']):>5}  {_fmt_exp(row['total']):>12}  "
            f"{delta_str:>12}  {pct_str:>8}  {trend_str}"
        )


def run_anomaly(conn) -> None:
    sql = """
        WITH stats AS (
            SELECT category,
                   AVG(ABS(amount))  AS cat_mean,
                   MAX(                           -- SQLite has no STDDEV; use variance trick
                       ABS(amount)*ABS(amount)
                   ) - AVG(ABS(amount))*AVG(ABS(amount)) AS cat_var
            FROM transactions
            WHERE amount < 0
              AND date >= date('now', '-90 days')
            GROUP BY category
            HAVING COUNT(*) >= 3
        )
        SELECT t.date, t.description, t.category,
               ROUND(ABS(t.amount), 2)               AS amount,
               ROUND(s.cat_mean, 2)                  AS cat_avg,
               ROUND(ABS(t.amount)/s.cat_mean, 1)    AS times_avg
        FROM transactions t
        JOIN stats s ON t.category = s.category
        WHERE t.amount < 0
          AND t.date >= date('now', '-90 days')
          AND ABS(t.amount) > s.cat_mean + 2 * SQRT(MAX(s.cat_var, 0))
        ORDER BY times_avg DESC
    """
    df = _q(conn, sql)
    print("\n  Anomaly Detection (trailing 90 days, >2x category average)")
    if df.empty:
        print("  No unusual transactions detected.")
        return
    print(f"  {'Date':<12}  {'Description':<{DESC_WIDTH}}  {'Category':<16}  "
          f"{'Amount':>12}  {'Cat Avg':>12}  {'x Avg':>6}")
    print(f"  {'-'*12}  {'-'*DESC_WIDTH}  {'-'*16}  {'-'*12}  {'-'*12}  {'-'*6}")
    for _, row in df.iterrows():
        print(
            f"  {row['date']:<12}  {_trunc(row['description']):<{DESC_WIDTH}}  "
            f"{row['category']:<16}  {_fmt_exp(row['amount']):>12}  "
            f"{_fmt_exp(row['cat_avg']):>12}  {row['times_avg']:>5.1f}x"
        )
    print(f"\n  * Anomaly detection requires >= 3 prior transactions per category.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(
        description="Spend-Analyzer: run a financial query against finance.db.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--query-type", "-q", required=True,
                   choices=["period-summary", "category-breakdown",
                            "comparison", "top-n", "trend", "anomaly"],
                   help="Type of analysis to run.")
    p.add_argument("--db",          default=DEFAULT_DB,
                   help=f"Path to SQLite database (default: {DEFAULT_DB}).")
    p.add_argument("--start-date",  metavar="YYYY-MM-DD",
                   help="Start of date range (inclusive).")
    p.add_argument("--end-date",    metavar="YYYY-MM-DD",
                   help="End of date range (inclusive).")
    p.add_argument("--period-a",    metavar="YYYY-MM",
                   help="First period for comparison (YYYY-MM).")
    p.add_argument("--period-b",    metavar="YYYY-MM",
                   help="Second period for comparison (YYYY-MM).")
    p.add_argument("--category",    metavar="CATEGORY",
                   help="Category filter (e.g. DINING, GROCERIES).")
    p.add_argument("--n",           type=int, default=10,
                   help="Number of results for top-n (default: 10).")
    args = p.parse_args()

    conn = _connect(args.db)

    try:
        if args.query_type == "period-summary":
            if not args.start_date or not args.end_date:
                p.error("--start-date and --end-date required for period-summary")
            run_period_summary(conn, args.start_date, args.end_date)

        elif args.query_type == "category-breakdown":
            if not args.category:
                p.error("--category required for category-breakdown")
            start = args.start_date or "2000-01-01"
            end   = args.end_date   or "2099-12-31"
            run_category_breakdown(conn, args.category, start, end)

        elif args.query_type == "comparison":
            if not args.period_a or not args.period_b:
                p.error("--period-a and --period-b required for comparison")
            run_comparison(conn, args.period_a, args.period_b)

        elif args.query_type == "top-n":
            run_top_n(conn, args.n, args.category, args.start_date, args.end_date)

        elif args.query_type == "trend":
            run_trend(conn, args.category, args.start_date, args.end_date)

        elif args.query_type == "anomaly":
            run_anomaly(conn)

    finally:
        conn.close()
    print()


if __name__ == "__main__":
    main()
