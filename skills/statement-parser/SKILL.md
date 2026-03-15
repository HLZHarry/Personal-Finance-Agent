```markdown
---
name: statement-parser
description: >
  Parse financial statements from different Canadian banks (RBC, TD, BMO, etc.)
  into a standardized transaction format. Handles CSV exports and PDF statements.
  Use this skill when the user uploads or references a bank statement file.
---

# Statement parser

## When to use
- User uploads a bank statement (CSV, PDF)
- User asks to "import" or "load" financial data
- User references specific bank statement files

## Supported formats
- RBC chequing CSV exports
- Visa/Mastercard CSV statements
- PDF credit card statements (via text extraction)
- Mortgage amortization schedules

## Output format
All parsed statements produce a standardized JSON structure:
```json
{
  "source": "rbc_chequing",
  "period": "2025-01 to 2025-12",
  "transactions": [
    {
      "date": "2025-01-15",
      "description": "LOBLAWS #1234",
      "amount": -85.42,
      "category": null,
      "account_type": "chequing"
    }
  ]
}
``` {data-source-line="410"}

## Instructions
1. Detect the file format (CSV vs PDF)
2. Identify the bank/institution from headers or filename
3. Map columns to the standardized schema
4. Normalize amounts (debits as negative, credits as positive)
5. Validate date formats and sort chronologically