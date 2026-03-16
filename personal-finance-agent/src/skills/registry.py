"""
Skill registry — discover, load, and execute SKILL.md-based skills.

Three-level progressive disclosure
-----------------------------------
Level 1  discover_skills()        lightweight list for the agent's system prompt
Level 2  load_skill()             full SKILL.md body injected at activation
Level 3  load_skill_resource()    reference files fetched on demand
         run_skill_script()       execute a skill's helper script

Usage
-----
    from src.skills.registry import discover_skills, load_skill
    from src.skills.registry import load_skill_resource, run_skill_script
    from src.skills.registry import format_skill_context

    # Level 1 — embed in system prompt
    skills = discover_skills()
    system_prompt += format_skill_context(skills)

    # Level 2 — inject when skill is activated
    instructions = load_skill("cashflow-forecaster")

    # Level 3 — fetch reference data or run a helper script
    patterns = load_skill_resource("transaction-categorizer",
                                   "reference/merchant_patterns.json")
    output = run_skill_script("statement-parser", "validate_parse.py",
                              ["--input", "parsed.json"])
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

# Resolved once at import time; works regardless of cwd at runtime.
# Layout: src/skills/registry.py  ->  project root is two levels up.
_PROJECT_ROOT = Path(__file__).parent.parent.parent


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _skills_root(skills_dir: str) -> Path:
    """Return an absolute Path for the skills directory."""
    p = Path(skills_dir)
    return p if p.is_absolute() else _PROJECT_ROOT / p


def _find_skill_dir(root: Path, skill_name: str) -> Path:
    """
    Return the directory for *skill_name* inside *root*.

    Tries an exact match first, then a case-insensitive scan.

    Raises
    ------
    ValueError  if no matching skill directory with a SKILL.md is found.
    """
    candidate = root / skill_name
    if candidate.is_dir() and (candidate / "SKILL.md").exists():
        return candidate

    for d in root.iterdir():
        if d.is_dir() and d.name.lower() == skill_name.lower():
            if (d / "SKILL.md").exists():
                return d

    raise ValueError(f"Skill '{skill_name}' not found in {root}")


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """
    Split YAML frontmatter from Markdown body.

    Expects the file to begin with ``---`` and contain a closing ``---``
    on its own line.  Returns ``({}, full_text)`` if the format is not
    recognised (rather than raising), so callers degrade gracefully.

    Returns
    -------
    (frontmatter_dict, body_text)
    """
    if not text.startswith("---"):
        return {}, text

    end = text.find("\n---", 3)
    if end == -1:
        return {}, text

    yaml_block = text[3:end].strip()
    body = text[end + 4:].lstrip("\n")   # skip past the '\n---' separator

    try:
        data = yaml.safe_load(yaml_block) or {}
    except yaml.YAMLError:
        data = {}

    return data, body


# ---------------------------------------------------------------------------
# Level 1 — Discovery
# ---------------------------------------------------------------------------

def discover_skills(skills_dir: str = "skills/") -> list[dict]:
    """
    Scan *skills_dir* for SKILL.md files and return a lightweight skill list.

    Only the YAML frontmatter is read (name + description).  The full body
    is *not* loaded, keeping memory usage minimal when building a system
    prompt that lists many skills.

    Parameters
    ----------
    skills_dir:
        Path to the skills root, relative to the project root or absolute.
        Defaults to ``"skills/"``.

    Returns
    -------
    List of dicts (sorted by skill name), each containing:

    .. code-block:: python

        {
            "name":        "cashflow-forecaster",
            "description": "Project future daily account balance …",
            "path":        "/abs/path/to/SKILL.md",
        }

    Returns an empty list if the directory does not exist or contains no
    SKILL.md files.
    """
    root = _skills_root(skills_dir)
    if not root.exists():
        return []

    skills: list[dict] = []
    for skill_md in sorted(root.glob("*/SKILL.md")):
        text = skill_md.read_text(encoding="utf-8")
        frontmatter, _ = _parse_frontmatter(text)

        name = frontmatter.get("name") or skill_md.parent.name

        # YAML folded/literal block scalars (>) arrive as multi-line strings;
        # collapse to a single line for the system prompt.
        raw_desc = frontmatter.get("description", "")
        description = " ".join(str(raw_desc).split())

        skills.append({
            "name":        name,
            "description": description,
            "path":        str(skill_md),
        })

    return skills


# ---------------------------------------------------------------------------
# Level 2 — Full skill loading
# ---------------------------------------------------------------------------

def load_skill(skill_name: str, skills_dir: str = "skills/") -> str:
    """
    Return the full Markdown body of a SKILL.md (frontmatter stripped).

    This is the text injected into the agent's context when a skill is
    activated — the complete how-to instructions.

    Parameters
    ----------
    skill_name:
        Directory name of the skill, e.g. ``"cashflow-forecaster"``.
    skills_dir:
        Root directory for skills.

    Returns
    -------
    Instruction text as a string.

    Raises
    ------
    ValueError  if the skill cannot be found.
    """
    root = _skills_root(skills_dir)
    skill_dir = _find_skill_dir(root, skill_name)
    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    _, body = _parse_frontmatter(text)
    return body


# ---------------------------------------------------------------------------
# Level 3 — Resources
# ---------------------------------------------------------------------------

def load_skill_resource(
    skill_name: str,
    resource_path: str,
    skills_dir: str = "skills/",
) -> str:
    """
    Read a file from within a skill's directory and return its contents.

    Parameters
    ----------
    skill_name:
        Directory name of the skill.
    resource_path:
        Path relative to the skill directory, e.g.
        ``"reference/merchant_patterns.json"``.
    skills_dir:
        Root directory for skills.

    Returns
    -------
    File contents as a UTF-8 string.

    Raises
    ------
    ValueError          if the skill is not found.
    FileNotFoundError   if *resource_path* does not exist inside the skill dir.
    """
    root = _skills_root(skills_dir)
    skill_dir = _find_skill_dir(root, skill_name)
    target = skill_dir / resource_path

    if not target.exists():
        raise FileNotFoundError(
            f"Resource '{resource_path}' not found in skill '{skill_name}' "
            f"(looked in {skill_dir})"
        )

    return target.read_text(encoding="utf-8")


def run_skill_script(
    skill_name: str,
    script_name: str,
    args: list[str] | None = None,
    skills_dir: str = "skills/",
) -> str:
    """
    Execute a Python script from a skill's ``scripts/`` directory.

    The script runs with the **project root** as the working directory so
    that relative paths such as ``"data/finance.db"`` resolve correctly.
    Both stdout and stderr are captured and returned as a single string.

    Parameters
    ----------
    skill_name:
        Directory name of the skill.
    script_name:
        Filename of the script, e.g. ``"validate_parse.py"``.
    args:
        Optional list of CLI arguments passed to the script.
    skills_dir:
        Root directory for skills.

    Returns
    -------
    Captured output (stdout + stderr if non-empty) as a UTF-8 string.

    Raises
    ------
    ValueError          if the skill is not found.
    FileNotFoundError   if the script does not exist.
    """
    root = _skills_root(skills_dir)
    skill_dir = _find_skill_dir(root, skill_name)
    script_path = skill_dir / "scripts" / script_name

    if not script_path.exists():
        raise FileNotFoundError(
            f"Script '{script_name}' not found in "
            f"skill '{skill_name}/scripts/'"
        )

    cmd = [sys.executable, str(script_path)] + (args or [])
    result = subprocess.run(
        cmd,
        cwd=str(_PROJECT_ROOT),
        capture_output=True,
        text=False,          # read raw bytes; decode manually
    )

    stdout = result.stdout.decode("utf-8", errors="replace")
    stderr = result.stderr.decode("utf-8", errors="replace")

    output = stdout
    if stderr.strip():
        output += f"\n[stderr]\n{stderr}"

    return output


# ---------------------------------------------------------------------------
# System-prompt formatting
# ---------------------------------------------------------------------------

def format_skill_context(skills: list[dict]) -> str:
    """
    Format discovered skills into a section suitable for a system prompt.

    Parameters
    ----------
    skills:
        Output of :func:`discover_skills`.

    Returns
    -------
    A multi-line string, for example::

        Available skills:
        - statement-parser: Parse Canadian bank statements …
        - transaction-categorizer: Two-pass categorization …

    Returns ``"Available skills: (none)"`` when *skills* is empty.
    """
    if not skills:
        return "Available skills: (none)"

    lines = ["Available skills:"]
    for s in skills:
        lines.append(f"- {s['name']}: {s['description']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# __main__ — smoke test for all four levels
# ---------------------------------------------------------------------------

def _emit(msg: str) -> None:
    """UTF-8-safe print — survives Windows cp1252 consoles."""
    sys.stdout.buffer.write((msg + "\n").encode("utf-8", errors="replace"))


if __name__ == "__main__":
    import textwrap

    SEP = "-" * 72

    # ------------------------------------------------------------------
    # 1. Discover all skills
    # ------------------------------------------------------------------
    _emit(SEP)
    _emit("LEVEL 1 -- Skill Registry")
    _emit(SEP)

    skills = discover_skills()
    if not skills:
        _emit("[WARN] No skills found. Check that 'skills/' exists.")
    for s in skills:
        _emit(f"  {s['name']:<30}  {s['path']}")
        _emit(f"    {textwrap.shorten(s['description'], width=66)}")

    _emit("")
    _emit("System-prompt section:")
    _emit(format_skill_context(skills))

    # ------------------------------------------------------------------
    # 2. Load one skill's full instructions
    # ------------------------------------------------------------------
    DEMO_SKILL = "cashflow-forecaster"
    _emit("")
    _emit(SEP)
    _emit(f"LEVEL 2 -- Full instructions: {DEMO_SKILL}")
    _emit(SEP)
    try:
        body = load_skill(DEMO_SKILL)
        lines = body.splitlines()
        _emit("\n".join(lines[:40]))
        if len(lines) > 40:
            _emit(f"  ... ({len(lines) - 40} more lines)")
    except ValueError as exc:
        _emit(f"[ERROR] {exc}")

    # ------------------------------------------------------------------
    # 3. Load a reference resource
    # ------------------------------------------------------------------
    DEMO_RESOURCE_SKILL = "transaction-categorizer"
    DEMO_RESOURCE_PATH  = "reference/merchant_patterns.json"
    _emit("")
    _emit(SEP)
    _emit(f"LEVEL 3a -- Resource: {DEMO_RESOURCE_SKILL}/{DEMO_RESOURCE_PATH}")
    _emit(SEP)
    try:
        content = load_skill_resource(DEMO_RESOURCE_SKILL, DEMO_RESOURCE_PATH)
        lines = content.splitlines()
        _emit("\n".join(lines[:30]))
        if len(lines) > 30:
            _emit(f"  ... ({len(lines) - 30} more lines)")
    except (ValueError, FileNotFoundError) as exc:
        _emit(f"[ERROR] {exc}")

    # ------------------------------------------------------------------
    # 4. Run a skill script
    # ------------------------------------------------------------------
    DEMO_SCRIPT_SKILL = "transaction-categorizer"
    DEMO_SCRIPT_NAME  = "pattern_categorize.py"
    DEMO_SCRIPT_ARGS  = ["--input", "data/mock/rbc_chequing_2025.csv", "--stats"]
    _emit("")
    _emit(SEP)
    _emit(f"LEVEL 3b -- Script: {DEMO_SCRIPT_SKILL}/scripts/{DEMO_SCRIPT_NAME}")
    _emit(f"            args:   {DEMO_SCRIPT_ARGS}")
    _emit(SEP)
    try:
        output = run_skill_script(DEMO_SCRIPT_SKILL, DEMO_SCRIPT_NAME, DEMO_SCRIPT_ARGS)
        _emit(output.rstrip())
    except (ValueError, FileNotFoundError) as exc:
        _emit(f"[ERROR] {exc}")
