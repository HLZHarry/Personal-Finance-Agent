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