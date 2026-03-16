# LLM Prompt Template — Transaction Categorizer (Pass 2)

This file contains the exact prompt to send to the LLM when pattern matching
(Pass 1) has not categorized a transaction.  Fill in `{{TRANSACTIONS}}` with
the JSON array of unmatched transactions.

---

## How to use

```python
import json

def build_llm_prompt(unmatched_transactions: list[dict]) -> str:
    tx_json = json.dumps(unmatched_transactions, indent=2)
    with open("skills/transaction-categorizer/reference/llm_prompt_template.md") as f:
        template = f.read()
    # Extract only the SYSTEM PROMPT and USER PROMPT sections (below)
    # and substitute {{TRANSACTIONS}}
    return template.replace("{{TRANSACTIONS}}", tx_json)
```

Invoke with the project's LLM client (Ollama or Claude):

```python
from langchain_anthropic import ChatAnthropic
from langchain_ollama import ChatOllama

llm = ChatAnthropic(model="claude-sonnet-4-6")   # or ChatOllama(model="llama3")
response = llm.invoke(prompt)
result = json.loads(response.content)             # parse the JSON array
```

---

## SYSTEM PROMPT

```
You are a precise financial transaction categorizer for a Canadian personal
finance application. Your task is to assign each transaction to exactly one
category from the following list:

HOUSING        - mortgage, rent, property tax, home insurance, condo fees
GROCERIES      - supermarkets and bulk food stores (Loblaws, Costco, Metro, T&T, etc.)
DINING         - restaurants, coffee shops, food delivery (Uber Eats, Skip, DoorDash)
TRANSPORTATION - gas stations, transit (Presto, TTC), rideshare (Uber, Lyft), parking
UTILITIES      - electricity, gas, water, internet, phone, cable TV
SUBSCRIPTIONS  - streaming services, gym memberships, software subscriptions
SHOPPING       - retail stores, e-commerce, pharmacies, clothing, electronics
TRAVEL         - flights, hotels, car rentals, travel booking platforms, Airbnb
INCOME         - salary deposits, government transfers, tax refunds
TRANSFER       - bill payments, e-transfers sent, RRSP/TFSA contributions
OTHER          - clearly identified but does not fit any category above
UNCATEGORIZED  - use only if there is absolutely no information to classify with

Rules:
1. Choose the MOST SPECIFIC matching category.
2. Return ONLY a valid JSON array — no markdown, no explanation outside the JSON.
3. Include a "confidence" field: "HIGH" if you are certain, "MEDIUM" if you are
   reasonably confident, "LOW" if you are guessing or the description is ambiguous.
4. Include a brief "reasoning" field (one sentence) explaining your choice.
5. Preserve the "index" field from the input so results can be matched back.
6. Do NOT invent new category names. Use only the 12 values listed above.
```

---

## USER PROMPT

```
Categorize the following Canadian bank transactions. Return a JSON array with
one object per transaction.

Required output format per transaction:
{
  "index": <integer from input>,
  "description": "<original description>",
  "category": "<one of the 12 categories>",
  "confidence": "HIGH" | "MEDIUM" | "LOW",
  "reasoning": "<one sentence>"
}

Transactions to categorize:
{{TRANSACTIONS}}
```

---

## Few-shot examples

Include these in the user prompt **before** the `{{TRANSACTIONS}}` block if the
LLM is a smaller/local model (e.g., Ollama llama3) and needs guidance.  For
Claude Sonnet or Opus, the system prompt alone is sufficient.

### Input example

```json
[
  {"index": 0, "description": "LCBO #0445 TORONTO ON",       "amount": -43.87},
  {"index": 1, "description": "DOLLARAMA TORONTO ON",        "amount": -23.45},
  {"index": 2, "description": "HOME DEPOT TORONTO ON",       "amount": -345.67},
  {"index": 3, "description": "AIRBNB TORONTO ON",           "amount": -456.78},
  {"index": 4, "description": "E-TRANSFER SENT MICHAEL CHEN","amount": -200.00},
  {"index": 5, "description": "CANADA REVENUE AGENCY INSTALMENT", "amount": -1245.00},
  {"index": 6, "description": "BESTBUY.CA BLACK FRIDAY",     "amount": -678.90},
  {"index": 7, "description": "IKEA NORTH YORK ON",          "amount": -234.56},
  {"index": 8, "description": "RRSP CONTRIBUTION TD DIRECT", "amount": -5000.00},
  {"index": 9, "description": "E-TRANSFER RECEIVED DAVID KIM","amount": 500.00}
]
```

### Expected output example

```json
[
  {
    "index": 0,
    "description": "LCBO #0445 TORONTO ON",
    "category": "SHOPPING",
    "confidence": "HIGH",
    "reasoning": "LCBO is the provincial liquor board retail store — alcohol retail is SHOPPING."
  },
  {
    "index": 1,
    "description": "DOLLARAMA TORONTO ON",
    "category": "SHOPPING",
    "confidence": "HIGH",
    "reasoning": "Dollarama is a dollar/discount retail store."
  },
  {
    "index": 2,
    "description": "HOME DEPOT TORONTO ON",
    "category": "SHOPPING",
    "confidence": "HIGH",
    "reasoning": "Home Depot is a home improvement retail store, not a recurring housing cost."
  },
  {
    "index": 3,
    "description": "AIRBNB TORONTO ON",
    "category": "TRAVEL",
    "confidence": "HIGH",
    "reasoning": "Airbnb is a short-term accommodation platform — always TRAVEL."
  },
  {
    "index": 4,
    "description": "E-TRANSFER SENT MICHAEL CHEN",
    "category": "TRANSFER",
    "confidence": "LOW",
    "reasoning": "Personal e-transfer with no context; could be rent-splitting, a loan, or a gift — cannot determine purpose without more information."
  },
  {
    "index": 5,
    "description": "CANADA REVENUE AGENCY INSTALMENT",
    "category": "TRANSFER",
    "confidence": "HIGH",
    "reasoning": "CRA tax instalments are payments to the government — categorized as TRANSFER."
  },
  {
    "index": 6,
    "description": "BESTBUY.CA BLACK FRIDAY",
    "category": "SHOPPING",
    "confidence": "HIGH",
    "reasoning": "Best Buy is an electronics retail store."
  },
  {
    "index": 7,
    "description": "IKEA NORTH YORK ON",
    "category": "SHOPPING",
    "confidence": "HIGH",
    "reasoning": "IKEA is a furniture and home goods retail store."
  },
  {
    "index": 8,
    "description": "RRSP CONTRIBUTION TD DIRECT",
    "category": "TRANSFER",
    "confidence": "HIGH",
    "reasoning": "RRSP contributions are savings account transfers, not expenses."
  },
  {
    "index": 9,
    "description": "E-TRANSFER RECEIVED DAVID KIM",
    "category": "TRANSFER",
    "confidence": "LOW",
    "reasoning": "Incoming e-transfer from a person — could be income, expense reimbursement, or a loan repayment; purpose is ambiguous."
  }
]
```

---

## Post-processing rules

After receiving the LLM response:

1. Parse the JSON array.  If parsing fails, retry once with the prompt prefixed
   with: *"Return ONLY a raw JSON array. Do not include any text before or after
   the JSON."*

2. For each item:
   - If `confidence == "LOW"`, add to the user-review queue (see SKILL.md §
     "Handling LOW-confidence items").
   - If `category` is not one of the 12 valid values, default to `UNCATEGORIZED`
     and mark `confidence = "LOW"`.

3. Match results back to the original transactions using the `index` field.

4. If the LLM returns fewer items than were sent, the missing ones remain
   `UNCATEGORIZED` and are added to the user-review queue with a note:
   *"LLM did not return a result for this transaction."*
