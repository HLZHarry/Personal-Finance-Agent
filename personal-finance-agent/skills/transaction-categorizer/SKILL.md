```markdown
---
name: transaction-categorizer
description: >
  Categorize financial transactions into spending categories like groceries,
  dining, utilities, transportation, etc. Uses merchant name pattern matching
  and LLM classification for ambiguous transactions.
---

# Transaction categorizer

## When to use
- After parsing statements (auto-triggered)
- User asks about spending by category
- User asks "what did I spend on X"

## Categories
- Housing (mortgage, rent, property tax, insurance)
- Groceries (Loblaws, No Frills, T&T, Costco, etc.)
- Dining (restaurants, takeout, coffee shops)
- Transportation (gas, Presto, Uber, parking)
- Utilities (hydro, gas, water, internet, phone)
- Subscriptions (Netflix, Spotify, gym, etc.)
- Shopping (Amazon, retail stores)
- Travel (flights, hotels, car rental)
- Income (salary, e-transfers received)
- Other (uncategorized)

## Instructions
1. First pass: pattern matching on merchant names
2. Second pass: LLM classification for unmatched transactions
3. Return transactions with category field populated
4. Track categorization confidence (high/medium/low)
```