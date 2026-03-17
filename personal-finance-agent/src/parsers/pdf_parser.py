"""
PDF parser for credit card statements.

Two parsing modes
-----------------
parse_pdf_with_llm(filepath, llm_provider="ollama")
    Extracts raw text with pypdf, then asks an LLM to identify transactions.
    Falls back to regex mode automatically if the LLM call fails or returns
    unparseable output.

parse_pdf_regex(filepath)
    Pure regex approach for simple tabular PDFs.  Works without Ollama.

Entry point
-----------
parse_pdf(filepath, use_llm=True)  ← auto-selects mode
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from src.models.transaction import AccountType, Category, Transaction, TransactionSet

# ---------------------------------------------------------------------------
# Internal helpers (mirrors csv_parser style)
# ---------------------------------------------------------------------------

_DATE_FMTS = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%d/%m/%Y",
    "%b %d, %Y",
    "%b %d %Y",
    "%B %d, %Y",
    "%B %d %Y",
)


def _parse_date(raw: str) -> date:
    raw = raw.strip()
    for fmt in _DATE_FMTS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognised date format: {raw!r}")


def _parse_amount(raw: str) -> Optional[float]:
    cleaned = raw.strip().replace(",", "").replace("$", "").replace(" ", "")
    if cleaned in ("", "-"):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _filename(filepath: str) -> str:
    return Path(filepath).name


def _print(msg: str) -> None:
    sys.stdout.buffer.write((msg + "\n").encode("utf-8", errors="replace"))


# ---------------------------------------------------------------------------
# Step 1 – extract raw text from PDF pages via pypdf
# ---------------------------------------------------------------------------

def _extract_pdf_text(filepath: str) -> str:
    """Return all pages concatenated as a single string."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ImportError(
            "pypdf is required for PDF parsing.  Install with: pip install pypdf"
        ) from exc

    reader = PdfReader(filepath)
    pages: list[str] = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        pages.append(f"--- Page {i + 1} ---\n{text}")
    return "\n\n".join(pages)


# ---------------------------------------------------------------------------
# Step 2a – LLM parsing (Ollama via langchain-ollama)
# ---------------------------------------------------------------------------

_LLM_PROMPT = """\
You are a financial data extractor.  Below is raw text extracted from a credit
card statement PDF.  Your job is to identify every individual transaction and
return them as a JSON array.

Rules:
- Only include actual purchase/payment transactions, not page headers, account
  summaries, opening/closing balances, or promotional text.
- Each object in the array must have exactly three keys:
    "date"        – the transaction date as a string (keep the original format)
    "description" – the merchant or payee name, cleaned of extra whitespace
    "amount"      – a number; use NEGATIVE for charges/expenses and POSITIVE
                    for payments/credits/refunds
- Do not include a currency symbol in the amount field.
- If you cannot find any transactions, return an empty array: []
- Return ONLY the JSON array with no markdown fences, no explanation.

Statement text:
{text}
"""


def _call_ollama(text: str, model: str = "llama3.2") -> list[dict]:
    """Send statement text to Ollama and return a list of raw transaction dicts."""
    try:
        from langchain_ollama import ChatOllama
    except ImportError as exc:
        raise ImportError(
            "langchain-ollama is required.  Install with: pip install langchain-ollama"
        ) from exc

    from langchain_core.messages import HumanMessage

    llm = ChatOllama(model=model, temperature=0)
    prompt = _LLM_PROMPT.format(text=text)

    _print(f"[LLM] Sending {len(text)} chars to Ollama model '{model}' …")
    response = llm.invoke([HumanMessage(content=prompt)])
    raw_content: str = response.content.strip()

    _print(f"[LLM] Received {len(raw_content)} chars from model.")

    # Strip accidental markdown code fences if the model added them
    if raw_content.startswith("```"):
        raw_content = re.sub(r"^```[a-z]*\n?", "", raw_content)
        raw_content = re.sub(r"\n?```$", "", raw_content.strip())

    return json.loads(raw_content)


def _validate_and_build(
    raw_items: list[dict],
    source: str,
) -> list[Transaction]:
    """Convert raw LLM dicts to validated Transaction objects, skipping bad rows."""
    transactions: list[Transaction] = []
    for item in raw_items:
        try:
            raw_date = str(item.get("date", "")).strip()
            raw_desc = str(item.get("description", "")).strip()
            raw_amt  = item.get("amount")

            if not raw_date or not raw_desc or raw_amt is None:
                continue

            tx_date  = _parse_date(raw_date)
            amount   = float(raw_amt)

            if amount == 0.0:
                continue  # Transaction model rejects zero amounts

            transactions.append(Transaction(
                date=tx_date,
                description=raw_desc,
                amount=round(amount, 2),
                category=Category.UNCATEGORIZED,
                account_type=AccountType.CREDIT,
                source_file=source,
                raw_description=raw_desc,
            ))
        except Exception as exc:
            _print(f"  [SKIP] Could not parse LLM row {item!r}: {exc}")

    return transactions


# ---------------------------------------------------------------------------
# Step 2b – Regex fallback
# ---------------------------------------------------------------------------

# Short date as it appears in many PDF statements: "Feb 22", "Mar 3"
_SHORT_DATE_RE = re.compile(
    r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{1,2}$",
    re.IGNORECASE,
)

# Full date on a single line: 2026-03-15, 03/15/2026, Mar 15, 2026
_FULL_DATE_RE = re.compile(
    r"^(?:"
    r"\d{4}-\d{2}-\d{2}"
    r"|[A-Za-z]{3}\.?\s+\d{1,2},?\s+\d{4}"
    r"|\d{1,2}/\d{1,2}/\d{2,4}"
    r")$",
    re.IGNORECASE,
)

# Amount on its own line: $42.30  or  -$1,234.56  or  1234.56
_AMOUNT_LINE_RE = re.compile(r"^\s*-?\$?[\d,]+\.\d{2}\s*$")

# Lines to always skip
_SKIP_RE = re.compile(
    r"(opening balance|closing balance|credit limit|minimum payment"
    r"|statement date|payment due|total new|balance forward|previous balance"
    r"|interest rate|annual rate|daily rate|how to make|customer service"
    r"|page \d|account ending|royal trust|synthetic mock)",
    re.IGNORECASE,
)

# Months for short-date year inference
_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _infer_year(text: str) -> int:
    """Try to pull a 4-digit year from the statement text (e.g. 'March 20, 2026')."""
    m = re.search(r"\b(20\d{2})\b", text)
    return int(m.group(1)) if m else datetime.now().year


def _expand_short_date(raw: str, year: int) -> date:
    """Turn 'Feb 22' into a date object using the inferred statement year."""
    parts = raw.strip().split()
    month = _MONTH_MAP[parts[0][:3].lower()]
    day = int(parts[1])
    return date(year, month, day)


def _parse_text_with_regex(text: str, source: str) -> list[Transaction]:
    """Extract transactions from raw PDF text.

    Handles two layouts:

    1. **Multi-line** (one token per line) – the format used by many PDF
       credit card statements after text extraction::

           Feb 22
           Feb 23
           UBER EATS TORONTO ON
            $42.30

    2. **Single-line** – each transaction on one row::

           03/15/2026   Tim Hortons     -$4.75
    """
    transactions: list[Transaction] = []
    year = _infer_year(text)
    lines = [ln.strip() for ln in text.splitlines()]

    # ── Pass 1: multi-line state machine ───────────────────────────────────
    # States: IDLE -> TRANS_DATE -> POST_DATE -> DESC -> AMOUNT
    state = "IDLE"
    trans_date_raw = post_date_raw = desc_raw = ""

    i = 0
    while i < len(lines):
        line = lines[i]

        if not line or _SKIP_RE.search(line):
            i += 1
            continue

        if state == "IDLE":
            if _SHORT_DATE_RE.match(line) or _FULL_DATE_RE.match(line):
                trans_date_raw = line
                state = "TRANS_DATE"

        elif state == "TRANS_DATE":
            # Expect the posting date next
            if _SHORT_DATE_RE.match(line) or _FULL_DATE_RE.match(line):
                post_date_raw = line
                state = "POST_DATE"
            else:
                # No posting date – treat this line as the description instead
                desc_raw = line
                state = "DESC"
                i += 1
                continue  # don't advance again below

        elif state == "POST_DATE":
            if _AMOUNT_LINE_RE.match(line):
                # No description line – skip this oddity
                state = "IDLE"
            elif _SHORT_DATE_RE.match(line) or _FULL_DATE_RE.match(line):
                # Back-to-back date lines means the previous was actually
                # a section header; restart
                trans_date_raw = line
                state = "TRANS_DATE"
            else:
                desc_raw = line
                state = "DESC"

        elif state == "DESC":
            if _AMOUNT_LINE_RE.match(line):
                # Build the transaction
                try:
                    amount_val = _parse_amount(line)
                    if amount_val is None or amount_val == 0.0:
                        raise ValueError(f"bad amount: {line!r}")

                    # Credit card convention: positive amounts on the statement
                    # are charges (expenses) → flip to negative
                    amount = -abs(amount_val)

                    if _SHORT_DATE_RE.match(trans_date_raw):
                        tx_date = _expand_short_date(trans_date_raw, year)
                    else:
                        tx_date = _parse_date(trans_date_raw)

                    transactions.append(Transaction(
                        date=tx_date,
                        description=desc_raw,
                        amount=amount,
                        category=Category.UNCATEGORIZED,
                        account_type=AccountType.CREDIT,
                        source_file=source,
                        raw_description=desc_raw,
                    ))
                except Exception as exc:
                    _print(f"  [SKIP] multi-line build error: {exc}")
                state = "IDLE"
            elif _SHORT_DATE_RE.match(line) or _FULL_DATE_RE.match(line):
                # Missed the amount; start fresh from this date
                trans_date_raw = line
                state = "TRANS_DATE"
            else:
                # Description continued on next line – append it
                desc_raw += " " + line

        i += 1

    if transactions:
        return transactions

    # ── Pass 2: single-line fallback ────────────────────────────────────────
    _ROW_RE = re.compile(
        r"^(?P<date>"
        r"\d{4}-\d{2}-\d{2}"
        r"|[A-Za-z]{3}\.?\s+\d{1,2},?\s+\d{4}"
        r"|\d{1,2}/\d{1,2}/\d{2,4}"
        r")\s+(?P<desc>.+?)\s+(?P<amount>-?\$?[\d,]+\.\d{2})\s*$",
        re.IGNORECASE,
    )

    for line in lines:
        if not line or _SKIP_RE.search(line):
            continue
        m = _ROW_RE.match(line)
        if not m:
            continue
        try:
            amount = _parse_amount(m.group("amount"))
            if amount is None or amount == 0.0:
                continue
            transactions.append(Transaction(
                date=_parse_date(m.group("date")),
                description=m.group("desc").strip(),
                amount=amount,
                category=Category.UNCATEGORIZED,
                account_type=AccountType.CREDIT,
                source_file=source,
                raw_description=m.group("desc").strip(),
            ))
        except Exception as exc:
            _print(f"  [SKIP] single-line row error: {exc}")

    return transactions


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_pdf_with_llm(
    filepath: str,
    llm_provider: str = "ollama",
    model: str = "llama3.2",
) -> TransactionSet:
    """Parse a PDF credit card statement using an LLM.

    1. Extracts raw text from every page with pypdf.
    2. Sends the text to the LLM with a structured extraction prompt.
    3. Parses the JSON response into Transaction objects.
    4. Falls back to regex if the LLM call fails or produces no results.

    Parameters
    ----------
    filepath:
        Path to the PDF file.
    llm_provider:
        Currently only ``"ollama"`` is supported.
    model:
        Ollama model name (default ``"llama3.2"``).

    Returns
    -------
    TransactionSet
    """
    source = _filename(filepath)
    _print(f"\n[PDF] Extracting text from {source} …")
    raw_text = _extract_pdf_text(filepath)
    _print(f"[PDF] Extracted {len(raw_text)} characters across all pages.")

    transactions: list[Transaction] = []
    used_llm = False

    if llm_provider == "ollama":
        try:
            raw_items = _call_ollama(raw_text, model=model)
            _print(f"[LLM] Model returned {len(raw_items)} candidate rows.")
            transactions = _validate_and_build(raw_items, source)
            used_llm = True
        except Exception as exc:
            _print(f"[LLM] Failed ({exc}). Falling back to regex parser.")

    if not transactions:
        if used_llm:
            _print("[LLM] No valid transactions from LLM. Trying regex fallback.")
        transactions = _parse_text_with_regex(raw_text, source)

    _print(f"[PDF] Parsed {len(transactions)} transactions from {source}")
    return TransactionSet(
        transactions=transactions,
        source=source,
        account_name="RBC Visa Infinite",
        institution="Royal Bank of Canada",
    )


def parse_pdf_regex(filepath: str) -> TransactionSet:
    """Parse a PDF credit card statement using regex only (no LLM required).

    Parameters
    ----------
    filepath:
        Path to the PDF file.

    Returns
    -------
    TransactionSet
    """
    source = _filename(filepath)
    _print(f"\n[PDF] Extracting text from {source} …")
    raw_text = _extract_pdf_text(filepath)
    _print(f"[PDF] Extracted {len(raw_text)} characters.")

    transactions = _parse_text_with_regex(raw_text, source)
    _print(f"[PDF] Parsed {len(transactions)} transactions from {source}")
    return TransactionSet(
        transactions=transactions,
        source=source,
        account_name="RBC Visa Infinite",
        institution="Royal Bank of Canada",
    )


def parse_pdf(filepath: str, use_llm: bool = True) -> TransactionSet:
    """Auto-select LLM or regex mode and parse a PDF statement.

    Parameters
    ----------
    filepath:
        Path to the PDF file.
    use_llm:
        If ``True`` (default), attempt LLM parsing first.

    Returns
    -------
    TransactionSet
    """
    if use_llm:
        return parse_pdf_with_llm(filepath)
    return parse_pdf_regex(filepath)


# ---------------------------------------------------------------------------
# __main__ – test with a single PDF file
# ---------------------------------------------------------------------------

def _print_summary(ts: TransactionSet) -> None:
    lines = [
        "",
        "=== Parsed TransactionSet ===",
        f"  Account  : {ts.account_name}  ({ts.institution})",
        f"  Source   : {ts.source}",
        f"  Period   : {ts.period_start} -> {ts.period_end}",
        f"  Count    : {ts.count} transactions",
        f"  Income   : +${ts.total_income:>10,.2f}",
        f"  Expenses :  ${ts.total_expenses:>10,.2f}",
        f"  Net      :  ${ts.net:>10,.2f}",
        "",
        "--- Transactions ---",
    ]
    for t in ts.transactions:
        sign = "+" if t.amount > 0 else ""
        lines.append(f"  {t.date}  {t.description:<45s}  {sign}{t.amount:>10.2f}")
    _print("\n".join(lines))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        _print("Usage: python -m src.parsers.pdf_parser <path/to/statement.pdf>")
        _print("       python -m src.parsers.pdf_parser <path> --regex   (skip LLM)")
        sys.exit(1)

    pdf_path = sys.argv[1]
    use_llm_flag = "--regex" not in sys.argv

    # ── 1. Show raw extracted text ──────────────────────────────────────────
    _print("\n" + "=" * 60)
    _print("RAW EXTRACTED TEXT")
    _print("=" * 60)
    raw = _extract_pdf_text(pdf_path)
    _print(raw)

    # ── 2. Parse and show structured transactions ───────────────────────────
    _print("\n" + "=" * 60)
    _print("PARSED TRANSACTIONS" + (" (LLM mode)" if use_llm_flag else " (regex mode)"))
    _print("=" * 60)

    ts = parse_pdf(pdf_path, use_llm=use_llm_flag)
    _print_summary(ts)
