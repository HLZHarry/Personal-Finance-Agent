# SQL Query Templates — Spend Analyzer

All queries run against the `transactions` table in `data/finance.db`.

Schema reminder:
```
transactions(id, date TEXT, description TEXT, amount REAL,
             category TEXT, account_type TEXT, source_file TEXT,
             raw_description TEXT, account_name TEXT, institution TEXT)
```

Sign convention: `amount < 0` = expense, `amount > 0` = income.
Dates are stored as ISO-8601 strings (`YYYY-MM-DD`); use `substr(date,1,7)`
for month-level grouping (`YYYY-MM`).

---

## 1. Period Summary

Returns total expenses, income, and count per category for a date range.
Use for: *"What did I spend last month?"*, *"Summarise Q1 2025"*

```sql
SELECT
    category,
    COUNT(*)                                                      AS txn_count,
    ROUND(SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END), 2) AS expenses,
    ROUND(SUM(CASE WHEN amount > 0 THEN amount      ELSE 0 END), 2) AS income,
    ROUND(AVG(CASE WHEN amount < 0 THEN ABS(amount) ELSE NULL END), 2) AS avg_expense
FROM transactions
WHERE date BETWEEN '{start_date}' AND '{end_date}'
  AND account_type != 'mortgage'          -- exclude amortisation noise
GROUP BY category
ORDER BY expenses DESC;
```

**Parameters:** `{start_date}` `{end_date}` — ISO-8601 strings (`YYYY-MM-DD`)

**Derived metrics to add in Python:**
- `pct_of_total` = `expenses / SUM(expenses) * 100` per row

**Example call:**
```python
df = sql.query(template.format(start_date="2025-01-01", end_date="2025-01-31"))
```

---

## 2. Category Breakdown

Returns individual transactions for one category in a period.
Use for: *"Break down my dining spending in January"*

```sql
SELECT
    date,
    description,
    ROUND(ABS(amount), 2) AS amount,
    account_type
FROM transactions
WHERE date BETWEEN '{start_date}' AND '{end_date}'
  AND category = '{category}'
  AND amount < 0
ORDER BY amount ASC;          -- largest expense first (most negative = lowest)
```

**Parameters:** `{start_date}` `{end_date}` `{category}` (uppercase enum value)

**Summary header query** (run first, display above the detail table):
```sql
SELECT
    COUNT(*)                            AS txn_count,
    ROUND(SUM(ABS(amount)), 2)          AS total,
    ROUND(AVG(ABS(amount)), 2)          AS avg_per_txn,
    ROUND(MAX(ABS(amount)), 2)          AS largest_single,
    ROUND(MIN(ABS(amount)), 2)          AS smallest_single
FROM transactions
WHERE date BETWEEN '{start_date}' AND '{end_date}'
  AND category = '{category}'
  AND amount < 0;
```

---

## 3. Comparison (two periods)

Side-by-side category totals for Period A vs Period B.
Use for: *"Compare January vs February spending"*

```sql
SELECT
    COALESCE(a.category, b.category)         AS category,
    COALESCE(a.expenses, 0)                  AS period_a,
    COALESCE(b.expenses, 0)                  AS period_b,
    ROUND(COALESCE(b.expenses, 0)
        - COALESCE(a.expenses, 0), 2)        AS delta,
    CASE
        WHEN COALESCE(a.expenses, 0) = 0 THEN NULL
        ELSE ROUND(
            (COALESCE(b.expenses, 0) - COALESCE(a.expenses, 0))
            / COALESCE(a.expenses, 0) * 100, 1)
    END                                      AS change_pct
FROM (
    SELECT category,
           ROUND(SUM(ABS(amount)), 2) AS expenses
    FROM transactions
    WHERE date BETWEEN '{start_a}' AND '{end_a}'
      AND amount < 0
    GROUP BY category
) a
FULL OUTER JOIN (
    SELECT category,
           ROUND(SUM(ABS(amount)), 2) AS expenses
    FROM transactions
    WHERE date BETWEEN '{start_b}' AND '{end_b}'
      AND amount < 0
    GROUP BY category
) b ON a.category = b.category
ORDER BY COALESCE(b.expenses, 0) DESC;
```

> **SQLite note:** SQLite does not support `FULL OUTER JOIN`.  Use the
> `analyze.py` script which runs two separate queries and merges in pandas,
> or replace with a `UNION`-based workaround (see below).

**SQLite-compatible alternative:**
```sql
SELECT category, period, ROUND(SUM(ABS(amount)), 2) AS expenses
FROM (
    SELECT category, amount, 'A' AS period
    FROM transactions
    WHERE date BETWEEN '{start_a}' AND '{end_a}' AND amount < 0
    UNION ALL
    SELECT category, amount, 'B' AS period
    FROM transactions
    WHERE date BETWEEN '{start_b}' AND '{end_b}' AND amount < 0
)
GROUP BY category, period
ORDER BY category, period;
```
Then pivot on `period` in pandas.

**Parameters:** `{start_a}` `{end_a}` `{start_b}` `{end_b}`

---

## 4. Top-N Largest Expenses

Biggest individual expense transactions, optionally filtered by category.
Use for: *"What were my 10 biggest expenses?"*, *"Top 5 dining charges"*

```sql
SELECT
    date,
    description,
    category,
    account_type,
    ROUND(ABS(amount), 2) AS amount
FROM transactions
WHERE amount < 0
  {category_filter}
  {date_filter}
ORDER BY amount ASC            -- most negative = largest expense
LIMIT {n};
```

**Parameters:**
- `{n}` — integer, default 10
- `{category_filter}` — either blank or `AND category = '{category}'`
- `{date_filter}` — either blank or `AND date BETWEEN '{start_date}' AND '{end_date}'`

---

## 5. Monthly Trend

Monthly totals for one category (or all expenses) over time.
Use for: *"Is my dining spending going up?"*, *"Show monthly grocery totals"*

```sql
SELECT
    substr(date, 1, 7)                     AS month,
    COUNT(*)                               AS txn_count,
    ROUND(SUM(ABS(amount)), 2)             AS total_expenses,
    ROUND(AVG(ABS(amount)), 2)             AS avg_per_txn
FROM transactions
WHERE amount < 0
  {category_filter}
  {date_filter}
GROUP BY month
ORDER BY month ASC;
```

**Parameters:**
- `{category_filter}` — blank for all categories, or `AND category = '{category}'`
- `{date_filter}` — blank for all time, or `AND date BETWEEN '{start_date}' AND '{end_date}'`

**Derived metrics to add in Python:**
- `mom_delta` = current month total − previous month total
- `mom_pct` = `mom_delta / previous * 100`
- `trend_dir` = `"+"` if `mom_delta > 0`, `"-"` if < 0, `"="` if within 2%

---

## 6. Anomaly Detection

Transactions that are outliers within their own category (more than 2 SD above
the category mean for the trailing 90 days).
Use for: *"Any unusual charges?"*, *"Anything that looks wrong?"*

```sql
WITH category_stats AS (
    SELECT
        category,
        AVG(ABS(amount))                    AS cat_mean,
        AVG(ABS(amount) * ABS(amount))
            - AVG(ABS(amount)) * AVG(ABS(amount))  AS cat_variance
    FROM transactions
    WHERE amount < 0
      AND date >= date('now', '-90 days')
    GROUP BY category
    HAVING COUNT(*) >= 3                    -- need at least 3 to compute SD
),
anomalies AS (
    SELECT
        t.date,
        t.description,
        t.category,
        ROUND(ABS(t.amount), 2)             AS amount,
        ROUND(s.cat_mean, 2)                AS category_avg,
        ROUND(ABS(t.amount) / NULLIF(s.cat_mean, 0), 1) AS times_avg
    FROM transactions t
    JOIN category_stats s ON t.category = s.category
    WHERE t.amount < 0
      AND t.date >= date('now', '-90 days')
      AND ABS(t.amount) > s.cat_mean + 2 * SQRT(MAX(s.cat_variance, 0))
)
SELECT * FROM anomalies
ORDER BY times_avg DESC;
```

> **Date function note:** `date('now', '-90 days')` uses SQLite's built-in
> date arithmetic.  Replace `'now'` with a literal date string for
> reproducible test runs: `date('2025-12-31', '-90 days')`.

---

## Utility queries

### Available date range
```sql
SELECT MIN(date) AS earliest, MAX(date) AS latest,
       COUNT(DISTINCT substr(date,1,7)) AS months_available
FROM transactions;
```

### Monthly totals overview (all time)
```sql
SELECT substr(date,1,7) AS month,
       COUNT(*) AS txn_count,
       ROUND(SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END), 2) AS expenses,
       ROUND(SUM(CASE WHEN amount > 0 THEN amount      ELSE 0 END), 2) AS income
FROM transactions
GROUP BY month
ORDER BY month;
```

### Uncategorized count
```sql
SELECT COUNT(*) AS uncategorized_count
FROM transactions
WHERE category = 'UNCATEGORIZED';
```
