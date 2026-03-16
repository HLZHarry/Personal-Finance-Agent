# Supported Banks and Detection Rules

This file is the authoritative list of file formats this skill can parse.
The auto-detector in `src.parsers.csv_parser._detect_format()` uses these
same column signatures.

---

## Detection algorithm

1. Open the file with `encoding="utf-8-sig"` (handles Excel BOM).
2. Read the first (header) row only.
3. Strip whitespace from each column name and build a `frozenset`.
4. Match against the signatures below using `required_columns.issubset(header_cols)`.
5. First match wins.  If nothing matches, raise `ValueError` with the actual headers.

---

## Supported formats

### 1. RBC Chequing

| Field | Value |
|-------|-------|
| **Format key** | `rbc_chequing` |
| **Parser function** | `parse_rbc_chequing(filepath)` |
| **Account type** | `CHEQUING` |
| **Institution** | Royal Bank of Canada |

**Required columns (detection signature):**
```
Date, Description, Debit, Credit, Balance
```

**Filename patterns** (hints only — detection uses headers, not filename):
- `rbc_chequing_*.csv`
- `*_account_activity_*.csv`

**Sign rules:**
- `Debit` column populated → `amount = -abs(debit)` (money leaving)
- `Credit` column populated → `amount = +abs(credit)` (money arriving)
- Both blank → opening-balance sentinel row; **skip**

---

### 2. Visa / Mastercard Credit Card

| Field | Value |
|-------|-------|
| **Format key** | `visa` |
| **Parser function** | `parse_visa_statement(filepath)` |
| **Account type** | `CREDIT` |
| **Institution** | Royal Bank of Canada (RBC Avion / RBC ION) |

**Required columns (detection signature):**
```
TransactionDate, PostingDate, Description, Amount
```

The optional `Category` column, if present, is mapped to project categories
(see `bank_formats.md` for the full mapping table).

**Filename patterns:**
- `visa_statement_*.csv`
- `*_visa_*.csv`

**Sign rules:**
- Positive `Amount` in CSV = charge to the card (outflow) → **inverted to negative** during parse.
- Negative `Amount` in CSV = payment or credit → **inverted to positive**.

---

### 3. Mortgage Amortization Schedule

| Field | Value |
|-------|-------|
| **Format key** | `mortgage` |
| **Parser function** | `parse_mortgage(filepath)` |
| **Account type** | `MORTGAGE` |
| **Institution** | Royal Bank of Canada (RBC Homeline) |

**Required columns (detection signature):**
```
PaymentNumber, Date, Payment, Principal, Interest, Balance
```

**Filename patterns:**
- `mortgage_amortization*.csv`
- `*_amortization_*.csv`

**Sign rules:**
- Each row becomes one transaction with `amount = -abs(Payment)`.
- Row with `PaymentNumber == 0` / `Payment == 0.0` is the opening-balance
  sentinel; **skip**.

---

## Unsupported formats (planned)

| Institution | Format | Status |
|-------------|--------|--------|
| TD Bank | CSV chequing / savings | Not yet supported |
| BMO | CSV chequing / credit | Not yet supported |
| Scotiabank | CSV | Not yet supported |
| Any institution | PDF statement | Parser not yet implemented |

To add a new format: implement a parser function in `src/parsers/csv_parser.py`,
add its detection signature to `_FORMAT_SIGNATURES`, and add a row to this table.
