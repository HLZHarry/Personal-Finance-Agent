# Phase 2: Document Parsing Pipeline (~3 hours)
## Personal Finance Agent — Learning Project

---

## What You're Building

A pipeline that takes raw bank statements (CSV and PDF) and:
1. Parses them into structured transaction data (Pydantic models)
2. Chunks and embeds them into ChromaDB for vector search
3. Also stores structured data in a queryable format (pandas DataFrame → SQLite)

This dual-storage approach is key to **agentic RAG** — your agent will later
decide whether to do vector search (semantic questions) or SQL queries
(exact numerical questions) depending on the question type.

---

## Key Concept: Why Dual Storage?

Traditional RAG stuffs everything into a vector DB. But financial data has
two natures:

| Question Type | Best Retrieval | Example |
|--------------|----------------|---------|
| Semantic / fuzzy | Vector search (ChromaDB) | "What were my big purchases recently?" |
| Exact / numerical | SQL query (SQLite) | "Total groceries spend in January 2026?" |
| Cross-document | Both | "How does my dining spend compare Q4 vs Q1?" |

Your agentic RAG agent (Phase 4) will learn to pick the right tool.
For now, we build both storage backends.

---

## Step 1: Build the Transaction Data Model (~20 min)

This is your single source of truth — every parser must output this format.

### Use Claude Code for this step:

Open Claude Code in your project and prompt:

```
Create src/models/transaction.py with Pydantic models for financial transactions.

Requirements:
- Transaction model with fields: date (date), description (str),
  amount (float, negative=expense, positive=income), category (optional str),
  account_type (str: chequing/credit/mortgage), source_file (str),
  raw_description (str for original text before cleanup)
- TransactionSet model: list of transactions + metadata (source, period,
  account_name, institution)
- Add a method to export TransactionSet to pandas DataFrame
- Add validation: amount cannot be 0, date must be reasonable (2020-2030)
- Add an enum for Category with values: HOUSING, GROCERIES, DINING,
  TRANSPORTATION, UTILITIES, SUBSCRIPTIONS, SHOPPING, TRAVEL, INCOME,
  TRANSFER, OTHER, UNCATEGORIZED

Use type hints everywhere. Add docstrings.
```

**Review what Claude Code generates.** Key things to check:
- Does the Transaction model normalize amounts correctly? (debits negative, credits positive)
- Does the DataFrame export include all fields?
- Are the validators sensible?

This is your first real experience of the Claude Code workflow: prompt → review → iterate.

---

## Step 2: Build CSV Parser (~30 min)

### Prompt Claude Code:

```
Create src/parsers/csv_parser.py that parses Canadian bank CSV exports
into TransactionSet objects.

Requirements:
- Function: parse_rbc_chequing(filepath: str) -> TransactionSet
  - RBC CSV format: Date, Description, Debit, Credit, Balance
  - Normalize: Debit values become negative amounts, Credit become positive
  - Handle empty Debit/Credit cells gracefully

- Function: parse_visa_statement(filepath: str) -> TransactionSet
  - Visa CSV format: TransactionDate, PostingDate, Description, Amount, Category
  - Amount is already signed (negative = charge, positive = payment/credit)

- Function: parse_mortgage(filepath: str) -> TransactionSet
  - Mortgage CSV: PaymentNumber, Date, Payment, Principal, Interest, Balance
  - Each row becomes a transaction with amount = -Payment

- Auto-detection function: parse_csv(filepath: str) -> TransactionSet
  - Reads first few lines, detects format by column headers
  - Routes to the correct parser

- All parsers should:
  - Strip whitespace from descriptions
  - Parse dates into datetime.date objects
  - Skip header rows and empty rows
  - Print status: "Parsed {n} transactions from {file}"

Test it by running:
  python -m src.parsers.csv_parser data/mock/rbc_chequing_2025.csv

Include a __main__ block that parses all mock CSVs and prints summary stats.
```

### What to learn from this step:

After Claude Code generates the parser, **manually run it** and inspect the output:

```powershell
python -m src.parsers.csv_parser data/mock/rbc_chequing_2025.csv
```

Look at the output. Ask yourself:
- Did it parse all rows?
- Are amounts correctly signed?
- Are dates in the right format?

If something's wrong, tell Claude Code what failed and let it fix it. This
debug loop (run → inspect → fix) is the core Claude Code workflow.

---

## Step 3: Build PDF Parser (~30 min)

PDF parsing is messier than CSV. This is where you'll feel the difference
between structured and unstructured data.

### Prompt Claude Code:

```
Create src/parsers/pdf_parser.py that extracts transactions from
PDF credit card statements.

Requirements:
- Use pypdf to extract raw text from each page
- Use an LLM (Ollama via langchain-ollama) to parse the extracted text
  into structured transactions. This is the "LLM-as-parser" pattern.

Approach:
1. Extract raw text from PDF using pypdf
2. Send the raw text to the LLM with a prompt like:
   "Extract all transactions from this credit card statement text.
    Return as JSON array with fields: date, description, amount.
    Only include actual transactions, not headers or summaries."
3. Parse the LLM JSON response into Transaction objects
4. Wrap in TransactionSet

Include two modes:
- parse_pdf_with_llm(filepath, llm_provider="ollama") — uses LLM for parsing
- parse_pdf_regex(filepath) — regex fallback for simple tabular PDFs

The LLM approach should:
- Use ChatOllama with model="llama3.2" by default
- Fall back to regex if LLM parsing fails
- Validate extracted transactions (reasonable dates, non-zero amounts)

Add a __main__ block to test:
  python -m src.parsers.pdf_parser data/mock/visa_statement_mar2026.pdf

Print both the raw extracted text AND the parsed transactions so I can
compare and validate.
```

### Key learning moment:

This step teaches you the **LLM-as-parser pattern** — instead of writing
brittle regex rules for every bank's PDF format, you extract raw text and
let the LLM understand the structure. This is essentially what that Medium
article "Stop Writing Bank Statement Parsers" advocates. The tradeoff is
speed (LLM is slower) vs flexibility (handles any format).

Run it and compare:
```powershell
python -m src.parsers.pdf_parser data/mock/visa_statement_mar2026.pdf
```

You should see the raw text dump first, then the structured output. If the
LLM misparses something, iterate with Claude Code to improve the prompt.

---

## Step 4: Build ChromaDB Vector Store (~40 min)

Now we embed parsed transactions into ChromaDB for semantic search.

### Prompt Claude Code:

```
Create src/embeddings/store.py that manages ChromaDB vector storage
for financial transactions.

Requirements:
- Class: FinanceVectorStore
  - __init__(persist_dir: str, embedding_model: str = "nomic-embed-text")
  - Uses Ollama embeddings (OllamaEmbeddings from langchain-ollama)
  - Creates/loads a persistent ChromaDB collection called "transactions"

  - ingest_transactions(transaction_set: TransactionSet):
    - Creates a text representation of each transaction for embedding:
      "{date} | {description} | ${amount} | {category} | {account_type}"
    - Stores metadata: date, amount, category, account_type, source_file
    - Uses ChromaDB's add() with IDs based on source_file + index
    - Prints: "Ingested {n} transactions into ChromaDB"

  - ingest_from_file(filepath: str):
    - Auto-detects CSV/PDF, parses, then ingests
    - Convenience method combining parsing + embedding

  - search(query: str, n_results: int = 10) -> list:
    - Semantic search on embedded transactions
    - Returns results with metadata and distance scores

  - search_by_date_range(start_date: str, end_date: str) -> list:
    - Filters using ChromaDB metadata filtering on date field

  - search_by_category(category: str, n_results: int = 20) -> list:
    - Metadata filter on category field

  - get_stats() -> dict:
    - Returns collection count, date range, unique sources

Also create a separate SQLite storage option:

- Class: FinanceSQLStore
  - __init__(db_path: str = "data/finance.db")
  - ingest_transactions(transaction_set: TransactionSet):
    - Inserts into a 'transactions' table
  - query(sql: str) -> pd.DataFrame:
    - Runs raw SQL and returns results
  - get_summary(group_by: str = "category", period: str = None):
    - Pre-built aggregation queries

Include a __main__ block that:
1. Parses all mock data files
2. Ingests into both ChromaDB and SQLite
3. Runs a sample vector search: "grocery purchases"
4. Runs a sample SQL query: total spending by category
5. Prints both results for comparison
```

### Run and validate:

```powershell
# Make sure Ollama is running first
ollama serve

# In another terminal
python -m src.embeddings.store
```

This should:
1. Parse all your mock CSVs
2. Embed them into ChromaDB (you'll see it downloading the embedding model first time)
3. Store them in SQLite
4. Show you vector search results for "grocery purchases"
5. Show you SQL aggregation results

**Compare the two result types.** Vector search returns semantically similar
transactions (maybe "LOBLAWS", "NO FRILLS", "T&T SUPERMARKET" even though
you searched "grocery"). SQL gives you exact totals. Both are useful —
that's why your agent needs both.

---

## Step 5: Build the Ingestion Pipeline (~20 min)

Tie everything together into a single pipeline script.

### Prompt Claude Code:

```
Create src/pipeline.py that orchestrates the full ingestion pipeline.

Requirements:
- Function: run_ingestion(data_dir: str = "data/mock"):
  1. Scans data_dir for all .csv and .pdf files
  2. Parses each file using the appropriate parser
  3. Ingests into both ChromaDB and SQLite
  4. Prints a summary report:
     - Files processed
     - Total transactions ingested
     - Date range covered
     - Transaction count by source file
     - Transaction count by account type

- Function: run_demo_queries():
  1. Vector search: "dining out expenses"
  2. Vector search: "large purchases over 500 dollars"
  3. SQL query: "SELECT category, SUM(amount) as total, COUNT(*) as count
     FROM transactions GROUP BY category ORDER BY total"
  4. SQL query: "SELECT strftime('%Y-%m', date) as month, SUM(amount) as total
     FROM transactions GROUP BY month ORDER BY month"
  5. Print all results clearly formatted

Add a __main__ block that runs both functions.
Also add CLI arguments:
  --data-dir: path to data directory (default: data/mock)
  --reset: clear existing ChromaDB and SQLite before ingesting
  --query-only: skip ingestion, just run demo queries
```

### Run the full pipeline:

```powershell
# Full run
python -m src.pipeline

# Query only (after initial ingestion)
python -m src.pipeline --query-only

# Reset and re-ingest
python -m src.pipeline --reset
```

---

## Step 6: Validate with Spot Checks (~20 min)

Before moving to Phase 3, manually verify your pipeline works correctly.

### Create a quick test script:

```
Create tests/test_pipeline.py with validation checks:

1. Parse a known CSV, verify transaction count matches expected
2. Verify all amounts are non-zero
3. Verify date range is within expected bounds
4. Ingest into ChromaDB, verify collection count matches
5. Search for "Loblaws" — verify results contain grocery transactions
6. SQL query total transactions — verify count matches ChromaDB count
7. Verify no duplicate transactions in either store

Use assert statements. Print PASS/FAIL for each check.
Run with: python -m tests.test_pipeline
```

Run it:
```powershell
python -m tests.test_pipeline
```

All checks should pass. If something fails, debug with Claude Code.

---

## Phase 2 Checklist

- [ ] Transaction Pydantic model created with validation
- [ ] CSV parser working for all 3 mock formats (RBC, Visa, Mortgage)
- [ ] PDF parser working with LLM-as-parser approach
- [ ] ChromaDB vector store ingesting and searching correctly
- [ ] SQLite store ingesting and querying correctly
- [ ] Pipeline script orchestrating full ingestion
- [ ] Demo queries returning sensible results
- [ ] Validation tests passing
- [ ] Both vector search and SQL returning complementary results

---

## What You've Learned in Phase 2

1. **Document parsing strategies** — CSV (structured) vs PDF (unstructured),
   and when to use regex vs LLM-as-parser
2. **Embedding pipeline** — text → embedding → vector store → semantic search
3. **Dual retrieval architecture** — vector search for semantic queries,
   SQL for exact numerical queries. This is the foundation of agentic RAG.
4. **ChromaDB basics** — persistent collections, metadata filtering,
   similarity search with distance scores
5. **Pydantic data models** — enforcing schema consistency across different
   input formats
6. **Claude Code iteration** — prompt → generate → run → debug → iterate

---

## Common Issues & Fixes

**Ollama embedding hangs or is slow**
- First run downloads the model (~270MB for nomic-embed-text). Wait for it.
- If it hangs, check `ollama serve` is running. Try `ollama pull nomic-embed-text` again.

**ChromaDB "collection already exists" error**
- Use `get_or_create_collection()` instead of `create_collection()`
- Or use the `--reset` flag to clear and re-ingest

**PDF text extraction returns garbled text**
- Some PDFs use non-standard encodings. Try pdfplumber as an alternative:
  `pip install pdfplumber` and ask Claude Code to add a pdfplumber fallback.

**LLM parser returns invalid JSON**
- Add retry logic with a "fix this JSON" prompt
- Or constrain output format with a Pydantic output parser from LangChain

**SQLite "table already exists"**
- Use `CREATE TABLE IF NOT EXISTS` in your schema creation
- Or add a reset/drop-and-recreate option

---

## Next: Phase 3 — Skills Architecture

In Phase 3, you'll flesh out your SKILL.md files with real logic and
learn how skills integrate with the agent's decision-making process.
This is where the "context engineering" happens.

Ask me to generate Phase 3 when ready.
