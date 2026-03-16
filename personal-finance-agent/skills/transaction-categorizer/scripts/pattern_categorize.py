"""
Pass 1: Deterministic pattern-matching categorizer.

Reads an RBC chequing CSV file (columns: Date, Description, Debit, Credit,
Balance), applies regex patterns from merchant_patterns.json, and writes two
output files:

  categorized.json  – transactions that matched a pattern (with HIGH confidence)
  unmatched.json    – transactions with no pattern match (send to LLM Pass 2)

Usage
-----
    python skills/transaction-categorizer/scripts/pattern_categorize.py \\
        --input  data/mock/rbc_chequing_2025.csv \\
        --output categorized.json \\
        --unmatched unmatched.json \\
        --patterns skills/transaction-categorizer/reference/merchant_patterns.json \\
        --stats

Exit codes
----------
    0  success
    1  I/O or parse error

Output format (categorized.json)
---------------------------------
{
  "source": "rbc_chequing_2025.csv",
  "transactions": [
    {
      "date": "2025-01-05",
      "description": "LOBLAWS #1234 TORONTO ON",
      "amount": -187.43,
      "category": "GROCERIES",
      "categorization": {
        "method": "pattern",
        "confidence": "HIGH",
        "pattern_matched": "LOBLAWS"
      }
    }
  ],
  "summary": {
    "total_input": 342,
    "matched": 289,
    "unmatched": 53,
    "pre_classified_skipped": 0,
    "by_category": {"GROCERIES": 18, "DINING": 34, ...}
  }
}
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_PATTERNS_PATH = (
    Path(__file__).parent.parent / "reference" / "merchant_patterns.json"
)

# Categories that should be skipped by pattern matching (already classified)
_SKIP_CATEGORIES = {"HOUSING", "INCOME"}

# Amount sign shortcuts — pre-classify payroll before pattern matching
_INCOME_DESCRIPTION_PATTERNS = re.compile(
    r"PAYROLL\s*DEPOSIT|PAYROLL|DIRECT\s*DEPOSIT|SALARY", re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Core matching logic
# ---------------------------------------------------------------------------

def load_patterns(patterns_path: str | Path) -> dict[str, list[re.Pattern]]:
    """Load merchant_patterns.json and compile every regex."""
    path = Path(patterns_path)
    if not path.exists():
        raise FileNotFoundError(f"Patterns file not found: {path}")

    with open(path, encoding="utf-8") as fh:
        raw: dict = json.load(fh)

    compiled: dict[str, list[re.Pattern]] = {}
    for category, patterns in raw.items():
        if category.startswith("_"):          # skip _comment keys
            continue
        compiled[category] = [
            re.compile(p, re.IGNORECASE) for p in patterns
        ]
    return compiled


def match_transaction(
    description: str,
    amount: float,
    current_category: str,
    patterns: dict[str, list[re.Pattern]],
) -> tuple[str, str] | None:
    """
    Return (category, pattern_that_matched) or None if no pattern match.

    "Already classified" shortcut (returns existing category so the caller
    counts the transaction as categorized, not unmatched):
    - current_category is in _SKIP_CATEGORIES (HOUSING, INCOME) — keep as-is.
    - Amount is positive AND description looks like payroll → pre-assign INCOME.

    Returns None only when no pattern fires — caller should send to LLM.
    """
    # Already definitively classified by the parser — preserve, don't re-test
    if current_category in _SKIP_CATEGORIES:
        return (current_category, "ALREADY_CLASSIFIED")

    # Positive-amount payroll → INCOME (fast-path before full pattern scan)
    if amount > 0 and _INCOME_DESCRIPTION_PATTERNS.search(description):
        return ("INCOME", "PAYROLL_INCOME_FAST_PATH")

    # Full pattern scan — first match wins
    desc_upper = description.upper()
    for category, compiled_patterns in patterns.items():
        for pat in compiled_patterns:
            if pat.search(desc_upper):
                return (category, pat.pattern)

    return None


def categorize_by_pattern(
    transactions: list[dict],
    patterns: dict[str, list[re.Pattern]],
) -> tuple[list[dict], list[dict]]:
    """
    Categorize a list of transaction dicts using pattern matching.

    Parameters
    ----------
    transactions:
        List of transaction dicts (each must have 'description', 'amount',
        and optionally 'category').
    patterns:
        Compiled patterns from load_patterns().

    Returns
    -------
    (categorized, unmatched)
        categorized – transactions that matched a pattern; each has an added
                      'categorization' key and updated 'category'.
        unmatched   – transactions with no pattern match; 'category' is
                      unchanged (UNCATEGORIZED or prior value).
    """
    categorized: list[dict] = []
    unmatched: list[dict] = []

    for tx in transactions:
        description = tx.get("description", "") or tx.get("raw_description", "")
        amount = float(tx.get("amount", 0))
        current_cat = tx.get("category", "UNCATEGORIZED")

        result = match_transaction(description, amount, current_cat, patterns)

        if result is not None:
            category, pattern_matched = result
            updated = dict(tx)
            updated["category"] = category
            updated["categorization"] = {
                "method": "pattern",
                "confidence": "HIGH",
                "pattern_matched": pattern_matched,
            }
            categorized.append(updated)
        else:
            unmatched.append(dict(tx))

    return categorized, unmatched


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _load_csv(path: str) -> dict:
    """Read an RBC chequing CSV and return a payload dict shaped like:

        {"source": filename, "transactions": [{"date", "description",
         "amount", "category"}, ...]}

    Columns expected: Date, Description, Debit, Credit, Balance
    - Rows where Description is blank or "OPENING BALANCE" are skipped.
    - Debit  → amount = -abs(debit)   (money leaving)
    - Credit → amount = +abs(credit)  (money arriving)
    - Rows with both Debit and Credit blank are skipped (balance-only rows).
    """
    p = Path(path)
    if not p.exists():
        print(f"[ERROR] Input file not found: {path}", file=sys.stderr)
        sys.exit(1)

    try:
        df = pd.read_csv(path, encoding="utf-8-sig", dtype=str)
    except Exception as exc:
        print(f"[ERROR] Could not read CSV {path}: {exc}", file=sys.stderr)
        sys.exit(1)

    required = {"Date", "Description", "Debit", "Credit", "Balance"}
    missing = required - set(df.columns)
    if missing:
        print(
            f"[ERROR] CSV is missing expected columns: {sorted(missing)}\n"
            f"        Found columns: {list(df.columns)}",
            file=sys.stderr,
        )
        sys.exit(1)

    transactions: list[dict] = []
    for _, row in df.iterrows():
        desc = str(row["Description"]).strip() if pd.notna(row["Description"]) else ""
        if not desc or desc.upper() == "OPENING BALANCE":
            continue

        date_str = str(row["Date"]).strip() if pd.notna(row["Date"]) else ""
        if not date_str:
            continue

        debit  = _parse_amount(row.get("Debit",  ""))
        credit = _parse_amount(row.get("Credit", ""))

        if debit is not None:
            amount = -abs(debit)
        elif credit is not None:
            amount = abs(credit)
        else:
            continue   # balance-only row

        transactions.append({
            "date":        date_str,
            "description": desc,
            "amount":      amount,
            "category":    "UNCATEGORIZED",
        })

    return {"source": p.name, "transactions": transactions}


def _parse_amount(raw) -> float | None:
    """Strip currency symbols / commas; return float or None if blank."""
    if pd.isna(raw):
        return None
    cleaned = str(raw).strip().replace(",", "").replace("$", "").replace(" ", "")
    if cleaned in ("", "-"):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _write_json(data: object, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, default=str)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pattern-match categorizer (Pass 1 of transaction-categorizer skill).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python pattern_categorize.py --input parsed.json\n"
            "  python pattern_categorize.py --input parsed.json "
            "--output cat.json --unmatched um.json\n"
        ),
    )
    parser.add_argument(
        "--input", "-i", required=True, metavar="FILE",
        help="Path to an RBC chequing CSV file "
             "(columns: Date, Description, Debit, Credit, Balance).",
    )
    parser.add_argument(
        "--output", "-o", default="categorized.json", metavar="FILE",
        help="Output path for categorized transactions (default: categorized.json).",
    )
    parser.add_argument(
        "--unmatched", "-u", default="unmatched.json", metavar="FILE",
        help="Output path for unmatched transactions (default: unmatched.json).",
    )
    parser.add_argument(
        "--patterns", "-p", default=str(DEFAULT_PATTERNS_PATH), metavar="FILE",
        help=f"Path to merchant_patterns.json (default: {DEFAULT_PATTERNS_PATH}).",
    )
    parser.add_argument(
        "--stats", action="store_true",
        help="Print a summary table to stdout after processing.",
    )
    args = parser.parse_args()

    # Load
    payload = _load_csv(args.input)
    transactions = payload.get("transactions", [])
    if not transactions:
        print("[WARN] No transactions found in input file.", file=sys.stderr)

    try:
        patterns = load_patterns(args.patterns)
    except FileNotFoundError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)

    # Categorize
    categorized, unmatched = categorize_by_pattern(transactions, patterns)

    # Count pre-classified (those in SKIP_CATEGORIES that were not tested)
    pre_classified_count = sum(
        1 for tx in transactions
        if tx.get("category", "UNCATEGORIZED") in _SKIP_CATEGORIES
    )

    # Build summary
    category_counts: Counter = Counter(
        tx["category"] for tx in categorized
    )
    summary = {
        "total_input": len(transactions),
        "matched": len(categorized),
        "unmatched": len(unmatched),
        "pre_classified_skipped": pre_classified_count,
        "by_category": dict(sorted(category_counts.items())),
    }

    # Write outputs
    categorized_payload = {
        "source": payload.get("source", ""),
        "account_name": payload.get("account_name", ""),
        "institution": payload.get("institution", ""),
        "period_start": payload.get("period_start"),
        "period_end": payload.get("period_end"),
        "transactions": categorized,
        "summary": summary,
    }
    unmatched_payload = {
        "source": payload.get("source", ""),
        "transactions": unmatched,
        "note": (
            "These transactions were not matched by any pattern. "
            "Pass them to LLM classification (Pass 2)."
        ),
    }

    _write_json(categorized_payload, args.output)
    _write_json(unmatched_payload, args.unmatched)

    # Human-readable summary
    if args.stats or True:   # always print a brief summary
        total = summary["total_input"]
        matched = summary["matched"]
        unmatched_count = summary["unmatched"]
        pct = (matched / total * 100) if total else 0
        print(f"\n[pattern_categorize] Results for: {payload.get('source', args.input)}")
        print(f"  Total input        : {total}")
        print(f"  Pattern matched    : {matched}  ({pct:.1f}%)")
        print(f"  Unmatched->LLM     : {unmatched_count}  ({100-pct:.1f}%)")
        print(f"  Pre-classified skip: {pre_classified_count}")
        print(f"\n  By category (pattern matches):")
        for cat, count in sorted(category_counts.items()):
            bar = "#" * min(count, 40)
            print(f"    {cat:<16} {count:>4}  {bar}")
        print(f"\n  Wrote: {args.output}")
        print(f"  Wrote: {args.unmatched}")


if __name__ == "__main__":
    main()
