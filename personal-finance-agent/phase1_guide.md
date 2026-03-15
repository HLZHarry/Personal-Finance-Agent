# Phase 1: Foundation Setup (~3 hours)
## Personal Finance Agent — Learning Project

---

## Prerequisites & Environment Checklist

### Hardware Requirements
- **Machine**: Your Windows laptop is fine. No GPU required for this project.
- **RAM**: 16GB+ recommended (Ollama models need ~5-8GB for a 7B model)
- **Disk**: ~15GB free (Ollama models + project + ChromaDB data)

### What You're Installing (and Why)

| Tool | Purpose | Install Method |
|------|---------|---------------|
| **Python 3.11+** | Core language for the agent pipeline | python.org or `winget` |
| **Node.js 18+** | Required for Claude Code (native installer) | nodejs.org |
| **Git for Windows** | Required by Claude Code on Windows | git-scm.com |
| **Claude Code** | Your AI coding partner — builds the project WITH you | PowerShell one-liner |
| **VS Code** | IDE with terminal integration | code.visualstudio.com |
| **Ollama** | Run local LLMs (privacy-first option) | ollama.com |
| **Claude Pro/Max** | API access for Claude Code + Claude API comparison | claude.ai subscription |

### Python Libraries (installed later via requirements.txt)

| Library | Purpose |
|---------|---------|
| `langchain` | Core framework for LLM orchestration |
| `langgraph` | Stateful agent graph (agentic RAG) |
| `langchain-anthropic` | Claude API integration |
| `langchain-ollama` | Ollama local LLM integration |
| `langchain-community` | Document loaders, vector stores |
| `chromadb` | Local vector database |
| `sentence-transformers` | Local embedding model (no API needed) |
| `pypdf` | PDF parsing for bank statements |
| `pandas` | Transaction data manipulation |
| `tabulate` | Pretty-print tables in terminal |
| `python-dotenv` | Environment variable management |
| `pydantic` | Data validation for transaction schemas |

---

## Step-by-Step Setup

### Step 1: Install Core Tools (~30 min)

#### 1a. Python 3.11+
```powershell
# Check if already installed
python --version

# If not installed, use winget (or download from python.org)
winget install Python.Python.3.12
```
After install, **close and reopen** your terminal.

#### 1b. Node.js 18+
```powershell
# Check if already installed
node --version

# If not installed
winget install OpenJS.NodeJS.LTS
```

#### 1c. Git for Windows
```powershell
# Check if already installed
git --version

# If not installed
winget install Git.Git
```
Use default options during install. Make sure "Add to PATH" is selected.

#### 1d. VS Code
```powershell
winget install Microsoft.VisualStudioCode
```
Recommended extensions:
- Python (Microsoft)
- Pylance
- GitLens

#### 1e. Claude Code
```powershell
# Native installer for Windows (recommended, no Node.js dependency)
irm https://claude.ai/install.ps1 | iex
```
After install, run `claude` in your terminal. It will prompt you to authenticate via browser with your Claude Pro/Max account.

Run `/init` inside Claude Code to generate a CLAUDE.md for your project.

#### 1f. Ollama
Download from https://ollama.com/download — run the Windows installer.

```powershell
# After install, pull models
ollama pull llama3.2        # 3B param chat model (~2GB) — lightweight
ollama pull nomic-embed-text # embedding model for vector search

# Verify it's running
ollama list
```

> **Note on model choice**: `llama3.2` (3B) is fast and fits easily in RAM.
> If you have 16GB+ RAM and want better quality, try `llama3.1:8b` (~5GB).
> You can always swap models later — the code is model-agnostic.

---

### Step 2: Create Project Structure (~15 min)

```powershell
# Create project directory
mkdir finance-agent
cd finance-agent

# Initialize git repo
git init

# Create Python virtual environment
python -m venv .venv

# Activate it
.venv\Scripts\activate    # Windows PowerShell
# or
source .venv/bin/activate  # Git Bash / WSL
```

#### Create the directory structure:
```
finance-agent/
├── .venv/                    # Python virtual environment
├── .claude/                  # Claude Code config (auto-generated)
├── CLAUDE.md                 # Project context for Claude Code
├── requirements.txt          # Python dependencies
├── .env                      # API keys (never commit this)
├── .gitignore
│
├── data/
│   ├── mock/                 # Synthetic bank statements
│   │   ├── rbc_chequing_2025.csv
│   │   ├── visa_statement_jan2026.pdf
│   │   ├── visa_statement_feb2026.pdf
│   │   └── mortgage_amortization.csv
│   ├── real/                 # Your actual statements (gitignored)
│   └── processed/            # Parsed & chunked output
│
├── skills/                   # SKILL.md files for the agent
│   ├── statement-parser/
│   │   └── SKILL.md
│   ├── transaction-categorizer/
│   │   └── SKILL.md
│   ├── spend-analyzer/
│   │   └── SKILL.md
│   └── cashflow-forecaster/
│       └── SKILL.md
│
├── src/
│   ├── __init__.py
│   ├── parsers/              # Document parsing logic
│   │   ├── __init__.py
│   │   ├── csv_parser.py     # Bank CSV parsing
│   │   └── pdf_parser.py     # PDF statement parsing
│   ├── embeddings/           # Vector store operations
│   │   ├── __init__.py
│   │   └── store.py          # ChromaDB ingestion & retrieval
│   ├── agents/               # LangGraph agent definitions
│   │   ├── __init__.py
│   │   ├── finance_agent.py  # Main agentic RAG agent
│   │   └── tools.py          # Agent tools (search, analyze, etc.)
│   └── models/               # Data models
│       ├── __init__.py
│       └── transaction.py    # Pydantic transaction schema
│
├── tests/                    # Validation scripts
│   └── test_pipeline.py
│
└── notebooks/                # Optional: Jupyter for exploration
    └── explore.ipynb
```

#### Create the structure with one command:
```powershell
# Run this from your finance-agent/ root
mkdir -p data/mock data/real data/processed
mkdir -p skills/statement-parser skills/transaction-categorizer
mkdir -p skills/spend-analyzer skills/cashflow-forecaster
mkdir -p src/parsers src/embeddings src/agents src/models
mkdir -p tests notebooks
```

---

### Step 3: Create Config Files (~15 min)

#### requirements.txt
```
# Core framework
langchain>=0.3.0
langgraph>=0.2.0
langchain-core>=0.3.0
langchain-community>=0.3.0

# LLM providers
langchain-anthropic>=0.3.0
langchain-ollama>=0.3.0

# Vector store
chromadb>=0.5.0

# Embeddings (local, no API needed)
sentence-transformers>=3.0.0

# Document parsing
pypdf>=4.0.0
pandas>=2.0.0

# Utilities
python-dotenv>=1.0.0
pydantic>=2.0.0
tabulate>=0.9.0
```

Install:
```powershell
pip install -r requirements.txt
```

> **Heads up**: `sentence-transformers` pulls in PyTorch (~2GB). This is a one-time download.
> If you want a lighter alternative, you can use Ollama's `nomic-embed-text` for embeddings instead.

#### .env
```bash
# Claude API key (get from console.anthropic.com)
ANTHROPIC_API_KEY=sk-ant-xxxxx

# Ollama (default local endpoint)
OLLAMA_BASE_URL=http://localhost:11434

# ChromaDB
CHROMA_PERSIST_DIR=./data/chroma_db

# Which LLM to use by default: "claude" or "ollama"
DEFAULT_LLM=ollama
```

#### .gitignore
```
.venv/
.env
data/real/
data/chroma_db/
__pycache__/
*.pyc
.DS_Store
```

#### CLAUDE.md (project context for Claude Code)
```markdown
# Personal Finance Agent

## Project Overview
A local-first personal finance assistant that uses agentic RAG to analyze
bank statements, credit card statements, and mortgage documents. Built as
a learning project to understand agentic RAG, SKILL.md architecture, and
LangGraph.

## Tech Stack
- Python 3.12, LangGraph, LangChain
- ChromaDB (local vector store)
- Ollama (local LLM) + Claude API (cloud LLM) — dual provider for comparison
- SKILL.md files for modular agent capabilities

## Project Structure
- `src/parsers/` — PDF and CSV parsers for different bank formats
- `src/embeddings/` — ChromaDB vector store operations
- `src/agents/` — LangGraph agent with agentic RAG
- `src/models/` — Pydantic transaction models
- `skills/` — SKILL.md files defining agent capabilities
- `data/mock/` — synthetic bank data for development
- `data/real/` — real statements (gitignored, never committed)

## Coding Conventions
- Use type hints everywhere
- Pydantic models for all data structures
- Keep functions small and testable
- Use python-dotenv for config, never hardcode API keys
- Print clear status messages during pipeline steps

## Key Commands
- `python -m src.parsers.csv_parser` — test CSV parsing
- `python -m src.agents.finance_agent` — run the agent
- `ollama serve` — start local LLM server
```

---

### Step 4: Generate Mock Bank Data (~45 min)

This is where Claude Code earns its keep. You'll use it to generate realistic synthetic data.

#### 4a. Start Claude Code in your project
```powershell
cd finance-agent
claude
```

#### 4b. Prompt Claude Code to generate mock data

Copy-paste this prompt into Claude Code:

```
Generate realistic mock financial data for a Toronto-based professional.
Create the following files in data/mock/:

1. rbc_chequing_2025.csv — 12 months of chequing account transactions
   - Columns: Date, Description, Debit, Credit, Balance
   - Include: salary deposits ($6,500 bi-weekly), rent/mortgage ($2,800/mo),
     groceries (various stores like Loblaws, No Frills, T&T), dining out,
     utilities (Enbridge, Toronto Hydro), subscriptions (Netflix, Spotify),
     transit (Presto), gas stations, Amazon purchases, e-transfers
   - ~30-50 transactions per month
   - Realistic Canadian merchant names

2. visa_statement_jan2026.csv — January 2026 credit card statement
   - Columns: TransactionDate, PostingDate, Description, Amount, Category
   - Include dining, shopping, travel (flights on Air Canada),
     online purchases, gas, phone bill (Rogers/Bell)
   - ~25 transactions

3. visa_statement_feb2026.csv — February 2026 credit card statement
   - Same format, different transactions
   - Show seasonal spending differences (less travel, more indoor activities)

4. mortgage_amortization.csv — Simplified mortgage schedule
   - Columns: PaymentNumber, Date, Payment, Principal, Interest, Balance
   - 25-year amortization, $550,000 principal, 4.5% rate
   - Show first 24 payments (2 years)

Make the data internally consistent (balances should be calculated correctly).
Use realistic amounts in CAD.
```

Claude Code will generate all four files. **Review them** — check that balances make sense and the data looks realistic.

#### 4c. Create a mock PDF statement (optional but recommended)

Prompt Claude Code:
```
Create a Python script at scripts/generate_mock_pdf.py that generates
a realistic-looking credit card statement PDF for March 2026.
Use reportlab library. The PDF should look like a typical Visa statement with:
- Header with bank name and logo placeholder
- Account summary (previous balance, payments, new charges, new balance)
- Transaction table with dates, descriptions, amounts
- Footer with minimum payment info
Save to data/mock/visa_statement_mar2026.pdf
```

This teaches you what PDF parsing will need to handle in Phase 2.

---

### Step 5: Create Initial SKILL.md Files (~30 min)

Create skeleton skills that you'll flesh out in Phase 3. This gets you familiar with the format now.

#### skills/statement-parser/SKILL.md
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
```

## Instructions
1. Detect the file format (CSV vs PDF)
2. Identify the bank/institution from headers or filename
3. Map columns to the standardized schema
4. Normalize amounts (debits as negative, credits as positive)
5. Validate date formats and sort chronologically
```

#### skills/transaction-categorizer/SKILL.md
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

#### skills/spend-analyzer/SKILL.md
```markdown
---
name: spend-analyzer
description: >
  Analyze spending patterns across time periods. Compares month-over-month,
  identifies top categories, and flags unusual transactions.
  Use when the user asks about spending trends or comparisons.
---

# Spend analyzer

## When to use
- "What did I spend last month?"
- "Compare my spending January vs February"
- "What are my top spending categories?"
- "Show me unusual or large transactions"

## Instructions
1. Aggregate transactions by category and time period
2. Calculate totals, averages, and percentages
3. Compare across requested periods
4. Flag transactions that are significantly above average for their category
5. Present results in a clear summary format
```

#### skills/cashflow-forecaster/SKILL.md
```markdown
---
name: cashflow-forecaster
description: >
  Project future cash flow based on historical income and spending patterns.
  Identifies recurring charges and predicts upcoming balances.
  Use when the user asks about future finances or projections.
---

# Cash flow forecaster

## When to use
- "What will my balance look like next month?"
- "Can I afford X given my current spending?"
- "What are my recurring monthly expenses?"

## Instructions
1. Identify recurring transactions (same amount ±5%, same merchant, regular interval)
2. Calculate average monthly income and expenses
3. Project forward based on identified patterns
4. Flag upcoming large known expenses (mortgage, insurance renewals)
5. Present a simple month-ahead projection
```

---

### Step 6: Verify Everything Works (~15 min)

#### Verify Python environment
```powershell
python -c "
import langchain
import langgraph
import chromadb
import pandas as pd
print('langchain:', langchain.__version__)
print('langgraph:', langgraph.__version__)
print('chromadb:', chromadb.__version__)
print('pandas:', pd.__version__)
print('All imports successful!')
"
```

#### Verify Ollama
```powershell
# Make sure Ollama is running
ollama list
# Should show llama3.2 and nomic-embed-text

# Quick test
ollama run llama3.2 "Say hello in 5 words"
```

#### Verify Claude Code
```powershell
cd finance-agent
claude
# Type: "Read my CLAUDE.md and confirm you understand the project"
# Claude Code should summarize your project back to you
```

#### Verify Claude API
```python
python -c "
from dotenv import load_dotenv
load_dotenv()
from langchain_anthropic import ChatAnthropic
llm = ChatAnthropic(model='claude-sonnet-4-20250514')
response = llm.invoke('Say hello in 5 words')
print(response.content)
print('Claude API working!')
"
```

#### Verify mock data
```python
python -c "
import pandas as pd
df = pd.read_csv('data/mock/rbc_chequing_2025.csv')
print(f'Loaded {len(df)} transactions')
print(f'Date range: {df.Date.min()} to {df.Date.max()}')
print(f'Columns: {list(df.columns)}')
print(df.head())
"
```

---

## Phase 1 Checklist

- [ ] Python 3.11+ installed and working
- [ ] Node.js 18+ installed
- [ ] Git for Windows installed
- [ ] VS Code installed with Python extension
- [ ] Claude Code installed and authenticated
- [ ] Ollama installed with llama3.2 and nomic-embed-text pulled
- [ ] Project directory created with full structure
- [ ] Virtual environment created and activated
- [ ] All Python packages installed via requirements.txt
- [ ] .env file created with API key
- [ ] CLAUDE.md written with project context
- [ ] Mock data generated (4 CSV/PDF files)
- [ ] Skeleton SKILL.md files created (4 skills)
- [ ] All verification checks passing

---

## What You've Learned in Phase 1

1. **Claude Code workflow** — using `/init`, CLAUDE.md, and natural language to scaffold a project
2. **SKILL.md format** — the structure of a skill file (frontmatter + instructions)
3. **Project architecture** — how to organize an agentic RAG project
4. **Dual LLM setup** — Ollama for local/private, Claude API for quality comparison
5. **Mock data strategy** — building with synthetic data before touching real statements

---

## Next: Phase 2 — Document Parsing Pipeline

In Phase 2, you'll build the parsers that turn raw bank statements into structured
transaction data and ingest them into ChromaDB. Ask me to generate Phase 2 when ready.
