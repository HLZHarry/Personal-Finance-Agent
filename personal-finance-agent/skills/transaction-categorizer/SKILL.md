---
name: transaction-categorizer
version: "2.0"
description: >
  Categorize transactions into the project's 12-value Category enum using a
  deterministic two-pass pipeline: (1) regex pattern matching against a known
  Canadian merchant list, (2) LLM classification for anything unmatched.
  Pattern matches carry HIGH confidence; LLM results carry MEDIUM or LOW.
  LOW-confidence items are surfaced to the user for manual review.
triggers:
  - transactions have category == UNCATEGORIZED after parsing
  - user asks "what did I spend on X"
  - user asks to categorize, label, or tag transactions
  - upstream skill hands off a TransactionSet for classification
categories:
  - HOUSING | GROCERIES | DINING | TRANSPORTATION | UTILITIES
  - SUBSCRIPTIONS | SHOPPING | TRAVEL | INCOME | TRANSFER | OTHER | UNCATEGORIZED
---

# Transaction Categorizer

## When to use

Activate this skill when **any** of the following are true:

- One or more transactions have `category == "UNCATEGORIZED"` and the user
  wants spending analysis.
- The user says *"categorize my transactions"*, *"what category is this?"*,
  *"tag my spending"*, or *"label these transactions"*.
- The `statement-parser` skill just completed and handed off a TransactionSet.
- The user asks a category-level question: *"how much did I spend on groceries?"*
  — categorize first, then answer.

## When NOT to use

- All transactions already have non-`UNCATEGORIZED` categories — skip directly
  to `spend-analyzer`.
- The user wants to *rename* or *redefine* a category (that requires a schema
  change, not categorization).
- The transaction set contains only `HOUSING` or `INCOME` items already labelled
  by the parser (mortgage payments and payroll are pre-classified).
- The user explicitly asks to skip categorization and view raw data.

---

## Two-pass process overview

```
TransactionSet (UNCATEGORIZED items)
         │
         ▼
  ┌─────────────────────┐
  │  PASS 1             │  deterministic, instant
  │  Pattern matching   │  → HIGH confidence
  │  (merchant_patterns)│
  └────────┬────────────┘
           │ unmatched
           ▼
  ┌─────────────────────┐
  │  PASS 2             │  calls LLM once per batch
  │  LLM classification │  → MEDIUM or LOW confidence
  │  (llm_prompt_template)
  └────────┬────────────┘
           │ LOW confidence
           ▼
  Ask user for clarification
           │
           ▼
  Final categorized TransactionSet
```

---

## Pass 1 — Pattern matching

**Run this first on every transaction.**

### How to run

```bash
python skills/transaction-categorizer/scripts/pattern_categorize.py \
    --input transactions.json \
    --patterns skills/transaction-categorizer/reference/merchant_patterns.json \
    --output categorized.json
```

Or call programmatically:

```python
from skills.transaction_categorizer.scripts.pattern_categorize import categorize_by_pattern

categorized, unmatched = categorize_by_pattern(transactions, patterns_path)
# categorized → list of (Transaction, category, "HIGH")
# unmatched   → list of Transaction (send to Pass 2)
```

### How it works

1. Load `reference/merchant_patterns.json` — a dict mapping category names
   to lists of regex patterns.
2. For each transaction, uppercase the `description` field and test it against
   every pattern with `re.search()`.
3. First match wins. Assign that category with confidence `HIGH`.
4. Transactions with no match go to the unmatched list for Pass 2.

### Rules

- Matching is case-insensitive (`re.IGNORECASE`). Descriptions are already
  uppercase from the parser, but normalise defensively.
- Patterns are plain substrings or simple regexes (no lookaheads needed).
- The order of categories in the JSON file determines priority when a
  description could match multiple categories (put more-specific patterns
  earlier).
- **Do not modify** merchant_patterns.json at runtime. It is a static
  reference; update it via a code change.

### Skip conditions (do not run pattern matching on these)

| Condition | Reason |
|-----------|--------|
| `account_type == "MORTGAGE"` | Already `HOUSING` from parser |
| `category != "UNCATEGORIZED"` | Already classified (e.g., Visa CSV categories) |
| `amount > 0` and description contains `PAYROLL` / `DEPOSIT` / `SALARY` | Pre-assign `INCOME` |

---

## Pass 2 — LLM classification

**Run only on transactions that Pass 1 did not match.**

### Batching

Collect all unmatched transactions and send them in a **single LLM call**
(batch in the prompt, not one call per transaction). This keeps latency
acceptable.  Maximum batch size: 50 transactions per call.  If there are more,
split into chunks of 50.

### How to invoke

Use the prompt template from
[`reference/llm_prompt_template.md`](reference/llm_prompt_template.md).
Fill in the `{{TRANSACTIONS}}` placeholder with the JSON array of unmatched
transactions.

Expected LLM response (JSON array, one object per transaction):

```json
[
  {
    "index": 0,
    "description": "DOLLARAMA TORONTO ON",
    "category": "SHOPPING",
    "confidence": "MEDIUM",
    "reasoning": "Dollarama is a discount/dollar store — retail shopping."
  }
]
```

### Confidence rules (for Pass 2 only)

| Condition | Assign |
|-----------|--------|
| LLM states high certainty OR description clearly matches a known type | `MEDIUM` |
| LLM is uncertain, description is ambiguous, or `reasoning` includes words like "unclear", "could be", "possibly" | `LOW` |

If the LLM does not return a `confidence` field, infer it from `reasoning`
length and hedging language.

---

## Handling LOW-confidence items

After both passes, collect every transaction with confidence `LOW`.

1. **Present them to the user** as a grouped list:

   ```
   I couldn't confidently categorize 3 transactions. Please clarify:

   1. DOLLARAMA TORONTO ON  –$23.45  (2025-01-19)
      My guess: SHOPPING — is that right, or should it be GROCERIES / OTHER?

   2. LCBO #0445 TORONTO ON  –$43.87  (2025-01-23)
      My guess: SHOPPING — alcohol store; categorize as SHOPPING or OTHER?

   3. E-TRANSFER SENT MICHAEL CHEN  –$200.00  (2025-01-30)
      My guess: TRANSFER — personal payment; confirm or specify (e.g., rent share)?
   ```

2. Accept the user's answer and update the category to their response.
   Upgrade confidence to `HIGH` once the user confirms.

3. If the user says *"just use your best guess"* — accept the LLM category,
   set confidence `LOW`, and proceed without blocking.

---

## Confidence summary table

| Source | Confidence | Meaning | Action |
|--------|------------|---------|--------|
| Pattern match (Pass 1) | `HIGH` | Deterministic regex hit | Accept, no review needed |
| LLM, clear answer | `MEDIUM` | LLM confident | Accept, log for audit |
| LLM, ambiguous | `LOW` | LLM uncertain | Ask user before finalising |
| User-confirmed | `HIGH` | Human verified | Authoritative |

---

## Output format

After both passes, emit an updated TransactionSet (or JSON array) with each
transaction annotated:

```jsonc
{
  "source": "rbc_chequing_2025.csv",
  "transactions": [
    {
      "date": "2025-01-05",
      "description": "LOBLAWS #1234 TORONTO ON",
      "amount": -187.43,
      "category": "GROCERIES",          // updated from UNCATEGORIZED
      "account_type": "CHEQUING",
      "categorization": {
        "method": "pattern",            // "pattern" | "llm" | "user"
        "confidence": "HIGH",           // "HIGH" | "MEDIUM" | "LOW"
        "pattern_matched": "LOBLAWS"    // which pattern fired, or LLM reasoning
      }
    }
  ],
  "categorization_summary": {
    "total": 342,
    "by_method": {"pattern": 289, "llm": 48, "user": 5},
    "by_confidence": {"HIGH": 294, "MEDIUM": 43, "LOW": 5},
    "still_uncategorized": 0
  }
}
```

The `categorization` block is for audit purposes and does not need to be stored
in ChromaDB or SQLite — it can be stripped before ingestion.

---

## Reference files

| File | Purpose |
|------|---------|
| [`reference/merchant_patterns.json`](reference/merchant_patterns.json) | Regex patterns → category, 10+ entries per category, Canadian merchants |
| [`reference/category_definitions.md`](reference/category_definitions.md) | Precise definitions, edge cases, and examples for all 12 categories |
| [`reference/llm_prompt_template.md`](reference/llm_prompt_template.md) | Exact prompt template with few-shot examples for LLM Pass 2 |
| [`scripts/pattern_categorize.py`](scripts/pattern_categorize.py) | Deterministic Pass 1 script; run standalone or import |
