"""
CSV parsers for Canadian bank statement exports.

Supported formats
-----------------
RBC Chequing  – Date, Description, Debit, Credit, Balance
Visa (generic) – TransactionDate, PostingDate, Description, Amount, Category
Mortgage      – PaymentNumber, Date, Payment, Principal, Interest, Balance

Entry points
------------
parse_rbc_chequing(filepath)  -> TransactionSet
parse_visa_statement(filepath) -> TransactionSet
parse_mortgage(filepath)       -> TransactionSet
parse_csv(filepath)            -> TransactionSet   ← auto-detects format
"""

from __future__ import annotations

import csv
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from src.models.transaction import AccountType, Category, Transaction, TransactionSet

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_DATE_FMTS = ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%b %d, %Y")


def _parse_date(raw: str) -> date:
    """Try several common date formats; raise ValueError if none match."""
    raw = raw.strip()
    for fmt in _DATE_FMTS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognised date format: {raw!r}")


def _parse_amount(raw: str) -> Optional[float]:
    """Strip currency symbols / commas and return float, or None if blank."""
    cleaned = raw.strip().replace(",", "").replace("$", "").replace(" ", "")
    if cleaned == "" or cleaned == "-":
        return None
    return float(cleaned)


def _filename(filepath: str) -> str:
    return Path(filepath).name


def _status(n: int, filepath: str) -> None:
    """Print a UTF-8-safe status line."""
    msg = f"Parsed {n} transactions from {_filename(filepath)}\n"
    sys.stdout.buffer.write(msg.encode("utf-8", errors="replace"))


# ---------------------------------------------------------------------------
# RBC Chequing  –  Date, Description, Debit, Credit, Balance
# ---------------------------------------------------------------------------

def parse_rbc_chequing(filepath: str) -> TransactionSet:
    """Parse an RBC chequing account CSV export.

    Sign convention applied here
    ----------------------------
    Debit  (money leaving)  → negative amount
    Credit (money arriving) → positive amount

    The first row with ``Description == "OPENING BALANCE"`` is skipped because
    it carries no Debit/Credit and is not a real transaction.

    Parameters
    ----------
    filepath:
        Path to the RBC chequing CSV file.

    Returns
    -------
    TransactionSet
        All valid transactions ordered as they appear in the file.
    """
    transactions: list[Transaction] = []
    source = _filename(filepath)

    with open(filepath, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            desc_raw = row.get("Description", "").strip()

            # Skip the synthetic opening-balance sentinel row
            if not desc_raw or desc_raw.upper() == "OPENING BALANCE":
                continue

            raw_date = row.get("Date", "").strip()
            if not raw_date:
                continue

            debit  = _parse_amount(row.get("Debit",  ""))
            credit = _parse_amount(row.get("Credit", ""))

            # Exactly one of debit / credit should be populated per row
            if debit is not None:
                amount = -abs(debit)    # leaving the account
            elif credit is not None:
                amount = abs(credit)    # arriving in the account
            else:
                continue               # balance-only row, nothing to record

            transactions.append(Transaction(
                date=_parse_date(raw_date),
                description=desc_raw,
                amount=amount,
                category=Category.UNCATEGORIZED,
                account_type=AccountType.CHEQUING,
                source_file=source,
                raw_description=desc_raw,
            ))

    _status(len(transactions), filepath)
    return TransactionSet(
        transactions=transactions,
        source=source,
        account_name="RBC Chequing",
        institution="Royal Bank of Canada",
    )


# ---------------------------------------------------------------------------
# Visa credit card  –  TransactionDate, PostingDate, Description, Amount, Category
# ---------------------------------------------------------------------------

# Map CSV Category strings → our Category enum (case-insensitive prefix match)
_VISA_CATEGORY_MAP: dict[str, Category] = {
    "food":          Category.DINING,
    "dining":        Category.DINING,
    "restaurant":    Category.DINING,
    "grocery":       Category.GROCERIES,
    "groceries":     Category.GROCERIES,
    "travel":        Category.TRAVEL,
    "gas":           Category.TRANSPORTATION,
    "transport":     Category.TRANSPORTATION,
    "shopping":      Category.SHOPPING,
    "health":        Category.SHOPPING,
    "phone":         Category.UTILITIES,
    "subscription":  Category.SUBSCRIPTIONS,
    "entertainment": Category.SUBSCRIPTIONS,
    "payment":       Category.TRANSFER,
    "transfer":      Category.TRANSFER,
}


def _map_visa_category(raw: str) -> Category:
    """Convert a Visa CSV category string to a ``Category`` enum value."""
    lower = raw.strip().lower()
    for prefix, cat in _VISA_CATEGORY_MAP.items():
        if lower.startswith(prefix):
            return cat
    return Category.UNCATEGORIZED


def parse_visa_statement(filepath: str) -> TransactionSet:
    """Parse a Visa credit card statement CSV export.

    The ``Amount`` column uses the convention already present in the file:
    positive → charge to the card (expense), negative → payment/credit.
    We **invert the sign** so positive = money received (consistent with the
    rest of the codebase).

    Parameters
    ----------
    filepath:
        Path to the Visa CSV file.

    Returns
    -------
    TransactionSet
        All valid transactions ordered as they appear in the file.
    """
    transactions: list[Transaction] = []
    source = _filename(filepath)

    with open(filepath, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            desc_raw = row.get("Description", "").strip()
            raw_date = row.get("TransactionDate", "").strip()
            if not raw_date or not desc_raw:
                continue

            amount_raw = _parse_amount(row.get("Amount", ""))
            if amount_raw is None:
                continue

            # Visa CSVs: positive = charge (outflow) → flip to negative
            amount = -amount_raw

            category = _map_visa_category(row.get("Category", ""))

            transactions.append(Transaction(
                date=_parse_date(raw_date),
                description=desc_raw,
                amount=amount,
                category=category,
                account_type=AccountType.CREDIT,
                source_file=source,
                raw_description=desc_raw,
            ))

    _status(len(transactions), filepath)
    return TransactionSet(
        transactions=transactions,
        source=source,
        account_name="RBC Visa Infinite",
        institution="Royal Bank of Canada",
    )


# ---------------------------------------------------------------------------
# Mortgage amortisation  –  PaymentNumber, Date, Payment, Principal, Interest, Balance
# ---------------------------------------------------------------------------

def parse_mortgage(filepath: str) -> TransactionSet:
    """Parse a mortgage amortisation schedule CSV.

    Each row becomes a single transaction where ``amount = -Payment``.
    Row 0 (opening balance, Payment == 0) is skipped.

    Parameters
    ----------
    filepath:
        Path to the mortgage amortisation CSV file.

    Returns
    -------
    TransactionSet
        One transaction per scheduled payment.
    """
    transactions: list[Transaction] = []
    source = _filename(filepath)

    with open(filepath, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            raw_date = row.get("Date", "").strip()
            if not raw_date:
                continue

            payment = _parse_amount(row.get("Payment", ""))
            if payment is None or payment == 0.0:
                continue   # skip the opening-balance row (PaymentNumber 0)

            principal = _parse_amount(row.get("Principal", "")) or 0.0
            interest  = _parse_amount(row.get("Interest",  "")) or 0.0
            pay_num   = row.get("PaymentNumber", "").strip()
            desc = f"Mortgage payment #{pay_num} (principal ${principal:.2f}, interest ${interest:.2f})"

            transactions.append(Transaction(
                date=_parse_date(raw_date),
                description=desc,
                amount=-abs(payment),
                category=Category.HOUSING,
                account_type=AccountType.MORTGAGE,
                source_file=source,
                raw_description=f"MORTGAGE PAYMENT {pay_num}",
            ))

    _status(len(transactions), filepath)
    return TransactionSet(
        transactions=transactions,
        source=source,
        account_name="RBC Homeline Mortgage",
        institution="Royal Bank of Canada",
    )


# ---------------------------------------------------------------------------
# Auto-detection
# ---------------------------------------------------------------------------

# Maps a frozenset of expected column names → the corresponding parser
_FORMAT_SIGNATURES: list[tuple[frozenset[str], str]] = [
    (frozenset({"Date", "Description", "Debit", "Credit", "Balance"}),   "rbc_chequing"),
    (frozenset({"TransactionDate", "PostingDate", "Description", "Amount"}), "visa"),
    (frozenset({"PaymentNumber", "Date", "Payment", "Principal", "Interest", "Balance"}), "mortgage"),
]


def _detect_format(filepath: str) -> str:
    """Read the CSV header row and return a format key.

    Returns
    -------
    str
        One of ``"rbc_chequing"``, ``"visa"``, ``"mortgage"``.

    Raises
    ------
    ValueError
        If the header does not match any known format.
    """
    with open(filepath, newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        try:
            header_cols = frozenset(col.strip() for col in next(reader))
        except StopIteration:
            raise ValueError(f"Empty file: {filepath}")

    for required_cols, fmt_key in _FORMAT_SIGNATURES:
        if required_cols.issubset(header_cols):
            return fmt_key

    raise ValueError(
        f"Cannot detect CSV format for {_filename(filepath)!r}. "
        f"Columns found: {sorted(header_cols)}"
    )


def parse_csv(filepath: str) -> TransactionSet:
    """Auto-detect CSV format and parse into a TransactionSet.

    Reads only the header row to determine format, then delegates to the
    appropriate parser.

    Parameters
    ----------
    filepath:
        Path to any supported CSV file.

    Returns
    -------
    TransactionSet
    """
    fmt = _detect_format(filepath)
    parsers = {
        "rbc_chequing": parse_rbc_chequing,
        "visa":         parse_visa_statement,
        "mortgage":     parse_mortgage,
    }
    return parsers[fmt](filepath)


# ---------------------------------------------------------------------------
# __main__ – parse all mock CSVs and print summary stats
# ---------------------------------------------------------------------------

def _print_summary(ts: TransactionSet) -> None:
    """Print a compact summary table for a TransactionSet."""
    lines = [
        f"  Account  : {ts.account_name}  ({ts.institution})",
        f"  Period   : {ts.period_start} → {ts.period_end}",
        f"  Count    : {ts.count} transactions",
        f"  Income   : +${ts.total_income:>10,.2f}",
        f"  Expenses :  ${ts.total_expenses:>10,.2f}",
        f"  Net      :  ${ts.net:>10,.2f}",
    ]
    sys.stdout.buffer.write(("\n".join(lines) + "\n\n").encode("utf-8", errors="replace"))


if __name__ == "__main__":
    root = Path(__file__).parent.parent.parent  # project root

    # If a specific file is passed on the command line, parse just that one
    if len(sys.argv) > 1:
        target = Path(sys.argv[1])
        if not target.is_absolute():
            target = root / target
        ts = parse_csv(str(target))
        _print_summary(ts)
        sys.exit(0)

    # Otherwise parse all mock CSVs
    mock_dir = root / "personal-finance-agent" / "data" / "mock"
    csv_files = sorted(mock_dir.glob("*.csv"))

    if not csv_files:
        sys.stdout.buffer.write(
            f"No CSV files found in {mock_dir}\n".encode("utf-8", errors="replace")
        )
        sys.exit(1)

    header = "\n=== Personal Finance Agent – Mock Data Summary ===\n\n"
    sys.stdout.buffer.write(header.encode("utf-8", errors="replace"))

    all_sets: list[TransactionSet] = []
    for csv_path in csv_files:
        try:
            ts = parse_csv(str(csv_path))
            _print_summary(ts)
            all_sets.append(ts)
        except Exception as exc:
            msg = f"  [SKIP] {csv_path.name}: {exc}\n\n"
            sys.stdout.buffer.write(msg.encode("utf-8", errors="replace"))

    # Aggregate stats across all parsed sets
    total_tx   = sum(ts.count           for ts in all_sets)
    total_inc  = sum(ts.total_income    for ts in all_sets)
    total_exp  = sum(ts.total_expenses  for ts in all_sets)

    aggregate = (
        f"--- Aggregate across {len(all_sets)} statement(s) ---\n"
        f"  Total transactions : {total_tx}\n"
        f"  Total income       : +${total_inc:>10,.2f}\n"
        f"  Total expenses     :  ${total_exp:>10,.2f}\n"
        f"  Net                :  ${total_inc + total_exp:>10,.2f}\n"
    )
    sys.stdout.buffer.write(aggregate.encode("utf-8", errors="replace"))
