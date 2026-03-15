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