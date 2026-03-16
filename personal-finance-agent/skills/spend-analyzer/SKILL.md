---
name: spend-analyzer
version: "2.0"
description: >
  Answer spending-pattern questions using SQL (FinanceSQLStore) for exact
  aggregations and ChromaDB vector search (FinanceVectorStore) for semantic
  description queries.  Handles six query types: period summary, category
  breakdown, comparison, top-N, trend, and anomaly detection.
triggers:
  - user asks about spending amounts, totals, or budgets
  - user asks to compare two time periods
  - user asks for biggest/top expenses
  - user asks about trends or whether spending is going up
  - user asks about unusual or unexpected charges
  - user asks "what did I spend on X"
prereqs:
  - transactions ingested into data/finance.db (run src/pipeline.py first)
  - categories assigned (run transaction-categorizer skill first for best results)
---

# Spend Analyzer

## When to use

Activate this skill when the user asks **any quantitative question about their
spending**, including:

*"What did I spend last month?"* · *"Break down my January spending"* ·
*"Compare January vs February"* · *"What were my biggest expenses?"* ·
*"Is my dining spending going up?"* · *"Any unusual charges?"* ·
*"How much did I spend at Loblaws?"* · *"Show me all transactions over $200"*

## When NOT to use

- The user asks a **predictive** question ("Will I run out of money?") →
  use `cashflow-forecaster` skill instead.
- Transactions have not been ingested yet → run `src/pipeline.py` first.
- The user wants to **categorize** uncategorized transactions →
  use `transaction-categorizer` skill first, then re-run analysis.

---

## Decision tree — classify the query type

```
User question
    │
    ├─ contains "last month / this year / between / from … to" ──► PERIOD_SUMMARY
    │
    ├─ contains "break down / by category / how much on X"     ──► CATEGORY_BREAKDOWN
    │
    ├─ contains "compare / vs / versus / difference"           ──► COMPARISON
    │
    ├─ contains "biggest / largest / top N / most expensive"   ──► TOP_N
    │
    ├─ contains "trend / over time / going up / month by month"──► TREND
    │
    ├─ contains "unusual / unexpected / strange / anomaly"     ──► ANOMALY
    │
    └─ unclear → ask the user one clarifying question, then route above
```

Ambiguous phrasing ("show me my spending") defaults to **PERIOD_SUMMARY** for
the most recent month with data.

---

## SQL vs vector search — when to use each

| Use SQL (`FinanceSQLStore.query()`) | Use vector search (`FinanceVectorStore.search()`) |
|-------------------------------------|---------------------------------------------------|
| Exact totals, counts, averages | "Find transactions that look like business meals" |
| Date-range filtering | "Anything related to travel in summer" |
| GROUP BY category / month | Description contains ambiguous merchant names |
| Top-N by amount | User describes a transaction but can't name the merchant |
| Trend over N months | Supplementing SQL results with semantic context |

**Default:** run SQL first for every query type. Add a vector search only when
the question uses natural-language descriptions that don't map to a category or
exact merchant name.

---

## Query type instructions

### 1. PERIOD_SUMMARY

**Trigger phrases:** "last month", "this year", "in January", "Q1", "between X and Y"

1. Parse the period from the question → derive `{start_date}` and `{end_date}`.
2. Run the **period-summary** SQL template from
   [`reference/query_templates.md`](reference/query_templates.md).
3. Calculate `% of total expenses` for each category row.
4. Format as a category table sorted by absolute spend (largest first).
5. Add a one-sentence prose summary: *"You spent $X in total, with groceries
   being the largest category at $Y (Z%)."*

### 2. CATEGORY_BREAKDOWN

**Trigger phrases:** "break down", "by category", "how much on groceries"

1. If a specific category is named, filter to that category.
   Otherwise show all categories for the period.
2. Run the **category-breakdown** SQL template.
3. Include: total, count, average per transaction, largest single transaction.
4. For the named category, also run a vector search with the category name to
   surface the top 5 individual transactions semantically closest to the query.

### 3. COMPARISON

**Trigger phrases:** "compare", "vs", "versus", "January compared to February"

1. Extract two periods (Period A and Period B).
2. Run the **comparison** SQL template (two subqueries joined on category).
3. Calculate absolute delta and percentage change per category.
4. Highlight categories where spending increased >20% (flag as notable).
5. Format as a side-by-side table: Category | Period A | Period B | Delta | Change%.

### 4. TOP_N

**Trigger phrases:** "biggest", "largest", "top 5", "most expensive"

1. Default N=10 if not specified. Extract N from the question if present.
2. Run the **top-n** SQL template.
3. Include: rank, date, description, category, amount.
4. If the user says "in dining" or names a category, add a `WHERE category =`
   filter.
5. Format as a numbered list or table.

### 5. TREND

**Trigger phrases:** "trend", "over time", "going up", "month by month", "is X increasing"

1. Extract the category of interest (or default to "total spending").
2. Run the **trend** SQL template grouped by month.
3. Calculate month-over-month change (absolute and %).
4. Identify the direction: consistently up / down / stable / volatile.
5. Format as a month table with a trend indicator column (`+` / `-` / `=`).
6. Add a one-sentence interpretation: *"Your dining spending has increased for
   3 consecutive months, up 18% from October to December."*

### 6. ANOMALY

**Trigger phrases:** "unusual", "unexpected", "strange charges", "anything weird"

1. Run the **anomaly** SQL template: transactions more than 2 standard
   deviations above the category mean.
2. Also run a vector search: `"unexpected unusual transaction"` to catch
   one-off merchants that don't fit typical patterns.
3. Combine SQL and vector results (deduplicate by transaction ID).
4. Format as a list: Date | Description | Amount | Why flagged (e.g.,
   "3.4x above dining average").

---

## Running with the helper script

For any query type, the `scripts/analyze.py` helper handles SQL execution,
derived-metric calculation, and table formatting:

```bash
python skills/spend-analyzer/scripts/analyze.py \
    --query-type period-summary \
    --start-date 2025-01-01 \
    --end-date   2025-01-31

python skills/spend-analyzer/scripts/analyze.py \
    --query-type comparison \
    --period-a 2026-01 \
    --period-b 2026-02

python skills/spend-analyzer/scripts/analyze.py \
    --query-type top-n --n 10

python skills/spend-analyzer/scripts/analyze.py \
    --query-type trend --category DINING

python skills/spend-analyzer/scripts/analyze.py \
    --query-type anomaly
```

---

## Handling missing data

| Situation | Response |
|-----------|----------|
| Requested period has no transactions | *"No transactions found for [period]. The data covers [actual range]. Did you mean [nearest period]?"* |
| Category has 0 transactions | Omit from table; note in prose: *"No [category] transactions in this period."* |
| Only one month of data for a trend | *"Trend analysis needs at least 2 months. Currently only [month] is available."* |
| `UNCATEGORIZED` transactions present | Show them in the breakdown; append: *"X transactions are still uncategorized — run the transaction-categorizer skill for a more accurate breakdown."* |
| SQLite not found / empty | *"No data found at data/finance.db. Run `python -m src.pipeline` to ingest your statements first."* |

---

## Reference files

| File | Purpose |
|------|---------|
| [`reference/query_templates.md`](reference/query_templates.md) | Parameterized SQL for all 6 query types |
| [`reference/formatting_guide.md`](reference/formatting_guide.md) | Currency formatting, table standards, prose vs table rules |
| [`scripts/analyze.py`](scripts/analyze.py) | CLI runner: executes queries, formats output, prints tables |
