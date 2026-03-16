"""
src/agents/nodes.py

LangGraph node functions for the personal finance agent.

Each node is a plain Python function that accepts the full AgentState and
returns a dict with only the fields it writes.  LangGraph merges the return
value into the state — untouched fields are preserved automatically.

Node overview
-------------
route_question      LLM selects the right skill and retrieval strategy.
load_skill          Loads the full SKILL.md for the selected skill.
retrieve_vector     Semantic search via ChromaDB.
retrieve_sql        Structured query via SQLite.
retrieve_both       Runs vector + SQL in sequence and merges results.
grade_retrieval     LLM scores how relevant the retrieved content is.
rewrite_question    Rewrites the query when retrieval scored poorly.
generate_answer     Synthesises all context into a final answer.

LLM helper
----------
get_llm(provider)   Returns the configured LLM instance.  Reads DEFAULT_LLM
                    from .env when provider is None.
"""

from __future__ import annotations

import os
from typing import Literal

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from src.agents.state import FinanceAgentState
from src.skills.registry import discover_skills, format_skill_context, load_skill as _load_skill_text

load_dotenv()

# ---------------------------------------------------------------------------
# LLM provider helper
# ---------------------------------------------------------------------------

def get_llm(provider: str | None = None):
    """
    Return a configured LLM instance.

    Parameters
    ----------
    provider:
        ``"ollama"``  — ChatOllama(model="llama3.2"), local inference.
        ``"claude"``  — ChatAnthropic(model="claude-sonnet-4-20250514").
        ``None``      — reads ``DEFAULT_LLM`` from .env (default "ollama").

    The function imports lazily so the module can be imported without both
    providers being installed.
    """
    resolved = (provider or os.getenv("DEFAULT_LLM", "ollama")).lower()

    if resolved == "claude":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model="claude-sonnet-4-20250514",
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            max_tokens=4096,
        )

    # Default: Ollama (local)
    from langchain_ollama import ChatOllama
    return ChatOllama(
        model="llama3.2",
        base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        temperature=0,
    )


# ---------------------------------------------------------------------------
# Structured output schemas (Pydantic V2)
# ---------------------------------------------------------------------------

class _RouteDecision(BaseModel):
    """Router output: skill selection + retrieval strategy."""

    skill: Literal[
        "statement-parser",
        "transaction-categorizer",
        "spend-analyzer",
        "cashflow-forecaster",
        "none",
    ] = Field(
        description=(
            "The skill best suited to answer the question. "
            "Use 'none' only if no skill applies."
        )
    )
    strategy: Literal["vector", "sql", "both", "none"] = Field(
        description=(
            "Retrieval strategy: "
            "'sql' for exact numbers/totals/comparisons, "
            "'vector' for semantic/description search, "
            "'both' when both types of context are needed, "
            "'none' when retrieval is not required."
        )
    )
    reasoning: str = Field(
        description="One sentence explaining why this skill and strategy were chosen."
    )


class _RelevanceScore(BaseModel):
    """Grader output: relevance of retrieved content."""

    score: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "How relevant the retrieved content is to the question. "
            "1.0 = highly relevant and sufficient to answer. "
            "0.5 = partially relevant. "
            "0.0 = irrelevant or empty."
        ),
    )
    reason: str = Field(description="One sentence justifying the score.")


class _SqlParams(BaseModel):
    """SQL node output: extracted query parameters."""

    query_type: Literal[
        "period_summary",
        "category_breakdown",
        "top_expenses",
        "monthly_trend",
        "category_comparison",
    ] = Field(description="The SQL query type that best answers the question.")
    start_date: str = Field(default="", description="ISO date YYYY-MM-DD or YYYY-MM period, or empty.")
    end_date: str   = Field(default="", description="ISO date YYYY-MM-DD or YYYY-MM period, or empty.")
    category: str   = Field(default="", description="Uppercase category name, or empty.")


# ---------------------------------------------------------------------------
# Shared prompt snippets
# ---------------------------------------------------------------------------

_SKILL_CONTEXT_HEADER = """You are a personal finance assistant for a Canadian bank customer.
The user's transaction data is stored in SQLite (exact queries) and ChromaDB (semantic search).
Today's date: {today}.

{skill_context}"""


def _today() -> str:
    from datetime import date
    return str(date.today())


def _active_question(state: FinanceAgentState) -> str:
    """Return the rewritten question if available, else the original."""
    return state.get("rewritten_question") or state["question"]


# ---------------------------------------------------------------------------
# Node 1 — Router
# ---------------------------------------------------------------------------

def route_question(state: FinanceAgentState) -> dict:
    """
    Select the most appropriate skill and retrieval strategy for the question.

    Uses structured output to force the LLM to return a well-typed decision
    rather than free text.  The full skill registry descriptions are included
    in the prompt so the model can distinguish between skills.

    Returns
    -------
    {"selected_skill": str, "retrieval_strategy": str}
    """
    question = state["question"]
    skills   = discover_skills()
    skill_context = format_skill_context(skills)

    system = (
        "You are a router for a personal finance assistant.\n"
        "Given a user question, choose the correct skill and retrieval strategy.\n\n"
        f"{skill_context}\n\n"
        "Retrieval strategy rules:\n"
        "  sql    — user wants totals, averages, counts, percentages, or period comparisons\n"
        "  vector — user asks about specific transaction descriptions or unusual charges\n"
        "  both   — question needs both exact numbers AND semantic context\n"
        "  none   — skill can answer directly (e.g. 'parse this file')\n"
    )

    llm      = get_llm()
    router   = llm.with_structured_output(_RouteDecision)
    decision: _RouteDecision = router.invoke([
        SystemMessage(content=system),
        HumanMessage(content=f"Question: {question}"),
    ])

    return {
        "selected_skill":    decision.skill,
        "retrieval_strategy": decision.strategy,
    }


# ---------------------------------------------------------------------------
# Node 2 — Skill loader
# ---------------------------------------------------------------------------

def load_skill(state: FinanceAgentState) -> dict:
    """
    Load the full SKILL.md body for the selected skill.

    If no skill was selected (or loading fails), skill_context is set to an
    empty string so downstream nodes degrade gracefully.

    Returns
    -------
    {"skill_context": str}
    """
    skill_name = state.get("selected_skill", "")
    if not skill_name or skill_name == "none":
        return {"skill_context": ""}

    try:
        text = _load_skill_text(skill_name)
    except ValueError:
        text = ""

    return {"skill_context": text}


# ---------------------------------------------------------------------------
# Node 3 — Vector retriever
# ---------------------------------------------------------------------------

def retrieve_vector(state: FinanceAgentState) -> dict:
    """
    Semantic search over ChromaDB using the active question.

    Returns
    -------
    {"retrieved_docs": list[str]}
    """
    from src.agents.tools import vector_search

    query  = _active_question(state)
    result = vector_search.invoke({"query": query, "n_results": 10})

    # Wrap in a list; the grader and generator iterate over retrieved_docs
    return {"retrieved_docs": [result]}


# ---------------------------------------------------------------------------
# Node 4 — SQL retriever
# ---------------------------------------------------------------------------

_VALID_CATEGORIES = {
    "GROCERIES", "DINING", "TRANSPORTATION", "UTILITIES",
    "SUBSCRIPTIONS", "SHOPPING", "TRAVEL", "HOUSING",
    "INCOME", "TRANSFER", "OTHER", "UNCATEGORIZED",
}


def retrieve_sql(state: FinanceAgentState) -> dict:
    """
    Extract SQL parameters from the question using the LLM, then run the query.

    The LLM maps free-text questions to one of five query_type values so we
    never pass un-validated SQL to the database.

    Returns
    -------
    {"sql_results": str}
    """
    from src.agents.tools import sql_query

    question = _active_question(state)
    today    = _today()

    system = (
        f"Today's date is {today}. "
        "Extract structured SQL query parameters from the user's financial question.\n\n"
        "query_type options:\n"
        "  period_summary      — category totals for a date range; needs YYYY-MM-DD dates\n"
        "  category_breakdown  — all transactions in one category; needs category + dates\n"
        "  top_expenses        — largest expense transactions; dates optional\n"
        "  monthly_trend       — month-by-month totals; category optional\n"
        "  category_comparison — compare two months side-by-side; use YYYY-MM for both dates\n\n"
        "Date rules: convert relative terms to absolute dates.\n"
        "  'last month'  → first and last day of the previous calendar month\n"
        "  'this year'   → Jan 1 of the current year to today\n"
        "  'January 2025' → 2025-01-01 and 2025-01-31\n"
        "  no period given → leave start_date and end_date empty\n\n"
        "Category: use UPPERCASE. Valid values: "
        "GROCERIES, DINING, TRANSPORTATION, UTILITIES, SUBSCRIPTIONS, "
        "SHOPPING, TRAVEL, HOUSING, INCOME, TRANSFER, OTHER. "
        "Leave empty if the user did not name a specific category."
    )

    llm       = get_llm()
    extractor = llm.with_structured_output(_SqlParams)
    params: _SqlParams = extractor.invoke([
        SystemMessage(content=system),
        HumanMessage(content=question),
    ])

    # Normalize category: reject anything not in the known set
    raw_cat = params.category.strip().upper()
    category = raw_cat if raw_cat in _VALID_CATEGORIES else ""

    result = sql_query.invoke({
        "query_type": params.query_type,
        "start_date": params.start_date,
        "end_date":   params.end_date,
        "category":   category,
    })

    return {"sql_results": result}


# ---------------------------------------------------------------------------
# Node 5 — Both retrievers
# ---------------------------------------------------------------------------

def retrieve_both(state: FinanceAgentState) -> dict:
    """
    Run vector search and SQL query in sequence and merge the results.

    Returns
    -------
    {"retrieved_docs": list[str], "sql_results": str}
    """
    vector_update = retrieve_vector(state)
    sql_update    = retrieve_sql(state)

    return {
        "retrieved_docs": vector_update["retrieved_docs"],
        "sql_results":    sql_update["sql_results"],
    }


# ---------------------------------------------------------------------------
# Node 6 — Relevance grader
# ---------------------------------------------------------------------------

def grade_retrieval(state: FinanceAgentState) -> dict:
    """
    Score how relevant the retrieved content is to the original question.

    Considers both retrieved_docs (vector) and sql_results (SQL).
    A score below 0.5 signals that rewrite_question should run next.

    Returns
    -------
    {"relevance_score": float}
    """
    question = state["question"]
    docs     = state.get("retrieved_docs") or []
    sql      = state.get("sql_results") or ""

    # If nothing was retrieved, score 0 immediately
    retrieved_content = "\n\n".join(docs).strip()
    if sql.strip():
        retrieved_content = (retrieved_content + "\n\nSQL results:\n" + sql).strip()

    if not retrieved_content:
        return {"relevance_score": 0.0}

    # Truncate to avoid overwhelming the context window
    content_preview = retrieved_content[:3000]

    system = (
        "You are a relevance grader for a financial Q&A system.\n"
        "Score whether the retrieved content is sufficient to answer the question.\n"
        "Be generous: partial matches that contribute useful context score >= 0.5."
    )
    user = (
        f"Question: {question}\n\n"
        f"Retrieved content:\n{content_preview}\n\n"
        "Is this content relevant and sufficient to answer the question?"
    )

    llm    = get_llm()
    grader = llm.with_structured_output(_RelevanceScore)
    result: _RelevanceScore = grader.invoke([
        SystemMessage(content=system),
        HumanMessage(content=user),
    ])

    return {"relevance_score": result.score}


# ---------------------------------------------------------------------------
# Node 7 — Query rewriter
# ---------------------------------------------------------------------------

def rewrite_question(state: FinanceAgentState) -> dict:
    """
    Rewrite the question to improve retrieval on the next attempt.

    Called when grade_retrieval returns a score below the threshold.
    Increments retry_count so the graph knows when to stop retrying.

    Returns
    -------
    {"rewritten_question": str, "retry_count": int}
    """
    original  = state["question"]
    previous  = state.get("rewritten_question") or ""
    docs      = "\n".join((state.get("retrieved_docs") or []))[:1000]
    sql       = (state.get("sql_results") or "")[:500]
    retrieved_summary = (docs + "\n" + sql).strip() or "(nothing retrieved)"

    system = (
        "You are a query rewriter for a financial assistant.\n"
        "The first retrieval attempt returned poor results.\n"
        "Rewrite the question to:\n"
        "  1. Use more specific financial terminology\n"
        "  2. Spell out date ranges explicitly (e.g. 'between 2025-01-01 and 2025-01-31')\n"
        "  3. Name specific categories if implied (GROCERIES, DINING, etc.)\n"
        "Return only the rewritten question, no explanation."
    )
    user = (
        f"Original question: {original}\n"
        + (f"Previous rewrite: {previous}\n" if previous else "")
        + f"Poor retrieval results:\n{retrieved_summary}"
    )

    llm      = get_llm()
    response = llm.invoke([
        SystemMessage(content=system),
        HumanMessage(content=user),
    ])

    rewritten = response.content.strip()
    return {
        "rewritten_question": rewritten,
        "retry_count":        state.get("retry_count", 0) + 1,
    }


# ---------------------------------------------------------------------------
# Node 8 — Answer generator
# ---------------------------------------------------------------------------

def generate_answer(state: FinanceAgentState) -> dict:
    """
    Synthesise all available context into a final user-facing answer.

    Context priority (highest to lowest):
        1. sql_results  — exact numbers from SQLite
        2. retrieved_docs — semantically matched transactions
        3. skill_context  — SKILL.md formatting instructions

    Returns
    -------
    {"generation": str}
    """
    question     = state["question"]
    skill_ctx    = state.get("skill_context") or ""
    docs         = state.get("retrieved_docs") or []
    sql          = state.get("sql_results") or ""
    skill_name   = state.get("selected_skill") or "general"

    # Build the context block shown to the LLM
    context_parts: list[str] = []

    if sql.strip():
        context_parts.append(f"## SQL Query Results\n{sql}")

    if docs:
        vector_text = "\n".join(d for d in docs if d.strip())
        if vector_text.strip():
            context_parts.append(f"## Semantic Search Results\n{vector_text}")

    context_block = "\n\n".join(context_parts) or "(no retrieved context)"

    # Skill instructions are injected as a guidance section, not a hard constraint
    skill_guidance = ""
    if skill_ctx.strip():
        # Include only up to 2000 chars of skill instructions to save context
        skill_guidance = (
            f"\n## Skill Instructions ({skill_name})\n"
            + skill_ctx[:2000]
            + ("\n[instructions truncated]" if len(skill_ctx) > 2000 else "")
        )

    system = _SKILL_CONTEXT_HEADER.format(
        today=_today(),
        skill_context=skill_guidance,
    ).strip()

    user = (
        f"## Retrieved Context\n{context_block}\n\n"
        f"## User Question\n{question}\n\n"
        "Answer the question using the retrieved context above.  "
        "Be specific: include dollar amounts, dates, and category names when available.  "
        "If the context is insufficient, say what's missing and suggest next steps."
    )

    llm = get_llm()

    # Build the message list: system prompt + prior conversation history + new user turn.
    # Prior messages are trimmed to the last 10 to avoid overflowing the context window.
    history = list(state.get("messages") or [])
    prior   = history[:-1]   # everything except the just-added HumanMessage for this turn
    recent  = prior[-10:] if len(prior) > 10 else prior

    messages = [SystemMessage(content=system)] + recent + [HumanMessage(content=user)]
    response = llm.invoke(messages)

    answer = response.content.strip()
    return {
        "generation": answer,
        # Append the assistant turn so MemorySaver accumulates the full dialogue.
        "messages":   [AIMessage(content=answer)],
    }
