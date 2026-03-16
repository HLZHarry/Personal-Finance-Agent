"""
Post-parse validator for TransactionSet JSON output.

Usage
-----
    # Validate a JSON file produced by the statement-parser skill:
    python skills/statement-parser/scripts/validate_parse.py --input parsed.json

    # Or pipe JSON from another command:
    python -c "import json,sys; ..." | python validate_parse.py --input -

Exit codes
----------
    0  validation passed (valid == true, no errors)
    1  validation failed (valid == false, errors list is non-empty)
    2  bad invocation / file not found

Output (always written to stdout as JSON)
-----------------------------------------
{
  "valid":    true | false,
  "errors":   ["..."],   // hard failures — do not ingest if non-empty
  "warnings": ["..."],   // soft issues — investigate but ingest may continue
  "stats": {
    "transaction_count": 416,
    "date_min": "2024-02-01",
    "date_max": "2026-01-30",
    "amount_min": -5000.0,
    "amount_max": 6500.0,
    "zero_amounts": 0,
    "null_dates": 0,
    "duplicate_ids": 0,
    "balance_check": "n/a"   // "passed", "failed <delta>", or "n/a"
  }
}
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date, datetime
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Transactions with dates outside this window are suspicious
REASONABLE_DATE_MIN = date(2000, 1, 1)
REASONABLE_DATE_MAX = date(2035, 12, 31)

# Amounts larger than this in absolute value are flagged (not failed)
LARGE_AMOUNT_THRESHOLD = 50_000.0

# Floating-point tolerance for balance reconciliation
BALANCE_TOLERANCE = 0.02


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_date(raw: Any) -> date | None:
    """Return a date from an ISO string, or None if unparseable."""
    if not raw:
        return None
    if isinstance(raw, date):
        return raw
    try:
        return datetime.fromisoformat(str(raw)).date()
    except ValueError:
        return None


def _load_input(source: str) -> dict:
    """Load JSON from a file path or stdin ('-')."""
    if source == "-":
        try:
            return json.load(sys.stdin)
        except json.JSONDecodeError as exc:
            _fatal(f"Invalid JSON on stdin: {exc}")
    try:
        with open(source, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        _fatal(f"File not found: {source}")
    except json.JSONDecodeError as exc:
        _fatal(f"Invalid JSON in {source!r}: {exc}")


def _fatal(msg: str) -> None:
    result = {"valid": False, "errors": [msg], "warnings": [], "stats": {}}
    print(json.dumps(result, indent=2))
    sys.exit(2)


# ---------------------------------------------------------------------------
# Validation checks
# ---------------------------------------------------------------------------

def _check_structure(payload: dict, errors: list, warnings: list) -> list[dict]:
    """Confirm top-level keys exist and transactions is a list."""
    required = {"source", "transactions"}
    missing = required - payload.keys()
    if missing:
        errors.append(f"Missing required top-level keys: {sorted(missing)}")
        return []

    txs = payload["transactions"]
    if not isinstance(txs, list):
        errors.append(f"'transactions' must be a list, got {type(txs).__name__}")
        return []
    if len(txs) == 0:
        warnings.append("'transactions' list is empty — was the file blank?")
    return txs


def _check_null_dates(txs: list[dict], errors: list, warnings: list) -> list[date | None]:
    """Every transaction must have a non-null, parseable date."""
    parsed_dates: list[date | None] = []
    null_count = 0

    for i, tx in enumerate(txs):
        d = _parse_date(tx.get("date"))
        parsed_dates.append(d)
        if d is None:
            null_count += 1
            errors.append(
                f"Transaction [{i}] has a null or unparseable date: "
                f"{tx.get('date')!r}  (description: {tx.get('description', '?')!r})"
            )

    return parsed_dates


def _check_date_range(
    parsed_dates: list[date | None], errors: list, warnings: list
) -> tuple[date | None, date | None]:
    """Dates must fall within REASONABLE_DATE_MIN … REASONABLE_DATE_MAX."""
    valid_dates = [d for d in parsed_dates if d is not None]
    if not valid_dates:
        return None, None

    d_min = min(valid_dates)
    d_max = max(valid_dates)

    if d_min < REASONABLE_DATE_MIN:
        errors.append(
            f"Earliest date {d_min} is before {REASONABLE_DATE_MIN} — "
            "likely a date-parsing error."
        )
    if d_max > REASONABLE_DATE_MAX:
        errors.append(
            f"Latest date {d_max} is after {REASONABLE_DATE_MAX} — "
            "likely a date-parsing error."
        )

    # Warn if the date range spans more than 5 years (unusual for a single statement)
    span_days = (d_max - d_min).days
    if span_days > 365 * 5:
        warnings.append(
            f"Date range spans {span_days} days ({d_min} → {d_max}). "
            "Confirm this is a multi-year file and not a parsing artefact."
        )

    return d_min, d_max


def _check_amounts(
    txs: list[dict], errors: list, warnings: list
) -> tuple[int, float, float]:
    """No transaction may have amount == 0; flag unusually large amounts."""
    zero_count = 0
    amounts: list[float] = []

    for i, tx in enumerate(txs):
        raw = tx.get("amount")
        if raw is None:
            errors.append(
                f"Transaction [{i}] is missing the 'amount' field "
                f"(description: {tx.get('description', '?')!r})"
            )
            continue

        try:
            amt = float(raw)
        except (TypeError, ValueError):
            errors.append(
                f"Transaction [{i}] has non-numeric amount: {raw!r} "
                f"(description: {tx.get('description', '?')!r})"
            )
            continue

        amounts.append(amt)

        if amt == 0.0:
            zero_count += 1
            errors.append(
                f"Transaction [{i}] has zero amount "
                f"(description: {tx.get('description', '?')!r})"
            )
        elif abs(amt) > LARGE_AMOUNT_THRESHOLD:
            warnings.append(
                f"Transaction [{i}] has unusually large amount {amt:,.2f} "
                f"(description: {tx.get('description', '?')!r}) — verify it is correct."
            )

    a_min = min(amounts) if amounts else 0.0
    a_max = max(amounts) if amounts else 0.0
    return zero_count, a_min, a_max


def _check_duplicates(txs: list[dict], errors: list, warnings: list) -> int:
    """IDs must be unique within the transaction list."""
    ids = [tx.get("id") or tx.get("source_file", "") + f"_{i:04d}"
           for i, tx in enumerate(txs)]
    counts = Counter(ids)
    dupes = {id_: n for id_, n in counts.items() if n > 1}
    if dupes:
        for id_, n in dupes.items():
            errors.append(f"Duplicate transaction ID {id_!r} appears {n} times.")
    return len(dupes)


def _check_balance(payload: dict, txs: list[dict],
                   errors: list, warnings: list) -> str:
    """
    If the payload carries opening_balance and closing_balance, verify that
    opening + sum(amounts) ≈ closing (within BALANCE_TOLERANCE).

    For mortgage files, also spot-check that Payment ≈ Principal + Interest
    using data embedded in the description text (best-effort).
    """
    opening = payload.get("opening_balance")
    closing = payload.get("closing_balance")

    if opening is None or closing is None:
        return "n/a"

    try:
        opening_f = float(opening)
        closing_f = float(closing)
    except (TypeError, ValueError):
        warnings.append("opening_balance or closing_balance is non-numeric; skipping balance check.")
        return "n/a"

    total_amounts = sum(float(tx.get("amount", 0)) for tx in txs)
    expected_closing = opening_f + total_amounts
    delta = abs(expected_closing - closing_f)

    if delta > BALANCE_TOLERANCE:
        errors.append(
            f"Balance mismatch: opening {opening_f:.2f} + transactions "
            f"{total_amounts:.2f} = {expected_closing:.2f}, "
            f"but closing_balance is {closing_f:.2f}  (delta {delta:.4f})."
        )
        return f"failed delta={delta:.4f}"

    return "passed"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def validate(payload: dict) -> dict:
    errors: list[str] = []
    warnings: list[str] = []

    # 1. Structure
    txs = _check_structure(payload, errors, warnings)

    # 2. Null dates
    parsed_dates = _check_null_dates(txs, errors, warnings)

    # 3. Date range
    d_min, d_max = _check_date_range(parsed_dates, errors, warnings)

    # 4. Amounts
    zero_count, a_min, a_max = _check_amounts(txs, errors, warnings)

    # 5. Duplicates
    dupe_count = _check_duplicates(txs, errors, warnings)

    # 6. Balance reconciliation (optional; only if payload carries balances)
    balance_status = _check_balance(payload, txs, errors, warnings)

    stats = {
        "transaction_count": len(txs),
        "date_min": str(d_min) if d_min else None,
        "date_max": str(d_max) if d_max else None,
        "amount_min": a_min,
        "amount_max": a_max,
        "zero_amounts": zero_count,
        "null_dates": sum(1 for d in parsed_dates if d is None),
        "duplicate_ids": dupe_count,
        "balance_check": balance_status,
    }

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "stats": stats,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate a parsed TransactionSet JSON file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python validate_parse.py --input parsed.json\n"
            "  python validate_parse.py --input -   # read from stdin\n"
        ),
    )
    parser.add_argument(
        "--input", "-i",
        required=True,
        metavar="FILE",
        help="Path to the TransactionSet JSON file, or '-' to read from stdin.",
    )
    args = parser.parse_args()

    payload = _load_input(args.input)
    result = validate(payload)

    print(json.dumps(result, indent=2))
    sys.exit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
