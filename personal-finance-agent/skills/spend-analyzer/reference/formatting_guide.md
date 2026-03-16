# Formatting Guide — Spend Analyzer

Standards for presenting financial data clearly in a terminal / chat context.

---

## Currency

| Rule | Correct | Incorrect |
|------|---------|-----------|
| Always two decimal places | `$1,234.56` | `$1234.6` |
| Thousands separator | `$12,345.00` | `$12345.00` |
| Currency prefix | `$187.43` | `187.43 CAD` |
| Expenses (negative amounts) | `-$187.43` | `($187.43)` |
| Income (positive amounts) | `+$6,500.00` | `6500` |
| Zero | `$0.00` | `$0` or `—` |
| Percentage | `23.4%` | `23.42314%` |
| Large round numbers | `$5,000.00` | `$5k` |

**Python helper:**
```python
def fmt_cad(amount: float) -> str:
    """Format a signed float as CAD currency string."""
    sign = "-" if amount < 0 else ("+" if amount > 0 else "")
    return f"{sign}${abs(amount):,.2f}"

def fmt_pct(value: float) -> str:
    return f"{value:+.1f}%" if value is not None else "n/a"
```

---

## When to use tables vs prose vs lists

### Use a TABLE when:
- Comparing 3+ categories or periods side by side
- Showing Top-N results (ranked list with multiple columns)
- Presenting a trend with month-by-month rows

### Use PROSE when:
- Answering a single-number question: *"How much did I spend on groceries?"*
  → *"You spent $1,234.56 on groceries in January (8 transactions, avg $154.32)."*
- Summarising a table result in one sentence after the table
- Explaining a trend direction

### Use a BULLET LIST when:
- Flagging 2–5 anomalies or notable items
- Listing caveats or data-quality warnings
- Showing the "top 3" without needing columns

---

## Table layout standards

### Category summary table (PERIOD_SUMMARY, CATEGORY_BREAKDOWN)

```
Category        Transactions    Expenses    % of Total    Avg/Txn
--------------  ------------  ----------  -----------  ---------
GROCERIES               18    $1,456.78        22.3%    $80.93
DINING                  12      $987.45        15.1%    $82.29
TRANSPORTATION          15      $876.23        13.4%    $58.42
...
--------------  ------------  ----------  -----------  ---------
TOTAL (expenses)        87    $6,543.21       100.0%    $75.21
```

Rules:
- Sort by expenses descending (largest category first).
- Right-align all numeric columns.
- Left-align category names.
- Include a TOTAL row at the bottom.
- Omit `INCOME` and `TRANSFER` rows from expense breakdowns (show separately).

### Comparison table (COMPARISON)

```
Category        Jan 2026    Feb 2026      Delta    Change
--------------  ----------  ----------  --------  -------
GROCERIES       $1,234.56   $1,456.78   +$222.22   +18.0%
DINING            $876.23     $654.32   -$221.91   -25.3%
SHOPPING          $543.21     $987.65   +$444.44   +81.8%
...
```

Rules:
- Delta column: prefix `+` for increase, `-` for decrease.
- Change% column: prefix `+`/`-`, one decimal place.
- Flag rows with `|change_pct| > 20%` with a `(!)` marker.
- If a category appears in only one period, show `$0.00` for the other.

### Trend table (TREND)

```
Month       Transactions    Total       MoM Delta    MoM %   Trend
----------  ------------  ----------  -----------  -------   -----
2025-01             18    $1,234.56           —        —       —
2025-02             14    $1,456.78      +$222.22   +18.0%    [+]
2025-03             20    $1,123.45      -$333.33   -22.9%    [-]
2025-04             16    $1,189.23       +$65.78    +5.9%    [=]
```

Rules:
- `[+]` = increase >2%, `[-]` = decrease >2%, `[=]` = within ±2%.
- First row always has `—` for delta/%.
- If >12 months of data, only show the trailing 12 months by default.

### Top-N table (TOP_N)

```
 #   Date        Description                      Category        Amount
---  ----------  -------------------------------- --------------  ----------
  1  2025-12-10  AMAZON.CA CHRISTMAS SHOPPING     SHOPPING        $567.89
  2  2025-05-25  IKEA NORTH YORK ON               SHOPPING        $456.78
  3  2025-06-22  AIRBNB TORONTO ON                TRAVEL          $456.78
```

Rules:
- Rank column right-aligned.
- Truncate descriptions longer than 40 characters with `…`.
- Sort by amount descending (largest expense first).

---

## Prose summary sentence templates

**After PERIOD_SUMMARY:**
> "You spent **$X** in [period] across [N] categories.
> [Top category] was your largest expense at **$Y** ([Z]% of total)."

**After COMPARISON:**
> "[Category] had the biggest change: [up/down] **[Delta]** ([Pct]%) from
> [Period A] to [Period B]."

**After TREND:**
> "Your [category] spending has [increased/decreased/stayed stable] over
> [N] months, [up/down] **[total change]** from [first month] to [last month]."

**After ANOMALY:**
> "Found [N] potentially unusual transaction(s). The most notable is
> **[description]** on [date] at **$X**, which is [Y]× the typical
> [category] charge."

**When no data:**
> "No [category/period] transactions found. The available data runs from
> [earliest] to [latest]."

---

## Warnings to include when relevant

Always append as a footnote below the table, not inline:

- `* UNCATEGORIZED transactions are excluded from category totals.`
- `* Mortgage amortisation payments are excluded from expense calculations.`
- `* Credit card payments (TRANSFER) are excluded to avoid double-counting.`
- `* Anomaly detection requires at least 3 prior transactions per category.`
