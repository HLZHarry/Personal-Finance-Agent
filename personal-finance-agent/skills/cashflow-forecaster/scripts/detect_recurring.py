"""
Detect recurring transactions from the finance SQLite database.

Groups transactions by exact description, then applies statistical rules to
identify series that recur on a consistent schedule with a consistent amount.

Output JSON schema (one object per recurring series)
----------------------------------------------------
[
  {
    "description":       "NETFLIX.COM",
    "category":          "SUBSCRIPTIONS",
    "amount_type":       "FIXED",        // FIXED | STABLE | VARIABLE | HIGH_VARIANCE
    "frequency":         "MONTHLY",      // WEEKLY | BI_WEEKLY | MONTHLY | QUARTERLY
    "amount_avg":        -18.99,
    "amount_median":     -18.99,
    "amount_stdev":      0.0,
    "amount_cv":         0.0,
    "occurrences":       13,
    "gap_mean_days":     32.4,
    "gap_stdev_days":    1.1,
    "first_seen":        "2025-01-09",
    "last_seen":         "2026-01-07",
    "next_expected":     "2026-02-06"    // last_seen + round(gap_mean_days)
  }
]

Usage
-----
    python skills/cashflow-forecaster/scripts/detect_recurring.py

    python skills/cashflow-forecaster/scripts/detect_recurring.py \\
        --db data/finance.db \\
        --min-occurrences 3 \\
        --output recurring.json \\
        --show-skipped

Exit codes: 0 success, 1 error
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from statistics import median, mean, stdev


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_DB  = str(Path(__file__).parent.parent.parent.parent / "data" / "finance.db")


def _emit(msg: str) -> None:
    """UTF-8-safe print — survives Windows cp1252 consoles."""
    sys.stdout.buffer.write((msg + "\n").encode("utf-8", errors="replace"))
DEFAULT_OUT = "recurring.json"

# Minimum number of occurrences to consider a series
MIN_OCCURRENCES = 3

# Gap consistency: gap_stdev / gap_mean must be below this to be "regular"
GAP_CV_THRESHOLD = 0.35

# Gap plausibility bounds (days)
GAP_MIN = 6
GAP_MAX = 120

# Amount classification thresholds (coefficient of variation)
CV_FIXED        = 0.10
CV_STABLE       = 0.35
CV_HIGH_VARIANCE = 0.70

# Frequency bins (mean gap in days)
FREQ_BINS = [
    (0,   9,   "WEEKLY"),
    (9,  19,   "BI_WEEKLY"),
    (19, 45,   "MONTHLY"),
    (45, 120,  "QUARTERLY"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _classify_frequency(mean_gap: float) -> str:
    for lo, hi, label in FREQ_BINS:
        if lo <= mean_gap < hi:
            return label
    return "IRREGULAR"


def _classify_amount(cv: float) -> str:
    if cv < CV_FIXED:
        return "FIXED"
    if cv < CV_STABLE:
        return "STABLE"
    if cv < CV_HIGH_VARIANCE:
        return "VARIABLE"
    return "HIGH_VARIANCE"


def _next_expected(last_date: date, mean_gap: float) -> date:
    return last_date + timedelta(days=round(mean_gap))


def _gap_stats(dates: list[date]) -> tuple[float, float]:
    """Return (mean_gap, stdev_gap) from a sorted list of dates."""
    gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
    m = mean(gaps)
    s = stdev(gaps) if len(gaps) >= 2 else 0.0
    return m, s


def _amount_stats(amounts: list[float]) -> tuple[float, float, float, float]:
    """Return (avg, median_val, std, cv) — all based on absolute values."""
    abs_amounts = [abs(a) for a in amounts]
    avg = mean(abs_amounts)
    med = median(abs_amounts)
    std = stdev(abs_amounts) if len(abs_amounts) >= 2 else 0.0
    cv  = (std / avg) if avg > 0 else 0.0
    # Preserve the sign of the original series (negative = expense)
    sign = -1 if mean(amounts) < 0 else 1
    return round(sign * avg, 2), round(sign * med, 2), round(std, 2), round(cv, 4)


def _distinct_months(dates: list[date]) -> int:
    return len({(d.year, d.month) for d in dates})


# ---------------------------------------------------------------------------
# Core detection
# ---------------------------------------------------------------------------

def detect_recurring(
    db_path: str,
    min_occurrences: int = MIN_OCCURRENCES,
) -> tuple[list[dict], list[dict]]:
    """
    Load all transactions from SQLite and detect recurring series.

    Returns
    -------
    (recurring, skipped)
        recurring – list of dicts matching the output schema above
        skipped   – list of dicts explaining why each rejected series was skipped
    """
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT date, description, amount, category "
        "FROM transactions ORDER BY date"
    ).fetchall()
    conn.close()

    if not rows:
        print("[detect_recurring] No transactions found in database.", file=sys.stderr)
        return [], []

    # Group by description
    groups: dict[str, list[tuple[date, float, str]]] = defaultdict(list)
    for date_str, desc, amount, category in rows:
        groups[desc].append((date.fromisoformat(date_str), amount, category))

    recurring: list[dict] = []
    skipped:   list[dict] = []

    for desc, entries in groups.items():
        n = len(entries)
        skip_reason: str | None = None

        # --- Filter: minimum occurrences ---
        if n < min_occurrences:
            skip_reason = f"only {n} occurrence(s) — need {min_occurrences}"

        dates   = sorted(e[0] for e in entries)
        amounts = [e[1] for e in entries]

        # --- Filter: dedup exact same date+amount (NSF bounce pattern) ---
        seen: set[tuple] = set()
        deduped: list[tuple[date, float]] = []
        for d, a in zip(dates, amounts):
            key = (d, round(a, 2))
            if key not in seen:
                seen.add(key)
                deduped.append((d, a))
        if len(deduped) < n:
            dates   = [x[0] for x in deduped]
            amounts = [x[1] for x in deduped]
            n       = len(deduped)
            if n < min_occurrences:
                skip_reason = (
                    f"only {n} unique (date, amount) pairs after dedup — "
                    f"need {min_occurrences}"
                )

        if skip_reason is None:
            gap_mean, gap_std = _gap_stats(dates)
            gap_cv = (gap_std / gap_mean) if gap_mean > 0 else 99.0

            # --- Filter: gap plausibility ---
            if not (GAP_MIN <= gap_mean <= GAP_MAX):
                skip_reason = (
                    f"mean gap {gap_mean:.1f}d outside plausible range "
                    f"[{GAP_MIN}, {GAP_MAX}]"
                )

            # --- Filter: gap consistency ---
            elif gap_cv > GAP_CV_THRESHOLD:
                skip_reason = (
                    f"inconsistent gaps (gap_cv={gap_cv:.2f} > {GAP_CV_THRESHOLD}) — "
                    "timing is too irregular to project reliably"
                )

            # --- Filter: must span at least 2 calendar months ---
            elif _distinct_months(dates) < 2:
                skip_reason = (
                    "all occurrences fall within a single calendar month — "
                    "may be a coincidental cluster, not a recurring schedule"
                )

        if skip_reason:
            skipped.append({"description": desc, "occurrences": n, "reason": skip_reason})
            continue

        # --- Classify ---
        gap_mean, gap_std = _gap_stats(dates)
        frequency = _classify_frequency(gap_mean)
        category  = entries[0][2]  # use the category from the first occurrence
        avg, med, std_amt, cv = _amount_stats(amounts)
        amount_type = _classify_amount(cv)

        recurring.append({
            "description":    desc,
            "category":       category,
            "amount_type":    amount_type,
            "frequency":      frequency,
            "amount_avg":     avg,
            "amount_median":  med,
            "amount_stdev":   std_amt,
            "amount_cv":      cv,
            "occurrences":    n,
            "gap_mean_days":  round(gap_mean, 1),
            "gap_stdev_days": round(gap_std, 1),
            "first_seen":     str(dates[0]),
            "last_seen":      str(dates[-1]),
            "next_expected":  str(_next_expected(dates[-1], gap_mean)),
        })

    # Sort: fixed income first, then fixed expenses, then variable
    def _sort_key(r):
        order = {"FIXED": 0, "STABLE": 1, "VARIABLE": 2, "HIGH_VARIANCE": 3}
        income_last = 0 if r["amount_avg"] < 0 else 1  # expenses before income? no — income first
        return (income_last, order.get(r["amount_type"], 9), r["description"])

    recurring.sort(key=lambda r: (r["amount_avg"] > 0, r["amount_type"], r["description"]))

    return recurring, skipped


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(
        description="Detect recurring transactions from finance.db.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--db",              default=DEFAULT_DB,
                   help=f"SQLite database path (default: {DEFAULT_DB}).")
    p.add_argument("--min-occurrences", type=int, default=MIN_OCCURRENCES,
                   help=f"Minimum occurrences to consider (default: {MIN_OCCURRENCES}).")
    p.add_argument("--output",  "-o",   default=DEFAULT_OUT,
                   help=f"Output JSON file (default: {DEFAULT_OUT}).")
    p.add_argument("--show-skipped",    action="store_true",
                   help="Also print the rejected series and why.")
    args = p.parse_args()

    if not Path(args.db).exists():
        print(f"[ERROR] Database not found: {args.db}", file=sys.stderr)
        sys.exit(1)

    recurring, skipped = detect_recurring(args.db, args.min_occurrences)

    # Write JSON output
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(recurring, fh, indent=2)

    # Print human-readable summary
    fixed    = [r for r in recurring if r["amount_type"] == "FIXED"]
    variable = [r for r in recurring if r["amount_type"] != "FIXED"]

    _emit(f"\n  Recurring transaction detection: {args.db}")
    _emit(f"  Detected: {len(recurring)}   Skipped: {len(skipped)}\n")

    if recurring:
        _emit(f"  {'Description':<42} {'Type':<13} {'Freq':<12} {'Avg Amt':>10}  {'Next Expected'}")
        _emit(f"  {'-'*42}  {'-'*13}  {'-'*12}  {'-'*10}  {'-'*13}")
        for r in recurring:
            sign = "+" if r["amount_avg"] > 0 else "-"
            amt  = f"{sign}${abs(r['amount_avg']):>8,.2f}"
            _emit(
                f"  {r['description'][:42]:<42}  {r['amount_type']:<13}  "
                f"{r['frequency']:<12}  {amt:>10}  {r['next_expected']}"
            )

    if args.show_skipped and skipped:
        _emit(f"\n  Skipped series ({len(skipped)}):")
        for s in skipped:
            _emit(f"    {s['description'][:50]:<50}  n={s['occurrences']}  {s['reason']}")

    _emit(f"\n  Wrote {len(recurring)} recurring series to: {args.output}")


if __name__ == "__main__":
    main()
