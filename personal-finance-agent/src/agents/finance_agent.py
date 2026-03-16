"""
src/agents/finance_agent.py

Full LangGraph agent for the personal finance assistant.

Graph topology
--------------

    START
      │
      ▼
  route_question          ← picks skill + retrieval strategy
      │
      ▼
  load_skill              ← injects SKILL.md instructions into state
      │
      ▼ (route_retrieval)
  ┌───┴──────────────┬───────────────┐
  │                  │               │
  ▼                  ▼               ▼         (strategy == "none")
retrieve_vector  retrieve_sql  retrieve_both ──────────────────────────┐
  │                  │               │                                  │
  └──────────────────┴───────────────┘                                  │
                      │                                                  │
                      ▼                                                  │
              grade_retrieval                                            │
                      │                                                  │
                      ▼ (check_relevance)                                │
              ┌───────┴────────────────┐                                 │
              │                        │                                 │
        (score ≥ 0.5           (score < 0.5                             │
         or retries ≥ 2)        and retries < 2)                        │
              │                        │                                 │
              │               rewrite_question                          │
              │                        │                                 │
              │             (route_retrieval — loop back to retrievers)  │
              │                                                          │
              ▼                                                          │
        generate_answer ◄────────────────────────────────────────────────┘
              │
              ▼
             END

Features
--------
- MemorySaver checkpointer — conversation history persists across turns
  within the same thread_id.
- Streaming execution — every node is printed as it fires (for learning).
- run_agent()       — single-question programmatic interface.
- interactive_mode() — REPL with /quit, /reset, /provider, /debug.
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from collections import Counter
from typing import Literal

from pathlib import Path

from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph

_ROOT = Path(__file__).parent.parent.parent   # …/personal-finance-agent/
from langgraph.checkpoint.memory import MemorySaver

from src.agents.state import FinanceAgentState, make_initial_state
from src.agents.nodes import (
    generate_answer,
    grade_retrieval,
    load_skill,
    retrieve_both,
    retrieve_sql,
    retrieve_vector,
    rewrite_question,
    route_question,
)

load_dotenv()

# ---------------------------------------------------------------------------
# UTF-8-safe console output (survives Windows cp1252)
# ---------------------------------------------------------------------------

def _emit(msg: str) -> None:
    sys.stdout.buffer.write((msg + "\n").encode("utf-8", errors="replace"))


# ---------------------------------------------------------------------------
# Conditional edge functions
# ---------------------------------------------------------------------------

def route_retrieval(state: FinanceAgentState) -> Literal[
    "retrieve_vector", "retrieve_sql", "retrieve_both", "generate_answer"
]:
    """
    Decide which retrieval node to visit based on the strategy chosen by
    route_question.

    Returns
    -------
    Node name string consumed by LangGraph's conditional edge routing.
    """
    strategy = state.get("retrieval_strategy", "none")
    if strategy == "vector":
        return "retrieve_vector"
    if strategy == "sql":
        return "retrieve_sql"
    if strategy == "both":
        return "retrieve_both"
    # "none" or unknown → skip retrieval entirely
    return "generate_answer"


def check_relevance(state: FinanceAgentState) -> Literal[
    "generate_answer", "rewrite_question"
]:
    """
    Decide whether retrieved content is good enough to generate an answer,
    or whether the question should be rewritten and retrieval retried.

    Rules
    -----
    - score >= 0.5              → generate_answer (good enough)
    - score <  0.5 and retries < 2 → rewrite_question (try again)
    - retries >= 2              → generate_answer (best effort after max retries)
    """
    score   = state.get("relevance_score", 0.0)
    retries = state.get("retry_count", 0)

    if score >= 0.5 or retries >= 2:
        return "generate_answer"
    return "rewrite_question"


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def _build_graph() -> StateGraph:
    """Construct and return the compiled finance agent graph."""
    g = StateGraph(FinanceAgentState)

    # --- Register nodes ---
    g.add_node("route_question",   route_question)
    g.add_node("load_skill",       load_skill)
    g.add_node("retrieve_vector",  retrieve_vector)
    g.add_node("retrieve_sql",     retrieve_sql)
    g.add_node("retrieve_both",    retrieve_both)
    g.add_node("grade_retrieval",  grade_retrieval)
    g.add_node("rewrite_question", rewrite_question)
    g.add_node("generate_answer",  generate_answer)

    # --- Linear edges ---
    g.add_edge(START,              "route_question")
    g.add_edge("route_question",   "load_skill")

    # Retrieval nodes all feed into the grader
    g.add_edge("retrieve_vector",  "grade_retrieval")
    g.add_edge("retrieve_sql",     "grade_retrieval")
    g.add_edge("retrieve_both",    "grade_retrieval")

    # Final answer goes to END
    g.add_edge("generate_answer",  END)

    # --- Conditional: after load_skill, pick retrieval path ---
    g.add_conditional_edges(
        "load_skill",
        route_retrieval,
        {
            "retrieve_vector": "retrieve_vector",
            "retrieve_sql":    "retrieve_sql",
            "retrieve_both":   "retrieve_both",
            "generate_answer": "generate_answer",
        },
    )

    # --- Conditional: after grading, decide to answer or retry ---
    g.add_conditional_edges(
        "grade_retrieval",
        check_relevance,
        {
            "generate_answer":  "generate_answer",
            "rewrite_question": "rewrite_question",
        },
    )

    # --- Conditional: after rewrite, loop back to retrieval ---
    g.add_conditional_edges(
        "rewrite_question",
        route_retrieval,
        {
            "retrieve_vector": "retrieve_vector",
            "retrieve_sql":    "retrieve_sql",
            "retrieve_both":   "retrieve_both",
            "generate_answer": "generate_answer",
        },
    )

    return g


# Compile once at module level — MemorySaver keeps per-thread conversation history
_checkpointer = MemorySaver()
graph = _build_graph().compile(checkpointer=_checkpointer)


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def run_agent(
    question: str,
    provider: str | None = None,
    thread_id: str = "default",
    debug: bool = False,
) -> str:
    """
    Run the finance agent on a single question and return the final answer.

    Parameters
    ----------
    question:
        The user's natural-language financial question.
    provider:
        ``"ollama"`` or ``"claude"``.  Overrides ``DEFAULT_LLM`` in .env
        for this call only.
    thread_id:
        Identifies the conversation thread.  Reusing the same ID gives the
        agent access to prior messages via the MemorySaver checkpointer.
    debug:
        When True, prints every field written by each node.

    Returns
    -------
    The agent's final answer string, or an error message prefixed with
    ``"[ERROR]"`` if the graph raised an exception.
    """
    if provider:
        os.environ["DEFAULT_LLM"] = provider

    config        = {"configurable": {"thread_id": thread_id}}
    initial_state = make_initial_state(question)

    generation = ""
    node_order: list[str] = []

    try:
        for chunk in graph.stream(initial_state, config, stream_mode="updates"):
            for node_name, update in chunk.items():
                node_order.append(node_name)
                _emit(f"  → {node_name}")

                if debug and update:
                    for field, value in update.items():
                        # Truncate long values for readability
                        if isinstance(value, str) and len(value) > 120:
                            display = value[:120].replace("\n", " ") + " …"
                        elif isinstance(value, list):
                            display = f"[{len(value)} item(s)]"
                        else:
                            display = repr(value)
                        _emit(f"       {field}: {display}")

                # Capture the latest generation
                if "generation" in update:
                    generation = update["generation"]

    except Exception as exc:
        _emit(f"  [ERROR] Graph execution failed: {exc}")
        return f"[ERROR] {exc}"

    return generation


# ---------------------------------------------------------------------------
# Graph visualisation
# ---------------------------------------------------------------------------

def visualize_graph(output_dir: str = "docs") -> str:
    """
    Render the agent graph in two formats and save to disk.

    1. **Mermaid** — written to ``<output_dir>/agent_graph.md`` as a fenced
       code block, ready to render on GitHub or any Markdown viewer.
    2. **ASCII** — printed directly to the terminal for a quick at-a-glance
       topology check without opening any files.

    Parameters
    ----------
    output_dir:
        Directory for the Markdown output file.  Created if it doesn't exist.
        Relative to the project root; defaults to ``"docs/"``.

    Returns
    -------
    Path of the saved Markdown file as a string.
    """
    docs_dir = _ROOT / output_dir
    docs_dir.mkdir(parents=True, exist_ok=True)
    md_path  = docs_dir / "agent_graph.md"

    # --- Mermaid diagram ---
    mermaid = graph.get_graph().draw_mermaid()

    md_content = f"""\
# Personal Finance Agent — Graph Topology

This diagram is auto-generated by `src/agents/finance_agent.visualize_graph()`.
Re-run after any changes to nodes or edges to keep it up to date.

## How to read it
- **Solid arrows** (→) are unconditional edges.
- **Dashed arrows** (⇢) are conditional edges whose target depends on state.
- `grade_retrieval` fans out to either `generate_answer` (score ≥ 0.5 or
  retries ≥ 2) or `rewrite_question` (score < 0.5 and retries < 2).
- `rewrite_question` loops back to the same retrieval node that was used
  originally, controlled by `route_retrieval()`.

```mermaid
{mermaid.strip()}
```

## Node responsibilities

| Node | Writes to state |
|------|----------------|
| `route_question` | `selected_skill`, `retrieval_strategy` |
| `load_skill` | `skill_context` |
| `retrieve_vector` | `retrieved_docs` |
| `retrieve_sql` | `sql_results` |
| `retrieve_both` | `retrieved_docs`, `sql_results` |
| `grade_retrieval` | `relevance_score` |
| `rewrite_question` | `rewritten_question`, `retry_count` |
| `generate_answer` | `generation`, `messages` |
"""

    md_path.write_text(md_content, encoding="utf-8")
    _emit(f"  [visualize] Mermaid diagram saved → {md_path}")

    # --- ASCII diagram (terminal) ---
    _emit("")
    _emit("  Agent graph topology (ASCII):")
    _emit("")
    try:
        ascii_diagram = graph.get_graph().draw_ascii()
        for line in ascii_diagram.splitlines():
            _emit("  " + line)
    except ImportError:
        _emit("  (install grandalf for ASCII rendering: pip install grandalf)")
        _emit("  Mermaid source:")
        for line in mermaid.strip().splitlines():
            _emit("    " + line)

    _emit("")
    return str(md_path)


# ---------------------------------------------------------------------------
# Demo runner
# ---------------------------------------------------------------------------

_DEMO_QUESTIONS = [
    # (question, description)
    (
        "How much did I spend by category in January 2025?",
        "Period summary — should route to spend-analyzer / sql",
    ),
    (
        "What are my top 5 biggest expenses this year?",
        "Top-N expenses — should route to spend-analyzer / sql or both",
    ),
    (
        "Are there any unusual or suspicious charges on my account?",
        "Anomaly detection — should route to spend-analyzer / vector or both",
    ),
    (
        "What are my recurring bills and subscriptions?",
        "Recurring detection — should route to cashflow-forecaster",
    ),
    (
        "Compare my grocery and dining spending in January vs February 2025",
        "Period comparison — should route to spend-analyzer / sql",
    ),
]


def run_demo(provider: str | None = None) -> None:
    """
    Run five pre-defined questions through the agent and print a summary.

    For each question this function prints:
    - The question text and its expected routing category
    - The actual skill and retrieval strategy chosen by ``route_question``
    - Every node that fired, in order
    - The final answer (first 300 chars)
    - Wall-clock time for the complete run

    After all questions a summary table is printed with:
    - Per-question timing
    - Average time
    - Most common retrieval strategy
    - Number of questions that triggered self-correction (retry > 0)
    - Skill distribution

    Parameters
    ----------
    provider:
        ``"ollama"`` or ``"claude"``.  Defaults to ``DEFAULT_LLM`` from .env.
    """
    if provider:
        os.environ["DEFAULT_LLM"] = provider

    active_provider = os.getenv("DEFAULT_LLM", "ollama")

    _emit("")
    _emit("=" * 68)
    _emit(f"  Finance Agent Demo  ({active_provider})")
    _emit(f"  {len(_DEMO_QUESTIONS)} questions — routing, answers, and timing")
    _emit("=" * 68)

    # Per-run metrics collected for the summary
    timings:    list[float] = []
    strategies: list[str]   = []
    skills:     list[str]   = []
    corrections: int        = 0

    for idx, (question, description) in enumerate(_DEMO_QUESTIONS, start=1):
        _emit("")
        _emit(f"  Q{idx}  {description}")
        _emit(f"  {'─' * 64}")
        _emit(f"  \"{question}\"")
        _emit("")

        # Collect routing info while streaming
        selected_skill     = ""
        retrieval_strategy = ""
        nodes_fired:  list[str] = []
        retry_count = 0
        generation  = ""

        config = {"configurable": {"thread_id": f"demo-{uuid.uuid4()}"}}
        state  = make_initial_state(question)

        t0 = time.perf_counter()
        try:
            for chunk in graph.stream(state, config, stream_mode="updates"):
                for node_name, update in chunk.items():
                    nodes_fired.append(node_name)
                    _emit(f"    → {node_name}")

                    if "selected_skill"     in update:
                        selected_skill     = update["selected_skill"]
                    if "retrieval_strategy" in update:
                        retrieval_strategy = update["retrieval_strategy"]
                    if "retry_count"        in update:
                        retry_count        = update["retry_count"]
                    if "generation"         in update:
                        generation         = update["generation"]

        except Exception as exc:
            _emit(f"    [ERROR] {exc}")
            generation = f"[ERROR] {exc}"

        elapsed = time.perf_counter() - t0

        # Record metrics
        timings.append(elapsed)
        strategies.append(retrieval_strategy or "unknown")
        skills.append(selected_skill or "unknown")
        if retry_count > 0:
            corrections += 1

        # Print routing decision
        _emit("")
        _emit(f"  Routing   : skill={selected_skill!r}  strategy={retrieval_strategy!r}"
              f"  retries={retry_count}")
        _emit(f"  Path      : {' → '.join(nodes_fired)}")

        # Print answer (truncated)
        answer_preview = generation[:300].replace("\n", " ")
        if len(generation) > 300:
            answer_preview += " …"
        _emit("")
        _emit(f"  Answer    : {answer_preview}")
        _emit(f"  Time      : {elapsed:.1f}s")

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    _emit("")
    _emit("=" * 68)
    _emit("  Demo Summary")
    _emit("=" * 68)
    _emit("")

    # Per-question timing table
    _emit(f"  {'#':<3}  {'Time':>7}  {'Strategy':<10}  {'Skill':<28}  Question (truncated)")
    _emit(f"  {'─'*3}  {'─'*7}  {'─'*10}  {'─'*28}  {'─'*30}")
    for i, (q, _) in enumerate(_DEMO_QUESTIONS, start=1):
        _emit(
            f"  {i:<3}  {timings[i-1]:>6.1f}s"
            f"  {strategies[i-1]:<10}"
            f"  {skills[i-1]:<28}"
            f"  {q[:30]}"
        )

    _emit("")
    avg_time = sum(timings) / len(timings) if timings else 0.0
    _emit(f"  Average time          : {avg_time:.1f}s per question")
    _emit(f"  Total time            : {sum(timings):.1f}s")

    if strategies:
        most_common_strategy, count = Counter(strategies).most_common(1)[0]
        _emit(f"  Most common strategy  : {most_common_strategy!r} ({count}/{len(strategies)} questions)")

    if skills:
        _emit(f"  Skills used           : {dict(Counter(skills))}")

    _emit(f"  Self-corrections      : {corrections}/{len(_DEMO_QUESTIONS)} questions triggered a rewrite")

    fastest_i = timings.index(min(timings))
    slowest_i = timings.index(max(timings))
    _emit(f"  Fastest               : Q{fastest_i+1} ({timings[fastest_i]:.1f}s)")
    _emit(f"  Slowest               : Q{slowest_i+1} ({timings[slowest_i]:.1f}s)")
    _emit("")


# ---------------------------------------------------------------------------
# Interactive REPL
# ---------------------------------------------------------------------------

_HELP_TEXT = """
Personal Finance Agent — interactive mode
------------------------------------------
Type any financial question and press Enter.

Special commands:
  /quit              Exit the session.
  /reset             Start a new conversation (clears memory).
  /provider ollama   Switch to local Ollama (llama3.2).
  /provider claude   Switch to Claude API.
  /debug on          Print every state field written by each node.
  /debug off         Print only node names (default).
  /help              Show this message.
""".strip()


def interactive_mode() -> None:
    """
    REPL loop for the personal finance agent.

    Maintains conversation history within a session (same thread_id).
    Use /reset to start a fresh thread.
    """
    _emit("")
    _emit("=" * 60)
    _emit("  Personal Finance Agent")
    _emit("  Type /help for commands, /quit to exit.")
    _emit("=" * 60)
    _emit("")

    thread_id = str(uuid.uuid4())
    provider  = os.getenv("DEFAULT_LLM", "ollama")
    debug     = False

    while True:
        # Prompt
        try:
            sys.stdout.buffer.write(f"[{provider}] You: ".encode("utf-8", errors="replace"))
            sys.stdout.buffer.flush()
            raw = sys.stdin.readline()
        except (EOFError, KeyboardInterrupt):
            _emit("\nGoodbye.")
            break

        question = raw.strip()

        if not question:
            continue

        # --- Special commands ---
        if question.lower() in ("/quit", "/exit", "/q"):
            _emit("Goodbye.")
            break

        if question.lower() == "/reset":
            thread_id = str(uuid.uuid4())
            _emit(f"  [reset] New conversation started (thread: {thread_id[:8]}…)")
            continue

        if question.lower().startswith("/provider "):
            requested = question.split(None, 1)[1].strip().lower()
            if requested in ("ollama", "claude"):
                provider = requested
                os.environ["DEFAULT_LLM"] = provider
                _emit(f"  [provider] Switched to {provider}.")
            else:
                _emit("  [provider] Unknown provider. Use 'ollama' or 'claude'.")
            continue

        if question.lower().startswith("/debug "):
            flag = question.split(None, 1)[1].strip().lower()
            if flag == "on":
                debug = True
                _emit("  [debug] Debug mode ON — full state updates will be printed.")
            elif flag == "off":
                debug = False
                _emit("  [debug] Debug mode OFF.")
            else:
                _emit("  [debug] Use '/debug on' or '/debug off'.")
            continue

        if question.lower() in ("/help", "/?"):
            _emit(_HELP_TEXT)
            continue

        # --- Run the agent ---
        _emit("")
        _emit(f"  Processing ({provider}) …")
        _emit("")

        answer = run_agent(
            question  = question,
            provider  = provider,
            thread_id = thread_id,
            debug     = debug,
        )

        _emit("")
        _emit("Agent: " + answer)
        _emit("")


# ---------------------------------------------------------------------------
# __main__
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    interactive_mode()
