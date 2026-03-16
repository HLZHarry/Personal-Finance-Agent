# Phase 3: Skills Architecture (~4 hours)
## Personal Finance Agent — Learning Project

---

## What You're Learning

This phase is about **context engineering** — the art of writing instructions
that make an AI agent reliably good at specific tasks. You'll transform your
skeleton SKILL.md files from Phase 1 into fully functional skills with:

- Progressive disclosure (3-level loading)
- Helper scripts for deterministic operations
- Reference files for domain knowledge
- Clear trigger descriptions so the agent picks the right skill

This is the skill that separates a junior AI engineer from a senior one.

---

## Key Concept: How Skills Actually Work (3 Levels)

This is the most important concept in this phase. Skills load progressively:

**Level 1 — Discovery (always in context, ~50 tokens per skill)**
The agent only reads the `name` and `description` from the YAML frontmatter.
This is how it decides WHICH skill to activate. If your description is bad,
the skill never triggers — no matter how good your instructions are.

**Level 2 — Instructions (loaded when triggered, <5k tokens)**
When the agent decides a skill is relevant, it reads the full SKILL.md body.
This is your main playbook — step-by-step instructions the agent follows.

**Level 3 — Resources (loaded on demand, unlimited)**
Scripts, reference files, templates that the agent reads ONLY when it needs
them during execution. These don't cost context tokens until accessed.

This means you can have 50 skills installed with near-zero context cost.
Only the relevant skill's instructions load, and only the needed resources
within that skill get read.

---

## The #1 Mistake: Bad Descriptions

Your description is like a function signature — it determines when the
skill gets called. The instructions are the function body.

**Bad description** (too vague — will trigger for everything or nothing):
```yaml
description: Helps with financial analysis
```

**Bad description** (too narrow — misses natural phrasings):
```yaml
description: Use when user says "categorize my transactions"
```

**Good description** (specific scope + natural trigger phrases):
```yaml
description: >
  Categorize financial transactions into spending categories like groceries,
  dining, utilities, and transportation. Use when the user asks about
  spending by category, wants to know "what did I spend on X", asks to
  "break down" or "classify" their expenses, or when transaction data
  needs category labels for analysis.
```

The good description includes: what it does, specific trigger phrases a
user might say, and when it should activate automatically (after parsing).

---

## Step 1: Upgrade statement-parser Skill (~45 min)

### Prompt Claude Code:

```
Upgrade skills/statement-parser/SKILL.md to be a production-quality skill.

The skill should follow the 3-level progressive disclosure pattern:
- Level 1: YAML frontmatter with a precise description
- Level 2: Step-by-step instructions in the SKILL.md body
- Level 3: Reference files and scripts in the skill directory

Requirements for the SKILL.md body:
- "When to use" section with specific trigger phrases
- "When NOT to use" section (boundary conditions)
- Step-by-step parsing instructions
- Error handling instructions (what to do when parsing fails)
- Output format specification with example JSON
- Link to reference files in the skill directory

Also create these supporting files:

1. skills/statement-parser/reference/bank_formats.md
   - Document the CSV column formats for: RBC chequing, Visa statements,
     mortgage amortization schedules
   - Include example rows for each format
   - Document known quirks (e.g., RBC uses empty cells for zero amounts)

2. skills/statement-parser/scripts/validate_parse.py
   - A deterministic validation script the agent can run after parsing
   - Checks: no null dates, no zero amounts, balance calculations correct,
     date range is reasonable
   - Outputs structured JSON result: {valid: true/false, errors: [...]}

3. skills/statement-parser/reference/supported_banks.md
   - List of supported banks and their formats
   - Detection rules (which columns indicate which bank)

The SKILL.md should reference these files with relative paths.
Keep the SKILL.md body under 3000 tokens — put details in reference files.
```

### After Claude Code generates it, review these specific things:

1. **Read the description** — would this trigger if you said "load my bank statements"? What about "import my financial data"? What about "parse this PDF"?

2. **Check the instructions** — are the steps ordered logically? Is there a clear decision tree for CSV vs PDF?

3. **Run the validation script manually:**
```powershell
python skills/statement-parser/scripts/validate_parse.py data/mock/rbc_chequing_2025.csv
```
Does it produce clean JSON output?

---

## Step 2: Upgrade transaction-categorizer Skill (~60 min)

This is the most interesting skill because it combines **deterministic logic**
(pattern matching) with **LLM reasoning** (classifying ambiguous transactions).

### Prompt Claude Code:

```
Upgrade skills/transaction-categorizer/SKILL.md to a production skill.

This skill has TWO modes:
1. Pattern matching (fast, deterministic) — for known merchants
2. LLM classification (slower, flexible) — for ambiguous transactions

Requirements for SKILL.md body:
- Clear 2-pass process: pattern match first, LLM second
- Instructions for the agent on when to use each mode
- Confidence scoring: HIGH (pattern match), MEDIUM (LLM confident),
  LOW (LLM uncertain)
- Instructions to ask the user for clarification on LOW confidence items

Create supporting files:

1. skills/transaction-categorizer/reference/merchant_patterns.json
   - JSON mapping of regex patterns to categories, e.g.:
     {"GROCERIES": ["LOBLAWS", "NO FRILLS", "T&T", "COSTCO", "FARM BOY",
      "METRO", "SOBEYS", "WALMART SUPER"],
      "DINING": ["MCDONALD", "TIM HORTON", "STARBUCKS", "SKIP THE DISHES",
       "UBER EATS", "DOORDASH"],
      "TRANSPORTATION": ["PRESTO", "UBER TRIP", "ESSO", "PETRO-CANADA",
       "SHELL", "PIONEER"],
      "UTILITIES": ["ENBRIDGE", "TORONTO HYDRO", "ROGERS", "BELL", "TELUS"],
      "SUBSCRIPTIONS": ["NETFLIX", "SPOTIFY", "AMAZON PRIME", "DISNEY PLUS"]}
   - Include 10+ patterns per category for major Canadian merchants

2. skills/transaction-categorizer/scripts/pattern_categorize.py
   - Takes a CSV of transactions, applies pattern matching
   - Outputs: categorized transactions + list of unmatched ones
   - Deterministic — same input always gives same output

3. skills/transaction-categorizer/reference/llm_prompt_template.md
   - The prompt template used for LLM classification of ambiguous transactions
   - Includes few-shot examples of correct categorization
   - Tells the LLM to output JSON with category + confidence

4. skills/transaction-categorizer/reference/category_definitions.md
   - Detailed definitions of each category with edge cases
   - E.g., "GROCERIES includes supermarkets but NOT convenience stores
     (those go under SHOPPING). Costco is GROCERIES even though they
     sell non-food items."

Keep SKILL.md body under 4000 tokens. Details go in reference files.
```

### Key learning: deterministic vs LLM reasoning

This is a critical pattern in production AI systems. You should understand
WHY we use pattern matching first:

| Approach | Speed | Cost | Accuracy | When to use |
|----------|-------|------|----------|-------------|
| Pattern match | Instant | Free | 100% for known merchants | First pass — handles ~70% of transactions |
| LLM classification | 1-3 sec | ~$0.001/txn | ~90% | Second pass — handles the remaining ~30% |

The deterministic script handles the easy cases (everyone knows Loblaws is
groceries). The LLM handles the ambiguous ones ("SQUARE *KING SLICE" —
is that dining or shopping?). This hybrid approach gives you speed AND
flexibility at minimal cost.

### Validate:

```powershell
# Test pattern matching
python skills/transaction-categorizer/scripts/pattern_categorize.py \
  data/mock/rbc_chequing_2025.csv

# Check: what percentage got categorized by patterns vs left for LLM?
```

---

## Step 3: Upgrade spend-analyzer Skill (~45 min)

### Prompt Claude Code:

```
Upgrade skills/spend-analyzer/SKILL.md to a production skill.

This skill is the main "insights" skill — it answers questions about
spending patterns and trends.

Requirements for SKILL.md body:
- Clear decision tree: what type of analysis to run based on the question
- Instructions for using SQL queries (via FinanceSQLStore) for exact numbers
- Instructions for using vector search (via FinanceVectorStore) for semantic queries
- Output formatting: tables for comparisons, summaries for overviews
- Instructions on handling missing data gracefully

The skill should handle these query types:
1. Period summary: "What did I spend last month?"
2. Category breakdown: "Break down my January spending"
3. Comparison: "Compare Jan vs Feb spending"
4. Top-N: "What were my biggest expenses?"
5. Trend: "Is my dining spending going up?"
6. Anomaly: "Any unusual charges?"

Create supporting files:

1. skills/spend-analyzer/reference/query_templates.md
   - SQL query templates for each query type above
   - Include parameterized versions (with {start_date}, {end_date}, etc.)
   - Example: "Period summary" ->
     SELECT category, SUM(amount) as total, COUNT(*) as txn_count
     FROM transactions
     WHERE date BETWEEN '{start_date}' AND '{end_date}'
     GROUP BY category ORDER BY total

2. skills/spend-analyzer/scripts/analyze.py
   - Helper script that takes a query type + parameters
   - Runs the SQL query against the SQLite database
   - Formats results as a clean table
   - Calculates derived metrics (% of total, avg per transaction)

3. skills/spend-analyzer/reference/formatting_guide.md
   - How to format financial summaries for the user
   - Currency formatting rules (CAD, 2 decimal places, negative in red)
   - Table layout standards
   - When to use tables vs prose vs charts

Keep SKILL.md under 3500 tokens.
```

### What makes this skill "agentic":

Notice that the skill instructions include a **decision tree** for choosing
between SQL and vector search. This is the key to agentic RAG — the agent
reads the skill, understands the user's question, and picks the right
retrieval tool. In Phase 4, you'll wire this into LangGraph as actual
tool-calling decisions.

---

## Step 4: Upgrade cashflow-forecaster Skill (~45 min)

### Prompt Claude Code:

```
Upgrade skills/cashflow-forecaster/SKILL.md to a production skill.

This skill predicts future cash flow based on historical patterns.

Requirements for SKILL.md body:
- Method: identify recurring transactions, calculate averages, project forward
- Instructions to separate fixed expenses (same amount monthly) from
  variable expenses (fluctuating amounts)
- Simple projection: next 30/60/90 days based on patterns
- Risk flags: when projected balance goes below a threshold

Create supporting files:

1. skills/cashflow-forecaster/scripts/detect_recurring.py
   - Deterministic script to find recurring transactions
   - Logic: group by description similarity + amount similarity (±10%)
   - Detect frequency: weekly, bi-weekly, monthly, quarterly
   - Output JSON: [{merchant, amount_avg, frequency, next_expected_date}]

2. skills/cashflow-forecaster/scripts/project_cashflow.py
   - Takes recurring transactions + current balance
   - Projects daily balance for next N days
   - Flags dates where balance drops below configurable threshold
   - Output: daily projection table + risk flags

3. skills/cashflow-forecaster/reference/recurring_patterns.md
   - Known recurring patterns in Canadian banking:
     salary (bi-weekly), rent/mortgage (1st or 15th), utilities (monthly),
     subscriptions (monthly), insurance (monthly or quarterly)
   - How to distinguish recurring vs coincidental same-amount transactions

Keep SKILL.md under 3000 tokens.
```

---

## Step 5: Create the Skill Registry (~30 min)

Now tie your skills together so the agent can discover them.

### Prompt Claude Code:

```
Create src/skills/registry.py that manages skill discovery and loading.

This implements the 3-level progressive disclosure pattern:

Level 1 - Discovery:
- Function: discover_skills(skills_dir: str = "skills/") -> list[dict]
  - Scans all subdirectories for SKILL.md files
  - Reads ONLY the YAML frontmatter (name + description)
  - Returns lightweight list: [{name, description, path}]
  - This gets embedded in the agent's system prompt

Level 2 - Loading:
- Function: load_skill(skill_name: str) -> str
  - Reads the full SKILL.md body for the named skill
  - Returns the instruction text
  - This gets injected into context when the agent activates the skill

Level 3 - Resources:
- Function: load_skill_resource(skill_name: str, resource_path: str) -> str
  - Reads a specific file from the skill's directory
  - E.g., load_skill_resource("transaction-categorizer",
    "reference/merchant_patterns.json")
  - Returns file contents as string

- Function: run_skill_script(skill_name: str, script_name: str,
    args: list[str] = None) -> str
  - Executes a script from the skill's scripts/ directory
  - Captures and returns stdout
  - E.g., run_skill_script("statement-parser", "validate_parse.py",
    ["data/mock/rbc_chequing_2025.csv"])

Also:
- Function: format_skill_context(skills: list[dict]) -> str
  - Formats the Level 1 discovery results into a system prompt section:
    "Available skills:\n- statement-parser: Parses bank...\n- ..."
  - This string gets appended to the agent's system prompt in Phase 4

Add a __main__ block that:
1. Discovers all skills and prints the registry
2. Loads one skill and prints its full instructions
3. Loads one reference file and prints it
4. Runs one validation script and prints the output
```

### Run it:

```powershell
python -m src.skills.registry
```

You should see all four skills discovered, one loaded in full, a reference
file read, and a script executed. This is the exact same flow your
LangGraph agent will use in Phase 4.

---

## Step 6: Test Skill Selection (~15 min)

Build a quick test to verify the agent would pick the right skill for
different user queries.

### Prompt Claude Code:

```
Create tests/test_skill_selection.py that validates skill matching.

Use Ollama (llama3.2) to test whether the agent selects the correct
skill for different user queries.

Test cases:
- "Load my RBC bank statement" -> statement-parser
- "What category is each transaction?" -> transaction-categorizer
- "How much did I spend last month?" -> spend-analyzer
- "What will my balance be next month?" -> cashflow-forecaster
- "Compare my grocery spending Jan vs Feb" -> spend-analyzer
- "Import this CSV file" -> statement-parser
- "Are there any unusual charges?" -> spend-analyzer
- "What are my recurring bills?" -> cashflow-forecaster

Method:
1. Load skill registry (Level 1 descriptions only)
2. For each test query, ask the LLM:
   "Given these available skills: {skill_descriptions}
    Which skill should be used for this query: '{query}'?
    Respond with only the skill name."
3. Compare LLM response to expected skill
4. Print PASS/FAIL for each and overall accuracy

Target: 7/8 or better. If below that, the descriptions need tuning.
```

### Run it:

```powershell
python -m tests.test_skill_selection
```

If any skill isn't selected correctly, **tune the description** —
not the instructions. This is the core lesson of context engineering:
the description is the trigger, the instructions are the payload.

---

## Phase 3 Checklist

- [ ] statement-parser skill upgraded with reference files and validation script
- [ ] transaction-categorizer skill upgraded with pattern matching + LLM classification
- [ ] spend-analyzer skill upgraded with SQL query templates and decision tree
- [ ] cashflow-forecaster skill upgraded with recurring detection and projection scripts
- [ ] Skill registry implemented with 3-level progressive disclosure
- [ ] Skill selection test passing 7/8 or better
- [ ] All helper scripts executable and producing clean output
- [ ] Skills directory is well-organized (each skill has SKILL.md + scripts/ + reference/)

---

## What You've Learned in Phase 3

1. **Progressive disclosure** — the 3-level loading pattern that makes
   skills scalable (discovery → instructions → resources)
2. **Description engineering** — the description is the trigger; bad
   descriptions mean your skill never activates
3. **Hybrid deterministic + LLM patterns** — use scripts for what's
   predictable, LLM for what requires reasoning
4. **Skill as contract** — SKILL.md is a contract between you and the
   agent: "when X happens, do Y using Z"
5. **Context budgeting** — keeping SKILL.md bodies under ~4k tokens and
   pushing details into reference files
6. **Skill testing** — validating selection accuracy before building
   the full agent pipeline

---

## Common Issues & Fixes

**Skill not triggering for expected queries**
- 99% of the time it's the description. Make it more specific with
  natural trigger phrases users would actually say.

**Pattern matching script misses obvious merchants**
- Add more patterns. Canadian banks use inconsistent merchant names
  (e.g., "LOBLAWS", "LOBLAWS #1234", "RCSS LOBLAWS"). Use substring
  matching, not exact matching.

**LLM classification returns wrong category**
- Improve the few-shot examples in llm_prompt_template.md
- Add edge case definitions to category_definitions.md

**Script execution fails from skill registry**
- Check file permissions: `chmod +x scripts/*.py`
- Make sure scripts have proper shebang lines or are called via `python`

---

## Next: Phase 4 — Agentic RAG with LangGraph

Phase 4 is the capstone — you'll build the LangGraph agent that ties
everything together. The agent will:
- Read user questions
- Select the right skill
- Decide between vector search and SQL
- Execute multi-step reasoning
- Return formatted answers

This is where all three things you wanted to learn converge:
agentic RAG + skills + coding agent workflow.

Ask me to generate Phase 4 when ready.
