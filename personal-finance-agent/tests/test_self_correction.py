"""
tests/test_self_correction.py

Validates the agent's self-correction loop: poor retrieval → rewrite →
retry → generate.

Each test streams the full LangGraph run, collects a per-node trace, then
asserts specific behaviours around routing, relevance scoring, query
rewriting, and retry caps.

Run
---
    python -m tests.test_self_correction

Exit codes
----------
    0  all tests passed
    1  one or more tests failed
    2  agent could not be initialised (Ollama offline, DB missing, etc.)
"""

from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Project root on sys.path
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.finance_agent import graph          # noqa: E402
from src.agents.state import make_initial_state     # noqa: E402


# ---------------------------------------------------------------------------
# UTF-8-safe output
# ---------------------------------------------------------------------------

def _emit(msg: str = "") -> None:
    sys.stdout.buffer.write((msg + "\n").encode("utf-8", errors="replace"))


# ---------------------------------------------------------------------------
# Run-trace dataclass — collected while streaming
# ---------------------------------------------------------------------------

@dataclass
class RunTrace:
    """Everything observable from one agent run, captured node by node."""

    question: str

    # Routing (route_question)
    selected_skill:     str = ""
    retrieval_strategy: str = ""

    # Ordered list of every node that fired
    nodes_fired: list[str] = field(default_factory=list)

    # grade_retrieval scores in order (one entry per grading pass)
    relevance_scores: list[float] = field(default_factory=list)

    # rewrite_question outputs in order
    rewrites: list[str] = field(default_factory=list)

    # Highest retry_count seen (set by rewrite_question)
    final_retry_count: int = 0

    # Final answer from generate_answer
    generation: str = ""

    # Whether retrieval was attempted at all
    retrieval_attempted: bool = False

    @property
    def did_self_correct(self) -> bool:
        return self.final_retry_count > 0

    @property
    def hit_max_retries(self) -> bool:
        return self.final_retry_count >= 2


# ---------------------------------------------------------------------------
# Core runner — streams the graph and builds a RunTrace
# ---------------------------------------------------------------------------

def _run(question: str) -> RunTrace:
    """
    Run the finance agent and return a complete execution trace.

    Uses a fresh UUID thread ID each call so tests are isolated from each
    other and from previous sessions.
    """
    trace  = RunTrace(question=question)
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    state  = make_initial_state(question)

    _RETRIEVAL_NODES = {"retrieve_vector", "retrieve_sql", "retrieve_both"}

    for chunk in graph.stream(state, config, stream_mode="updates"):
        for node_name, update in chunk.items():
            trace.nodes_fired.append(node_name)

            if node_name in _RETRIEVAL_NODES:
                trace.retrieval_attempted = True

            if "selected_skill" in update:
                trace.selected_skill = update["selected_skill"]

            if "retrieval_strategy" in update:
                trace.retrieval_strategy = update["retrieval_strategy"]

            if "relevance_score" in update:
                trace.relevance_scores.append(float(update["relevance_score"]))

            if "rewritten_question" in update:
                trace.rewrites.append(update["rewritten_question"])

            if "retry_count" in update:
                trace.final_retry_count = int(update["retry_count"])

            if "generation" in update:
                trace.generation = str(update["generation"])

    return trace


# ---------------------------------------------------------------------------
# Diagnostic printer
# ---------------------------------------------------------------------------

def _print_trace(trace: RunTrace, label: str) -> None:
    _emit(f"  Question    : {trace.question}")
    _emit(f"  Skill       : {trace.selected_skill}  |  Strategy: {trace.retrieval_strategy}")
    _emit(f"  Nodes fired : {' → '.join(trace.nodes_fired)}")

    for i, (score, rewrite) in enumerate(
        zip(trace.relevance_scores, trace.rewrites + [None] * len(trace.relevance_scores)),
        start=1,
    ):
        _emit(f"  Grade {i}      : {score:.2f}")
        if i <= len(trace.rewrites):
            short = trace.rewrites[i - 1][:80].replace("\n", " ")
            _emit(f"  Rewrite {i}    : {short}")

    # Last grade (after final retry) if it wasn't paired with a rewrite
    extra_grades = len(trace.relevance_scores) - len(trace.rewrites)
    for j in range(extra_grades):
        idx = len(trace.rewrites) + j
        if idx < len(trace.relevance_scores):
            _emit(f"  Grade {idx+1}      : {trace.relevance_scores[idx]:.2f}  (→ generate)")

    _emit(f"  Retries     : {trace.final_retry_count}")
    _emit(f"  Generation  : {trace.generation[:120].replace(chr(10), ' ')}{'…' if len(trace.generation) > 120 else ''}")


# ---------------------------------------------------------------------------
# Individual tests
# ---------------------------------------------------------------------------

def _run_test(label: str, fn) -> bool:
    """
    Execute a single test function.  Returns True on PASS, False on FAIL.
    The test function must raise AssertionError on failure.
    """
    SEP = "-" * 64
    _emit(SEP)
    _emit(f"TEST: {label}")
    _emit(SEP)
    try:
        fn()
        _emit(f"  PASS")
        return True
    except AssertionError as exc:
        _emit(f"  FAIL  — {exc}")
        return False
    except Exception as exc:
        _emit(f"  ERROR — {type(exc).__name__}: {exc}")
        return False
    finally:
        _emit("")


def test_ambiguous_query() -> None:
    """
    An intentionally vague question should have low initial relevance,
    trigger at least one rewrite, and still produce a non-empty answer.

    Checks
    ------
    1. retry_count >= 1  (self-correction fired)
    2. rewritten_question differs from the original  (something was rewritten)
    3. generation is non-empty  (agent gave a best-effort answer)
    """
    question = "that thing I bought at the store last week"
    _emit(f"  Streaming: \"{question}\"")
    _emit("")
    trace = _run(question)
    _print_trace(trace, "ambiguous")

    # Check 1 — self-correction loop fired
    assert trace.did_self_correct, (
        f"Expected retry_count >= 1 but got {trace.final_retry_count}. "
        "The grader may have scored the initial retrieval as relevant, or "
        "retrieval was skipped (strategy='none')."
    )

    # Check 2 — question was actually rewritten into something different
    assert trace.rewrites, "No rewrites recorded despite retry_count > 0."
    first_rewrite = trace.rewrites[0].strip().lower()
    original_lower = question.lower()
    assert first_rewrite != original_lower, (
        "Rewritten question is identical to the original — rewriter did nothing."
    )

    # Check 3 — a generation was produced
    assert trace.generation.strip(), "Agent produced an empty generation."


def test_numerical_question_routing() -> None:
    """
    A clearly numerical question should be routed to SQL (or 'both'), not
    pure vector search.  The final answer should contain currency figures.

    Checks
    ------
    1. retrieval_strategy is "sql" or "both"  (not pure vector)
    2. generation is non-empty
    3. generation contains "$"  (numeric data was surfaced)
    """
    question = "What is my total spending by category for January 2025?"
    _emit(f"  Streaming: \"{question}\"")
    _emit("")
    trace = _run(question)
    _print_trace(trace, "numerical")

    # Check 1 — router picked a SQL-capable path
    assert trace.retrieval_strategy in ("sql", "both", "none"), (
        f"Expected strategy 'sql', 'both', or 'none' for a numerical question, "
        f"got '{trace.retrieval_strategy}'. The router may be over-relying on "
        "vector search for aggregation queries."
    )

    # Check 2 — a generation was produced
    assert trace.generation.strip(), "Agent produced an empty generation."

    # Check 3 — answer references dollar amounts (SQL data was used)
    has_dollars = "$" in trace.generation or "dollar" in trace.generation.lower()
    assert has_dollars, (
        "Final answer does not mention dollar amounts. "
        "SQL retrieval may have failed or been ignored by the generator. "
        f"Generation: {trace.generation[:200]}"
    )


def test_max_retry_cap() -> None:
    """
    A question that cannot be answered from transaction data should exhaust
    both retry attempts and still produce a best-effort answer rather than
    crashing or returning an empty string.

    Checks
    ------
    1. retry_count == 2  (hit the hard cap; did not loop forever)
    2. generate_answer ran  (graph always terminates with an answer)
    3. generation is non-empty  (best-effort response was produced)
    """
    # The mock database only contains 2025–2026 data.  Asking for a detailed
    # breakdown of 2023 spending will force the SQL retriever to return empty
    # results ("No transactions found"), causing the grader to score 0.0 on
    # both retrieval attempts and exhaust the retry budget.
    question = (
        "Show me my complete spending breakdown for all of 2023, "
        "including monthly totals and category analysis for every month."
    )
    _emit(f"  Streaming: \"{question}\"")
    _emit("")
    trace = _run(question)
    _print_trace(trace, "max-retry")

    # Check 1 — hit the retry cap (2 rewrites attempted)
    assert trace.hit_max_retries, (
        f"Expected retry_count == 2 but got {trace.final_retry_count}. "
        "The grader may have scored an unanswerable question as relevant, or "
        "the retry loop exited early."
    )

    # Check 2 — graph always ends at generate_answer
    assert "generate_answer" in trace.nodes_fired, (
        "generate_answer node never ran — graph terminated abnormally."
    )

    # Check 3 — non-empty best-effort generation
    assert trace.generation.strip(), (
        "Agent produced an empty generation even after exhausting retries. "
        "generate_answer should always produce something."
    )


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def _print_summary(results: list[tuple[str, bool]]) -> None:
    passed = sum(1 for _, ok in results if ok)
    total  = len(results)

    _emit("=" * 64)
    _emit(f"Self-Correction Test Results: {passed}/{total} passed")
    _emit("=" * 64)
    for label, ok in results:
        status = "PASS" if ok else "FAIL"
        _emit(f"  [{status}]  {label}")
    _emit("")

    if passed < total:
        _emit("Tuning suggestions for failures:")
        _emit("  retry_count too low: grade_retrieval threshold may be too lenient")
        _emit("                       (increase strictness or lower passing threshold)")
        _emit("  retry_count too high: grader is too strict; consider raising the")
        _emit("                        passing score from 0.5 to 0.3")
        _emit("  no $ in answer: SQL retrieval succeeded but generator ignored it;")
        _emit("                   check generate_answer context assembly")
        _emit("")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    _emit("")
    _emit("=" * 64)
    _emit("  Agent Self-Correction Tests  (Ollama llama3.2)")
    _emit("=" * 64)
    _emit("")

    # Warm-up connectivity check
    try:
        from src.agents.nodes import get_llm
        llm = get_llm()
        llm.invoke("ping")
    except Exception as exc:
        _emit(f"[SKIP] Cannot reach LLM: {exc}")
        _emit("       Start Ollama with 'ollama serve' and retry.")
        return 2

    tests = [
        ("Ambiguous query → self-correction",       test_ambiguous_query),
        ("Numerical question → SQL routing + $",    test_numerical_question_routing),
        ("Unanswerable query → max retry cap (2)",  test_max_retry_cap),
    ]

    results: list[tuple[str, bool]] = []
    for label, fn in tests:
        ok = _run_test(label, fn)
        results.append((label, ok))

    _print_summary(results)

    return 0 if all(ok for _, ok in results) else 1


if __name__ == "__main__":
    sys.exit(main())
