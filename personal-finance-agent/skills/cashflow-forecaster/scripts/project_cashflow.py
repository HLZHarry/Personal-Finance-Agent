"""
Project daily account balance for the next N days using recurring transactions.

Reads the output of detect_recurring.py and a starting balance, then
schedules each recurring transaction on its expected future dates.  Prints
a daily balance table and a risk summary when the balance drops below the
configured threshold.

Usage
-----
    # Detect first, then project:
    python skills/cashflow-forecaster/scripts/detect_recurring.py --output recurring.json

    python skills/cashflow-forecaster/scripts/project_cashflow.py \\
        --recurring  recurring.json \\
        --balance    14235.67 \\
        --days       60 \\
        --threshold  2000

    # One-shot (detects + projects without writing an intermediate file):
    python skills/cashflow-forecaster/scripts/project_cashflow.py \\
        --db         data/finance.db \\
        --balance    14235.67 \\
        --days       30

Exit codes: 0 = no risk flags, 1 = one or more risk dates found, 2 = error
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_DB        = str(Path(__file__).parent.parent.parent.parent / "data" / "finance.db")
DEFAULT_DAYS      = 30
DEFAULT_THRESHOLD = 0.0


# ---------------------------------------------------------------------------
# Scheduling helpers
# ---------------------------------------------------------------------------

def _schedule_occurrences(
    last_seen: date,
    gap_days: float,
    start: date,
    end: date,
) -> list[date]:
    """
    Return all expected dates in [start, end] for a recurring item.

    Starting from next_expected (last_seen + gap_days), keep adding gap_days
    until we pass end.  Include dates on or after start.
    """
    step    = round(gap_days)
    current = last_seen + timedelta(days=step)
    result: list[date] = []
    while current <= end:
        if current >= start:
            result.append(current)
        current += timedelta(days=step)
    return result


def build_daily_events(
    recurring: list[dict],
    start: date,
    end: date,
) -> dict[date, list[dict]]:
    """
    Build a map of date → list of scheduled transactions for [start, end].
    Each scheduled transaction carries amount (using amount_median for
    VARIABLE items and amount_avg for FIXED items).
    """
    events: dict[date, list[dict]] = {}

    for item in recurring:
        last_seen = date.fromisoformat(item["last_seen"])
        gap       = item["gap_mean_days"]
        # Use median for VARIABLE/HIGH_VARIANCE to reduce outlier sensitivity
        if item["amount_type"] in ("VARIABLE", "HIGH_VARIANCE"):
            amount = item["amount_median"]
        else:
            amount = item["amount_avg"]

        for d in _schedule_occurrences(last_seen, gap, start, end):
            if d not in events:
                events[d] = []
            events[d].append({
                "description": item["description"],
                "category":    item["category"],
                "amount":      amount,
                "amount_type": item["amount_type"],
                "frequency":   item["frequency"],
            })

    return events


# ---------------------------------------------------------------------------
# Projection engine
# ---------------------------------------------------------------------------

def project(
    recurring:  list[dict],
    balance:    float,
    start:      date,
    days:       int,
    threshold:  float,
) -> tuple[list[dict], list[dict]]:
    """
    Project daily balance from start to start + days - 1.

    Returns
    -------
    (projection, risk_flags)
        projection  – one dict per day:
                      {date, events, day_net, running_balance}
        risk_flags  – subset of projection where running_balance < threshold
    """
    end    = start + timedelta(days=days - 1)
    events = build_daily_events(recurring, start, end)

    projection: list[dict] = []
    running = balance

    for i in range(days):
        today    = start + timedelta(days=i)
        day_evts = events.get(today, [])
        day_net  = sum(e["amount"] for e in day_evts)
        running  = round(running + day_net, 2)

        projection.append({
            "date":            str(today),
            "events":          day_evts,
            "day_net":         round(day_net, 2),
            "running_balance": running,
        })

    risk_flags = [
        row for row in projection if row["running_balance"] < threshold
    ]
    return projection, risk_flags


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

def _fmt(v: float) -> str:
    sign = "-" if v < 0 else ("+" if v > 0 else " ")
    return f"{sign}${abs(v):>10,.2f}"


def _fmt_bal(v: float, threshold: float) -> str:
    marker = " <!" if v < threshold else "    "
    sign = "-" if v < 0 else " "
    return f"{sign}${abs(v):>10,.2f}{marker}"


def print_projection(
    projection: list[dict],
    risk_flags: list[dict],
    threshold: float,
    show_quiet_days: bool = False,
) -> None:
    """Print daily projection table; quiet days (no events, no risk) condensed."""
    has_risk = bool(risk_flags)

    print(f"\n  {'Date':<12}  {'Transaction':<40}  {'Day Net':>13}  {'Balance':>14}")
    print(f"  {'-'*12}  {'-'*40}  {'-'*13}  {'-'*14}")

    prev_quiet_count = 0

    for row in projection:
        d       = row["date"]
        evts    = row["events"]
        day_net = row["day_net"]
        bal     = row["running_balance"]
        is_risk = bal < threshold

        if not evts and not is_risk:
            if show_quiet_days:
                print(f"  {d:<12}  {'(no scheduled transactions)':<40}  "
                      f"{'':>13}  {_fmt_bal(bal, threshold):>14}")
            else:
                prev_quiet_count += 1
            continue

        # Flush quiet count before printing an event row
        if prev_quiet_count > 0 and not show_quiet_days:
            print(f"  {'...':<12}  {f'({prev_quiet_count} quiet days)':<40}")
            prev_quiet_count = 0

        if evts:
            for j, evt in enumerate(evts):
                desc = evt["description"][:40]
                if j == 0:
                    print(
                        f"  {d:<12}  {desc:<40}  "
                        f"{_fmt(evt['amount']):>13}  {_fmt_bal(bal, threshold):>14}"
                    )
                else:
                    print(f"  {'':12}  {desc:<40}  {_fmt(evt['amount']):>13}")
        else:
            # Risk day with no events (balance drifted below threshold without a transaction)
            print(
                f"  {d:<12}  {'':40}  {'':>13}  {_fmt_bal(bal, threshold):>14}"
            )

    if prev_quiet_count > 0 and not show_quiet_days:
        print(f"  {'...':<12}  {f'({prev_quiet_count} quiet days)':<40}")

    # Risk summary
    print()
    if has_risk:
        print(f"  RISK FLAGS  (balance below threshold ${threshold:,.2f}):")
        for rf in risk_flags:
            print(
                f"    {rf['date']}  balance = {_fmt_bal(rf['running_balance'], threshold).strip()}"
            )
        min_bal  = min(rf["running_balance"] for rf in risk_flags)
        min_date = min(risk_flags, key=lambda r: r["running_balance"])["date"]
        print(f"\n  Lowest projected balance: ${min_bal:,.2f} on {min_date}")
    else:
        min_row  = min(projection, key=lambda r: r["running_balance"])
        print(
            f"  No risk dates.  "
            f"Lowest projected balance: ${min_row['running_balance']:,.2f} on {min_row['date']}"
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(
        description="Project daily cash flow from recurring transactions.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    src = p.add_mutually_exclusive_group()
    src.add_argument("--recurring", "-r", metavar="FILE",
                     help="Path to recurring.json from detect_recurring.py.")
    src.add_argument("--db",              metavar="FILE", default=None,
                     help="Run detect_recurring inline against this SQLite DB.")
    p.add_argument("--balance",   "-b", type=float, required=True,
                   help="Current account balance (CAD).")
    p.add_argument("--days",      "-d", type=int,   default=DEFAULT_DAYS,
                   help=f"Number of days to project (default: {DEFAULT_DAYS}).")
    p.add_argument("--threshold", "-t", type=float, default=DEFAULT_THRESHOLD,
                   help=f"Risk alert threshold (default: {DEFAULT_THRESHOLD}).")
    p.add_argument("--as-of-date",       metavar="YYYY-MM-DD", default=None,
                   help="Start projection from this date instead of today.")
    p.add_argument("--show-all",  action="store_true",
                   help="Print every day, not just days with transactions.")
    args = p.parse_args()

    # --- Load recurring data ---
    if args.recurring:
        rpath = Path(args.recurring)
        if not rpath.exists():
            print(f"[ERROR] Recurring file not found: {args.recurring}", file=sys.stderr)
            sys.exit(2)
        with open(rpath, encoding="utf-8") as fh:
            recurring = json.load(fh)
    elif args.db:
        # Inline detection — import sibling script
        sys.path.insert(0, str(Path(__file__).parent))
        from detect_recurring import detect_recurring as _detect
        recurring, _ = _detect(args.db)
    else:
        # Fall back to default DB path
        sys.path.insert(0, str(Path(__file__).parent))
        from detect_recurring import detect_recurring as _detect
        recurring, _ = _detect(DEFAULT_DB)

    if not recurring:
        print("[WARN] No recurring transactions detected — nothing to project.")
        sys.exit(0)

    # --- Determine start date ---
    if args.as_of_date:
        try:
            start = date.fromisoformat(args.as_of_date)
        except ValueError:
            print(f"[ERROR] Invalid date format: {args.as_of_date}  (use YYYY-MM-DD)",
                  file=sys.stderr)
            sys.exit(2)
    else:
        from datetime import date as _date
        start = _date.today()

    end = start + timedelta(days=args.days - 1)

    print(f"\n  Cash Flow Projection")
    print(f"  Period   : {start} to {end} ({args.days} days)")
    print(f"  Balance  : ${args.balance:,.2f}")
    print(f"  Threshold: ${args.threshold:,.2f}")
    print(f"  Recurring: {len(recurring)} series loaded")

    # --- Project ---
    projection, risk_flags = project(
        recurring  = recurring,
        balance    = args.balance,
        start      = start,
        days       = args.days,
        threshold  = args.threshold,
    )

    print_projection(projection, risk_flags, args.threshold, show_quiet_days=args.show_all)

    sys.exit(1 if risk_flags else 0)


if __name__ == "__main__":
    main()
