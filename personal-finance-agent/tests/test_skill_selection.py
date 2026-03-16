"""
tests/test_skill_selection.py

Validates that an LLM (Ollama llama3.2) selects the correct skill for
user queries using only the Level 1 registry descriptions embedded in
the prompt.

How it works
------------
1. Load the skill registry (Level 1 — name + description only).
2. For each test case, send a structured prompt to Ollama asking which
   skill to use, then parse the model's response.
3. Compare to the expected skill name and print PASS / FAIL.
4. Report overall accuracy.  Target: 7 / 8 or better.

Run
---
    python -m tests.test_skill_selection

Exit codes
----------
    0  all tests passed (or target met)
    1  below target accuracy
    2  Ollama unavailable / configuration error
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Project root on sys.path so we can import src.skills.registry
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.skills.registry import discover_skills, format_skill_context  # noqa: E402

# ---------------------------------------------------------------------------
# Ollama configuration
# ---------------------------------------------------------------------------
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL      = "llama3.2"
TIMEOUT_S  = 60      # seconds per request

# ---------------------------------------------------------------------------
# Test cases  (query, expected_skill_name)
# ---------------------------------------------------------------------------
TEST_CASES: list[tuple[str, str]] = [
    ("Load my RBC bank statement",              "statement-parser"),
    ("What category is each transaction?",      "transaction-categorizer"),
    ("How much did I spend last month?",        "spend-analyzer"),
    ("What will my balance be next month?",     "cashflow-forecaster"),
    ("Compare my grocery spending Jan vs Feb",  "spend-analyzer"),
    ("Import this CSV file",                    "statement-parser"),
    ("Are there any unusual charges?",          "spend-analyzer"),
    ("What are my recurring bills?",            "cashflow-forecaster"),
]

TARGET_PASS = 7   # minimum to consider the descriptions acceptable

# ---------------------------------------------------------------------------
# Ollama helpers
# ---------------------------------------------------------------------------

def _build_prompt(skill_context: str, query: str, skill_names: list[str]) -> str:
    """
    Build the zero-shot skill-selection prompt.

    The response constraint (respond with only the skill name from the list)
    keeps parsing simple and reduces ambiguity.
    """
    names_inline = ", ".join(skill_names)
    return (
        f"{skill_context}\n\n"
        f"The valid skill names are: {names_inline}\n\n"
        f"Which skill should be used for this user request?\n"
        f'User request: "{query}"\n\n'
        f"Respond with ONLY the skill name from the list above. "
        f"Do not add any explanation or punctuation."
    )


def _call_ollama(prompt: str) -> str:
    """
    Send *prompt* to Ollama and return the raw response text.

    Raises
    ------
    ConnectionError   if Ollama is not running or returns a bad status.
    """
    payload = json.dumps({
        "model":  MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.0,   # deterministic — we want a fixed choice
            "num_predict": 32,    # skill names are short; cap token budget
        },
    }).encode("utf-8")

    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body.get("response", "").strip()
    except urllib.error.URLError as exc:
        raise ConnectionError(
            f"Cannot reach Ollama at {OLLAMA_URL}. "
            f"Is 'ollama serve' running?  ({exc})"
        ) from exc


def _normalize(response: str, skill_names: list[str]) -> str | None:
    """
    Extract a skill name from the LLM's raw response.

    Strategy (in order):
    1. Exact match (case-insensitive) against known skill names.
    2. Substring match — the model may add punctuation or extra words.
    3. Return None if nothing matches.
    """
    cleaned = response.strip().lower().rstrip(".,!?;:")

    # Exact match first
    for name in skill_names:
        if cleaned == name.lower():
            return name

    # Substring match
    for name in skill_names:
        if name.lower() in cleaned:
            return name

    return None


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def _emit(msg: str) -> None:
    """UTF-8-safe print — survives Windows cp1252 consoles."""
    sys.stdout.buffer.write((msg + "\n").encode("utf-8", errors="replace"))


def run_tests() -> int:
    """
    Run all skill-selection test cases.

    Returns
    -------
    Exit code: 0 = target met, 1 = below target, 2 = setup failure.
    """
    # --- Load registry ---------------------------------------------------
    skills = discover_skills()
    if not skills:
        _emit("[ERROR] No skills discovered. Run from the project root.")
        return 2

    skill_names   = [s["name"] for s in skills]
    skill_context = format_skill_context(skills)

    _emit("")
    _emit("=" * 68)
    _emit("Skill Selection Test  (Ollama llama3.2)")
    _emit("=" * 68)
    _emit(f"Model   : {MODEL}")
    _emit(f"Skills  : {', '.join(skill_names)}")
    _emit(f"Cases   : {len(TEST_CASES)}")
    _emit(f"Target  : {TARGET_PASS}/{len(TEST_CASES)} PASS")
    _emit("")

    # --- Check Ollama availability ---------------------------------------
    try:
        _call_ollama("ping")   # short warm-up; response content is ignored
    except ConnectionError as exc:
        _emit(f"[SKIP] {exc}")
        return 2

    # --- Run each test case ---------------------------------------------
    col_q    = 46   # query column width
    col_exp  = 24   # expected column width
    col_got  = 24   # got column width

    header = (
        f"  {'Query':<{col_q}}  {'Expected':<{col_exp}}  "
        f"{'Got':<{col_got}}  Result"
    )
    _emit(header)
    _emit("  " + "-" * (col_q + col_exp + col_got + 18))

    passed   = 0
    failures: list[tuple[str, str, str | None]] = []

    for query, expected in TEST_CASES:
        prompt   = _build_prompt(skill_context, query, skill_names)
        raw      = _call_ollama(prompt)
        selected = _normalize(raw, skill_names)

        ok     = selected == expected
        result = "PASS" if ok else "FAIL"
        got    = selected or f"(unrecognised: {raw[:20]!r})"

        _emit(
            f"  {query:<{col_q}}  {expected:<{col_exp}}  "
            f"{got:<{col_got}}  {result}"
        )

        if ok:
            passed += 1
        else:
            failures.append((query, expected, selected))

    # --- Summary --------------------------------------------------------
    _emit("")
    _emit("-" * 68)
    _emit(f"  Result : {passed}/{len(TEST_CASES)} passed")
    _emit(f"  Target : {TARGET_PASS}/{len(TEST_CASES)}")

    if passed >= TARGET_PASS:
        _emit("  Status : PASS  (skill descriptions are adequate)")
    else:
        _emit("  Status : FAIL  (skill descriptions need tuning)")
        _emit("")
        _emit("  Failed cases:")
        for q, exp, got in failures:
            _emit(f"    query    : {q}")
            _emit(f"    expected : {exp}")
            _emit(f"    got      : {got}")
            _emit("")
        _emit("  Suggested fixes:")
        _emit("  - Add trigger keywords for misrouted queries to the")
        _emit("    relevant SKILL.md 'description' frontmatter field.")
        _emit("  - Shorten descriptions that are ambiguous when compared")
        _emit("    side-by-side (the full text is visible to the model).")

    _emit("")

    return 0 if passed >= TARGET_PASS else 1


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sys.exit(run_tests())
