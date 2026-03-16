---
name: cashflow-forecaster
version: "2.0"
description: >
  Project future daily account balance for the next 30, 60, or 90 days by
  detecting recurring transactions (fixed and variable), extrapolating their
  expected dates and amounts forward, and flagging any day where the projected
  balance falls below a configurable risk threshold.
triggers:
  - user asks "what will my balance be next month"
  - user asks "can I afford X"
  - user asks about upcoming bills or recurring charges
  - user asks "when will I run out of money"
  - user wants a cash-flow projection or forecast
prereqs:
  - transactions ingested into data/finance.db (run src/pipeline.py first)
  - at least 3 months of transaction history for reliable recurring detection
---

# Cash Flow Forecaster

## When to use

Activate this skill when the user asks any **forward-looking** financial
question:

*"What will my balance look like next month?"* · *"Can I afford a $2,000
vacation in March?"* · *"What are my fixed monthly bills?"* ·
*"When is my next mortgage payment?"* · *"Will I go negative before payday?"*

## When NOT to use

- User asks about **past** spending → use `spend-analyzer` skill.
- Fewer than 3 months of transaction history in the database — the recurrence
  detector needs enough data to distinguish recurring from coincidental.
- User asks about investment returns or compound growth — this skill models
  cash flow only, not interest or investment returns.

---

## Three-step method

```
Step 1: Detect recurring transactions
        scripts/detect_recurring.py  →  recurring.json
             │
             ▼
Step 2: Project forward N days
        scripts/project_cashflow.py  →  projection table
             │
             ▼
Step 3: Flag risk dates
        Days where balance < threshold  →  risk report
```

---

## Step 1 — Detect recurring transactions

Run the detector to classify every description that appears 3+ times:

```bash
python skills/cashflow-forecaster/scripts/detect_recurring.py \
    --db data/finance.db \
    --min-occurrences 3 \
    --output recurring.json
```

The script classifies each recurring series as **FIXED** or **VARIABLE**:

| Type | Rule | Examples |
|------|------|---------|
| **FIXED** | Amount coefficient of variation < 10% | Netflix, Rogers, Mortgage |
| **VARIABLE** | CV ≥ 10% | Groceries, Gas, Hydro |

And assigns a **frequency**:

| Label | Mean gap | Examples |
|-------|----------|---------|
| `WEEKLY` | < 9 days | Weekly grocery run |
| `BI_WEEKLY` | 9–19 days | Bi-weekly payroll |
| `MONTHLY` | 19–45 days | Mortgage, subscriptions |
| `QUARTERLY` | 45–120 days | Insurance, RRSP |

A series must also have a **consistent gap** (gap std-dev / mean < 0.35) to be
treated as genuinely recurring rather than coincidentally repeated.

See [`reference/recurring_patterns.md`](reference/recurring_patterns.md) for
guidance on Canadian-specific recurring patterns and how to distinguish
recurring from coincidental transactions.

---

## Step 2 — Project forward

```bash
python skills/cashflow-forecaster/scripts/project_cashflow.py \
    --recurring recurring.json \
    --balance   14235.67 \
    --days      60 \
    --threshold 2000
```

Key flags:
- `--balance` — current account balance (ask the user or read from their last
  statement's closing balance)
- `--days` — projection window: 30, 60, or 90 (default 30)
- `--threshold` — balance floor for risk alerts (default $0; suggest $1,000
  as a practical minimum for most users)
- `--as-of-date` — override "today" with a specific date (useful for
  historical what-if analysis)

For **variable** recurring items the script uses the historical average amount.
This is conservative: actual spending may be lower, making the projection a
useful worst-case floor.

---

## Step 3 — Interpret and present results

### Summary to give the user

1. **Fixed monthly outflows** — list each FIXED MONTHLY/BI_WEEKLY item with
   its exact amount and typical day of the month.
2. **Variable monthly outflows** — list VARIABLE items with their historical
   average and range.
3. **Upcoming 30-day projection** — run the projection script and extract the
   lowest projected balance and the date it occurs.
4. **Risk flags** — any date where the balance is projected below threshold.

### Projection window guidance

| User question | Use `--days` |
|---------------|-------------|
| "Next paycheque" / "This month" | 30 |
| "Next two months" / "Can I afford X in April?" | 60 |
| "Next quarter" / "Summer planning" | 90 |

### Presenting risk flags to the user

When a risk date is found:
> *"Based on your recurring expenses, your balance is projected to drop to
> **$X** on **[date]** — below your $Y threshold. Your next payroll deposit
> of $6,500 arrives on approximately **[next payday]**, which should bring
> the balance back to **$Z**."*

When no risk dates:
> *"Your projected balance stays above $Y throughout the next 30 days,
> with a minimum of **$X** on **[date]** just before your payroll deposit."*

---

## Fixed vs variable expenses — classification guide

**Fixed (exact same amount each period):**
- Mortgage/rent payment — exact principal + interest
- Streaming subscriptions (Netflix, Spotify, Disney+)
- Phone/internet (Rogers, Bell, Telus on a fixed plan)
- Gym memberships on a fixed contract

**Variable (fluctuating amount, consistent frequency):**
- Grocery stores — amount varies week to week
- Gas — price-per-litre and fill-up size vary
- Utilities (hydro, gas) — seasonal variation
- Visa card payment — varies with monthly spend

**Not recurring (even if repeated):**
- E-transfers to different people in varying amounts
- Restaurant visits with varying amounts and gaps
- Amazon purchases with no consistent gap

---

## Handling missing or insufficient data

| Situation | Response |
|-----------|----------|
| Fewer than 3 months of data | *"Need at least 3 months of history. Currently have [N] months. Projection confidence is LOW."* |
| No income detected | Ask the user for their net pay and pay frequency before projecting |
| Missing current balance | Ask: *"What is your current chequing account balance?"* |
| VARIABLE item with high variance (CV > 50%) | Use median instead of mean; widen the note: *"This estimate has high uncertainty."* |
| Gap inconsistency (bills sometimes skip) | Exclude from projection; note: *"[Item] has irregular timing and is excluded."* |

---

## Reference files

| File | Purpose |
|------|---------|
| [`reference/recurring_patterns.md`](reference/recurring_patterns.md) | Canadian banking recurring patterns, detection rules, and edge cases |
| [`scripts/detect_recurring.py`](scripts/detect_recurring.py) | Detects recurring transactions and classifies fixed vs variable |
| [`scripts/project_cashflow.py`](scripts/project_cashflow.py) | Projects daily balance and flags risk dates |
