---
name: statement-parser
version: "2.0"
description: >
  Parse Canadian bank statement exports (RBC chequing CSV, Visa/Mastercard CSV,
  mortgage amortization CSV, or Visa PDF) into the project's standardized
  TransactionSet JSON format.  Handles sign normalization, category mapping,
  and opening-balance row removal automatically.  Call src.parsers.csv_parser
  parse_csv() for all CSV work; PDF support is not yet implemented.
triggers:
  - user uploads or references a bank statement file
  - user says "import", "load", "parse", or "read" with a filename
  - user asks what transactions are in a file
---

# Statement Parser

## When to use

Activate this skill when **any** of the following are true:

- The user provides a file path ending in `.csv` or `.pdf` and asks to analyse it.
- The user says phrases like *"parse my statement"*, *"load this CSV"*,
  *"import my transactions"*, *"what's in this file?"*, *"read my bank export"*.
- A pipeline step needs raw transactions before categorisation or analysis.
- The user drags a file into the conversation and asks about spending.

## When NOT to use

- The file is already parsed (a JSON array of transactions is in context) —
  skip straight to the `transaction-categorizer` or `spend-analyzer` skill.
- The user asks about *future* projections — that is the `cashflow-forecaster` skill.
- The file format is not a supported bank export (e.g., a receipt image, a PDF
  invoice, or a spreadsheet with custom columns).  Tell the user which formats
  are supported and ask them to export in one of those formats instead.
- The user has not yet provided a file — ask for one before invoking this skill.

---

## Step-by-step instructions

### Step 1 — Identify the file type

1. Check the file extension:
   - `.csv` → proceed to Step 2.
   - `.pdf` → PDF parsing is **not yet implemented**.  Inform the user and stop.
   - Anything else → unsupported.  Explain and stop.

### Step 2 — Detect the bank format

Call `src.parsers.csv_parser._detect_format(filepath)` or read the first line
and compare the column set against the detection rules in
[`reference/supported_banks.md`](reference/supported_banks.md).

Detected formats: `rbc_chequing` | `visa` | `mortgage`

If no format matches, raise a `ValueError` and report the unrecognised column
headers to the user.

### Step 3 — Parse the file

Call the appropriate entry-point function:

```python
from src.parsers.csv_parser import parse_csv   # auto-detects format

transaction_set = parse_csv(filepath)
# Returns a TransactionSet Pydantic model
```

`parse_csv()` is idempotent — safe to call multiple times on the same file.

Sign convention applied by the parsers (do **not** re-apply):
- RBC chequing: Debit → negative, Credit → positive.
- Visa: CSV Amount sign is **inverted** (positive charge → stored as negative).
- Mortgage: Payment → negative (money leaving).

See [`reference/bank_formats.md`](reference/bank_formats.md) for column
layouts, example rows, and known quirks.

### Step 4 — Validate the result

Run the validation script to confirm the parse is clean before handing off
to downstream skills:

```bash
python skills/statement-parser/scripts/validate_parse.py \
    --input <path-to-exported-json>
```

Or programmatically:

```python
import json, subprocess, sys
payload = transaction_set.model_dump(mode="json")
with open("_tmp_parse.json", "w") as f:
    json.dump(payload, f, default=str)
result = subprocess.run(
    [sys.executable,
     "skills/statement-parser/scripts/validate_parse.py",
     "--input", "_tmp_parse.json"],
    capture_output=True, text=True,
)
validation = json.loads(result.stdout)
if not validation["valid"]:
    raise RuntimeError(f"Parse validation failed: {validation['errors']}")
```

A passing validation returns `{"valid": true, "errors": [], ...}`.

### Step 5 — Emit the output

Serialise the `TransactionSet` to the standard output format (see below) and
pass it to the next skill or store it via `src.embeddings.store`.

---

## Error handling

| Situation | Action |
|-----------|--------|
| File not found | Tell the user the exact path that was not found; ask them to confirm the location. |
| Unknown CSV format | Show the detected column headers; point the user to `reference/supported_banks.md` for supported formats. |
| Date parse failure | Log the offending row; skip that row; include a warning in the validation output. |
| All-blank Debit **and** Credit (RBC) | Skip the row silently — it is an opening-balance sentinel. |
| Zero-amount transaction after parsing | Flag in validation `errors`; do not ingest zero-amount rows. |
| PDF file provided | Respond: *"PDF parsing is not yet implemented.  Please export as CSV from your online banking portal."* |
| Encoding issues | Re-open with `encoding="utf-8-sig"` (handles BOM from Excel exports). |

---

## Output format

```jsonc
{
  "source": "rbc_chequing_2025.csv",       // filename used as stable ID prefix
  "account_name": "RBC Chequing",
  "institution": "Royal Bank of Canada",
  "period_start": "2025-01-01",             // derived from min transaction date
  "period_end":   "2025-12-31",             // derived from max transaction date
  "transactions": [
    {
      "date": "2025-01-05",                 // ISO-8601
      "description": "LOBLAWS #1234 TORONTO ON",
      "amount": -187.43,                    // negative = expense, positive = income
      "category": "UNCATEGORIZED",          // enum; categoriser skill fills this in
      "account_type": "CHEQUING",           // CHEQUING | CREDIT | MORTGAGE
      "source_file": "rbc_chequing_2025.csv",
      "raw_description": "LOBLAWS #1234 TORONTO ON"
    }
  ]
}
```

Category values after parsing: `UNCATEGORIZED` (RBC/mortgage) or a mapped
value for Visa (e.g., `GROCERIES`, `DINING`, `TRANSPORTATION`).  Pass the
result to the `transaction-categorizer` skill to fill in remaining categories.

---

## Reference files

| File | Purpose |
|------|---------|
| [`reference/supported_banks.md`](reference/supported_banks.md) | Detection rules — which column sets map to which parser |
| [`reference/bank_formats.md`](reference/bank_formats.md) | Full column schemas, example rows, and known quirks per format |
| [`scripts/validate_parse.py`](scripts/validate_parse.py) | Deterministic post-parse validator; outputs `{valid, errors, warnings, stats}` JSON |
