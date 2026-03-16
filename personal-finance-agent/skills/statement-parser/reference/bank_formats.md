# Bank Format Reference

Detailed column schemas, example rows, and known quirks for every supported
CSV format.  This is the reference used by the parser; changes here should be
reflected in `src/parsers/csv_parser.py`.

---

## Format 1 — RBC Chequing

### Column schema

| Column | Type | Notes |
|--------|------|-------|
| `Date` | `YYYY-MM-DD` | Always ISO-8601 in RBC exports |
| `Description` | string | Raw merchant / payee name in UPPER CASE |
| `Debit` | decimal or blank | Amount leaving account; blank when Credit is set |
| `Credit` | decimal or blank | Amount arriving; blank when Debit is set |
| `Balance` | decimal | Running account balance after this row |

### Example rows

```csv
Date,Description,Debit,Credit,Balance
2025-01-01,OPENING BALANCE,,,14235.67
2025-01-01,MORTGAGE PAYMENT RBC HOMELINE,3057.61,,11178.06
2025-01-03,PAYROLL DEPOSIT ACCENTURE INC,,6500.00,17678.06
2025-01-05,LOBLAWS #1234 TORONTO ON,187.43,,17490.63
```

### Sign normalisation applied by parser

```
Debit  column non-blank  →  amount = -abs(debit)
Credit column non-blank  →  amount = +abs(credit)
Both blank               →  skip row
```

### Known quirks

| Quirk | Detail |
|-------|--------|
| **Opening-balance row** | First data row always has `Description == "OPENING BALANCE"` with blank Debit and Credit. The parser skips it explicitly before the blank-check so it never appears in output. |
| **BOM prefix** | Exported via online banking, the file may begin with a UTF-8 BOM (`\xef\xbb\xbf`). Open with `encoding="utf-8-sig"`. |
| **No category column** | RBC chequing exports carry no category data. All transactions are parsed as `UNCATEGORIZED`; pass to `transaction-categorizer` skill. |
| **Empty Balance cell** | Occasionally the last row has a blank Balance (known RBC bug). The parser ignores Balance entirely — it is not stored. |
| **Decimal format** | Always uses `.` as decimal separator and no thousands separator. No `$` prefix. |
| **E-transfer descriptions** | `E-TRANSFER SENT <NAME>` / `E-TRANSFER RECEIVED <NAME>` — names are real PII. Strip before sharing outputs. |

---

## Format 2 — Visa / Mastercard Credit Card

### Column schema

| Column | Type | Notes |
|--------|------|-------|
| `TransactionDate` | `YYYY-MM-DD` | Date the purchase occurred |
| `PostingDate` | `YYYY-MM-DD` | Date it cleared; usually +1 day. Not stored. |
| `Description` | string | Merchant name; often includes city/province code |
| `Amount` | decimal | **Positive = charge (outflow); negative = payment/credit** |
| `Category` | string | Optional; mapped to project Category enum (see table below) |

### Example rows

```csv
TransactionDate,PostingDate,Description,Amount,Category
2026-01-05,2026-01-06,SHELL STATION 1204 TORONTO,82.34,Gas & Auto
2026-01-15,2026-01-16,WHOLE FOODS MARKET TORONTO,156.78,Groceries
2026-01-28,2026-01-29,THE KEG STEAKHOUSE TORONTO,198.45,Food & Dining
2026-02-18,2026-02-19,LOBLAWS PC MASTERCARD,198.45,Groceries
```

### Sign normalisation applied by parser

```
amount = -Amount   # positive charge → stored as negative (consistent with RBC)
```

### Visa Category → Project Category mapping

| Visa CSV `Category` prefix | Project `Category` enum |
|----------------------------|------------------------|
| `Food`, `Dining`, `Restaurant` | `DINING` |
| `Grocery`, `Groceries` | `GROCERIES` |
| `Travel` | `TRAVEL` |
| `Gas`, `Transport` | `TRANSPORTATION` |
| `Shopping`, `Health` | `SHOPPING` |
| `Phone` | `UTILITIES` |
| `Subscription`, `Entertainment` | `SUBSCRIPTIONS` |
| `Payment`, `Transfer` | `TRANSFER` |
| *(anything else)* | `UNCATEGORIZED` |

Matching is case-insensitive prefix match (e.g., `"Food & Dining"` matches `"food"`).

### Known quirks

| Quirk | Detail |
|-------|--------|
| **Amount sign is inverted** | The CSV stores purchases as positive. The parser flips the sign. Do **not** re-invert downstream. |
| **No running balance** | Visa exports contain no balance column. Balance verification is not possible without the statement PDF. |
| **PostingDate lag** | PostingDate is typically TransactionDate + 1. The parser stores TransactionDate and discards PostingDate. |
| **Category column optional** | Some RBC Avion exports omit the Category column. Parser defaults to `UNCATEGORIZED` if the column is absent. |
| **Merchant city suffix** | Descriptions end with `TORONTO ON`, `TORONTO ON CA`, etc. These are not stripped; the categoriser skill uses them for location-based rules. |

---

## Format 3 — Mortgage Amortization Schedule

### Column schema

| Column | Type | Notes |
|--------|------|-------|
| `PaymentNumber` | integer | 0 = opening balance row (skip); 1-N = payments |
| `Date` | `YYYY-MM-DD` | Scheduled payment date |
| `Payment` | decimal | Total monthly payment (fixed for most mortgages) |
| `Principal` | decimal | Portion reducing the principal balance |
| `Interest` | decimal | Interest portion; `Payment = Principal + Interest` |
| `Balance` | decimal | Remaining mortgage balance after this payment |

### Example rows

```csv
PaymentNumber,Date,Payment,Principal,Interest,Balance
0,2024-01-01,0.00,0.00,0.00,550000.00
1,2024-02-01,3057.61,995.11,2062.50,549004.89
2,2024-03-01,3057.61,998.84,2058.77,548006.05
24,2026-01-01,3057.61,1084.57,1973.04,525058.52
```

### Sign normalisation applied by parser

```
amount = -abs(Payment)   # mortgage payment is always an outflow
```

Description stored as:
```
"Mortgage payment #<N> (principal $<P>, interest $<I>)"
```

### Known quirks

| Quirk | Detail |
|-------|--------|
| **Row 0 is not a transaction** | `PaymentNumber == 0` has `Payment == 0.0` and represents the loan origination / opening balance. Skipped by the parser. |
| **All rows are HOUSING category** | Mortgage payments are pre-assigned `Category.HOUSING` — no categoriser step needed. |
| **Fixed payment, shifting principal/interest** | The `Payment` amount is constant; the split between `Principal` and `Interest` drifts monthly (amortisation). The parser stores both in the description text. |
| **Balance column is a projection** | Unlike chequing, the balance is calculated (not bank-confirmed). Use with care for "net worth" queries. |
| **No merchant description** | The `raw_description` field is set to `"MORTGAGE PAYMENT <N>"` for search purposes. |
