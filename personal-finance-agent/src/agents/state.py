"""
src/agents/state.py

LangGraph state definition for the personal finance agent.

The state is a TypedDict that flows through every node in the graph.
Each node reads what it needs and writes only the fields it owns —
nothing is mutated globally.

Field lifecycle
---------------
messages          Populated by the user turn; extended by every assistant
                  response.  Uses add_messages so LangGraph merges updates
                  rather than replacing the whole list.

question          Set once at graph entry from the latest human message.
                  Never modified after that.

rewritten_question
                  Written by the query-rewriter node when the original
                  question needs to be expanded or clarified for better
                  retrieval.  Left as "" if no rewrite is needed.

selected_skill    Written by the router node after it reads the Level 1
                  skill registry descriptions and picks the best skill.
                  One of: "statement-parser", "transaction-categorizer",
                  "spend-analyzer", "cashflow-forecaster", or "" if the
                  router cannot determine a skill.

retrieval_strategy
                  Written by the router or skill node to tell the retriever
                  how to fetch context.
                  "vector"  - semantic search via ChromaDB only
                  "sql"     - structured query via SQLite only
                  "both"    - run both and merge results
                  "none"    - no retrieval needed (skill handles it directly)

retrieved_docs    Written by the retriever node.  Each element is a plain
                  string (document text or formatted row).  The grader node
                  may filter this list before generation.

sql_results       Written by the SQL retriever node as a formatted string
                  (tab-separated rows or a Markdown table).  Kept separate
                  from retrieved_docs so the generator can format them
                  differently.  None when no SQL query was run.

skill_context     Written by the skill-loader node after load_skill() is
                  called for the selected skill.  Contains the full SKILL.md
                  body.  Injected into the system prompt at generation time.

generation        Written by the generator node.  The final answer shown to
                  the user.

relevance_score   Written by the document-grader node.  Float in [0.0, 1.0]
                  representing how relevant the retrieved docs are to the
                  question.  Values below a threshold (e.g. 0.5) trigger a
                  retry cycle.

retry_count       Incremented by the retry controller.  The graph checks
                  this before looping back to retrieval; the hard cap is 2
                  to prevent infinite cycles.
"""

from __future__ import annotations

from typing import Annotated, Optional, TypedDict

from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage


class FinanceAgentState(TypedDict):
    """Complete state for the personal finance LangGraph agent."""

    # ------------------------------------------------------------------
    # Conversation history
    # ------------------------------------------------------------------

    messages: Annotated[list[BaseMessage], add_messages]
    """
    Full conversation history.  ``add_messages`` tells LangGraph to append
    new messages rather than overwrite the list, so the entire thread is
    preserved across turns.
    """

    # ------------------------------------------------------------------
    # Query fields
    # ------------------------------------------------------------------

    question: str
    """
    The user's original question, extracted from the latest human message
    at graph entry.  Immutable for the rest of the run.
    """

    rewritten_question: str
    """
    An expanded or clarified version of ``question`` produced by the
    query-rewriter node.  Used as the retrieval query in place of the
    original when non-empty.  Empty string ("") means no rewrite occurred.
    """

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    selected_skill: str
    """
    The skill name chosen by the router node, e.g. ``"spend-analyzer"``.
    Must match a directory name under ``skills/``.  Empty string if the
    router could not make a decision.
    """

    retrieval_strategy: str
    """
    How the retriever node should fetch supporting context.

    ``"vector"``  — semantic search via ChromaDB (FinanceVectorStore)
    ``"sql"``     — structured query via SQLite (FinanceSQLStore)
    ``"both"``    — run both stores and merge results
    ``"none"``    — no retrieval; the skill operates without RAG context
    """

    # ------------------------------------------------------------------
    # Retrieval outputs
    # ------------------------------------------------------------------

    retrieved_docs: list[str]
    """
    Documents returned by the vector retriever, each as a plain string.
    The grader node may shorten or filter this list before generation.
    """

    sql_results: Optional[str]
    """
    Formatted output from the SQL retriever (e.g. a Markdown table or
    newline-separated rows).  ``None`` when no SQL query was executed.
    Kept separate from ``retrieved_docs`` so the generator can apply
    different formatting to structured vs. semantic results.
    """

    # ------------------------------------------------------------------
    # Skill context
    # ------------------------------------------------------------------

    skill_context: str
    """
    The full SKILL.md body for ``selected_skill``, loaded by the
    skill-loader node via ``load_skill()``.  Injected into the generator's
    system prompt so the model follows the skill's instructions.
    Empty string if no skill was loaded.
    """

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    generation: str
    """
    The agent's final answer, written by the generator node.  This is
    the text returned to the user at the end of the graph run.
    """

    # ------------------------------------------------------------------
    # Quality control
    # ------------------------------------------------------------------

    relevance_score: float
    """
    Relevance of ``retrieved_docs`` to ``question``, scored by the
    grader node.  Range: 0.0 (irrelevant) to 1.0 (highly relevant).
    The retry controller compares this against a threshold (typically
    0.5) to decide whether to re-run retrieval with the rewritten query.
    """

    retry_count: int
    """
    Number of retrieval retries attempted so far.  Incremented by the
    retry-controller node.  The graph enforces a hard cap of 2 to prevent
    infinite loops.
    """


# ---------------------------------------------------------------------------
# Default factory
# ---------------------------------------------------------------------------

def make_initial_state(question: str) -> FinanceAgentState:
    """
    Return a fully-initialised state for a new agent run.

    All fields are set to safe zero-values; the caller only needs to
    supply the user's ``question``.

    Parameters
    ----------
    question:
        The user's raw input string.

    Returns
    -------
    A :class:`FinanceAgentState` dict ready to pass to
    ``graph.invoke()``.
    """
    from langchain_core.messages import HumanMessage

    return FinanceAgentState(
        messages            = [HumanMessage(content=question)],
        question            = question,
        rewritten_question  = "",
        selected_skill      = "",
        retrieval_strategy  = "none",
        retrieved_docs      = [],
        sql_results         = None,
        skill_context       = "",
        generation          = "",
        relevance_score     = 0.0,
        retry_count         = 0,
    )
