# Personal Finance Agent

A local-first personal finance assistant built as a hands-on learning project for agentic RAG, SKILL.md architecture, and LangGraph. The agent can parse Canadian bank statements, categorize transactions, analyze spending patterns, and forecast cash flow — all running privately on your machine.

---

## What It Does

- **Parse** RBC chequing CSVs, Visa/Mastercard statements, and mortgage amortization schedules
- **Categorize** transactions using merchant pattern matching + LLM classification
- **Analyze** spending trends and month-over-month comparisons
- **Forecast** upcoming cash flow based on recurring patterns

---

## Tech Stack

| Layer | Tool |
|-------|------|
| Language | Python 3.12 |
| Agent Framework | LangGraph + LangChain |
| Vector Store | ChromaDB (local) |
| Embeddings | sentence-transformers (local, no API needed) |
| LLM (local) | Ollama — llama3.2 |
| LLM (cloud) | Claude API (Anthropic) |
| Document Parsing | pypdf + pandas |
| AI Coding Partner | Claude Code |

The project runs dual LLM providers so you can compare local (Ollama) vs cloud (Claude API) quality side by side.

---

## Project Structure

```
personal-finance-agent/
├── data/
│   ├── mock/          # Synthetic Canadian bank statements (CSV/PDF)
│   ├── real/          # Your actual statements — gitignored
│   └── processed/     # Parsed & chunked output
├── skills/
│   ├── statement-parser/
│   ├── transaction-categorizer/
│   ├── spend-analyzer/
│   └── cashflow-forecaster/
├── src/
│   ├── parsers/       # CSV and PDF parsing logic
│   ├── embeddings/    # ChromaDB ingestion & retrieval
│   ├── agents/        # LangGraph agent + tools
│   └── models/        # Pydantic transaction schema
├── tests/
├── notebooks/
├── CLAUDE.md          # Project context for Claude Code
├── requirements.txt
└── .env               # API keys — never committed
```

---

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+ (for Claude Code)
- [Ollama](https://ollama.com/download) installed

### Setup

```powershell
# Clone the repo
git clone https://github.com/HLZHarry/personal-finance-agent.git
cd personal-finance-agent

# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Pull local models
ollama pull llama3.2
ollama pull nomic-embed-text
```

### Configure API Keys

Create a `.env` file in the project root:

```
ANTHROPIC_API_KEY=sk-ant-xxxxxx
OLLAMA_BASE_URL=http://localhost:11434
CHROMA_PERSIST_DIR=./data/chroma_db
DEFAULT_LLM=ollama
```

Get your Anthropic API key from [console.anthropic.com](https://console.anthropic.com).

### Verify Setup

```powershell
python -c "
import langchain, langgraph, chromadb, pandas as pd
print('langchain:', langchain.__version__)
print('langgraph:', langgraph.__version__)
print('chromadb:', chromadb.__version__)
print('pandas:', pd.__version__)
print('All imports successful!')
"
```

---

## Mock Data

The `data/mock/` folder contains synthetic Canadian financial data for development:

- `rbc_chequing_2025.csv` — 12 months of chequing transactions (~30-50/month)
- `visa_statement_jan2026.csv` — January 2026 Visa statement
- `visa_statement_feb2026.csv` — February 2026 Visa statement
- `mortgage_amortization.csv` — 25-year amortization schedule ($550K @ 4.5%)

---

## Skills (SKILL.md Architecture)

The agent uses modular SKILL.md files that define when and how each capability is invoked:

| Skill | Trigger |
|-------|---------|
| `statement-parser` | User uploads or references a bank statement |
| `transaction-categorizer` | Auto-triggered after parsing; or "what did I spend on X" |
| `spend-analyzer` | "Compare my spending Jan vs Feb", "top categories" |
| `cashflow-forecaster` | "What will my balance look like next month?" |

---

## Roadmap

- [x] Phase 1 — Environment setup, mock data, skeleton skills
- [ ] Phase 2 — Document parsing pipeline (CSV + PDF → ChromaDB)
- [ ] Phase 3 — Agentic RAG with LangGraph
- [ ] Phase 4 — Full skill implementation
- [ ] Phase 5 — CLI interface + real statement support

---

## Notes

- `data/real/` and `.env` are gitignored — never commit real financial data or API keys
- Default LLM is Ollama (local/private). Switch to Claude API by setting `DEFAULT_LLM=claude` in `.env`
- Built and scaffolded using Claude Code with CLAUDE.md project context