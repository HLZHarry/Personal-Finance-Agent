# Phase 5: Real Data + Dual LLM Comparison (~3 hours)
## Personal Finance Agent — Learning Project

---

## What You're Building

The final phase. You'll:
1. Swap in your real bank statements and see what breaks
2. Run identical questions through Ollama and Claude API side-by-side
3. Compare quality, speed, and cost
4. Document what you learned for your portfolio / interview prep

---

## Step 1: Prepare Real Data (~30 min)

### 1a. Gather your statements

Download from your online banking:
- RBC chequing export (CSV) — last 3-6 months
- Visa/credit card statements (CSV or PDF) — last 2-3 months
- Mortgage statement (if available as CSV)

Place them in `data/real/`. Remember: this directory is gitignored.

### 1b. Redact if you want extra safety

If you're uncomfortable with any data even locally, create a
quick redaction step:

```
Ask Claude Code:
Create scripts/redact.py that:
1. Reads a CSV from data/real/
2. Replaces account numbers with "XXXX"
3. Optionally masks exact amounts (round to nearest $10)
4. Saves redacted version to data/real/redacted/
5. Keeps dates and descriptions intact (needed for analysis)
```

This is optional — everything stays local. But good practice.

### 1c. Inspect your real data format

Before running the pipeline, manually look at your real CSVs:

```powershell
python -c "
import pandas as pd
df = pd.read_csv('data/real/YOUR_FILE.csv')
print('Columns:', list(df.columns))
print('First 5 rows:')
print(df.head())
print('Shape:', df.shape)
"
```

**Compare the columns to your mock data.** Real RBC exports might have
slightly different column names, date formats, or extra columns you
didn't anticipate. Note the differences — this is the reality of
production data pipelines.

---

## Step 2: Run Pipeline on Real Data (~45 min)

### 2a. Try ingestion and see what breaks

```powershell
python -m src.pipeline --data-dir data/real --reset
```

**Expect failures.** This is the whole point of this step. Common issues:

| Problem | Cause | Fix |
|---------|-------|-----|
| Column name mismatch | Real CSV has "Transaction Date" not "Date" | Update csv_parser.py column mapping |
| Date parse failure | Real format is "MM/DD/YYYY" not "YYYY-MM-DD" | Add date format detection |
| Encoding error | French characters in merchant names (Québec merchants) | Add `encoding='utf-8-sig'` to pd.read_csv |
| PDF extraction garbled | Real PDF uses non-standard layout | Improve LLM parser prompt or try pdfplumber |
| Amount parsing error | Amounts have "$" or "," characters | Strip non-numeric characters before parsing |

### 2b. Fix with Claude Code

For each failure, prompt Claude Code with the exact error:

```
I'm running the pipeline on real bank data and getting this error:
[paste error]

The real CSV has these columns: [paste column names]
The date format looks like: [paste example date]

Fix the parser to handle this format while still supporting the mock data format.
```

Let Claude Code fix, then re-run. Iterate until ingestion completes.

### 2c. Validate with spot checks

```powershell
python -m src.pipeline --data-dir data/real --query-only
```

Ask yourself:
- Does the transaction count match roughly what you expect?
- Are the date ranges correct?
- Do the category totals seem reasonable?
- Pick 5 transactions you remember and verify they parsed correctly

**This manual validation is essential** — the agent can't check its own
data quality. You need to sanity-check at least a handful of results.

---

## Step 3: Dual LLM Comparison Framework (~45 min)

### Prompt Claude Code:

```
Create src/comparison.py that runs the same questions through both
Ollama and Claude API and compares results.

Requirements:

1. Define a list of 10 test questions covering all query types:
   - 3 SQL-type questions (exact numbers)
     e.g., "What was my total spending in [most recent month]?"
     e.g., "How much did I spend on groceries vs dining?"
     e.g., "What are my top 5 largest transactions?"
   - 3 vector search questions (semantic)
     e.g., "What were my most unusual purchases?"
     e.g., "Find transactions related to home improvement"
     e.g., "What discretionary spending could I cut?"
   - 2 multi-step questions (both)
     e.g., "Compare my spending this month vs last month by category"
     e.g., "Am I spending more on dining out recently?"
   - 2 forecasting questions
     e.g., "What are my recurring monthly expenses?"
     e.g., "What will my cash flow look like next month?"

2. For each question, run through the agent twice:
   - Once with provider="ollama"
   - Once with provider="claude"

3. Capture for each run:
   - Answer text
   - Total time (seconds)
   - Routing decision (skill + strategy)
   - Number of LLM calls made
   - Retry count (did it self-correct?)
   - Relevance score from grader

4. Output a comparison report:
   - Side-by-side answers for each question
   - Timing comparison (table)
   - Routing agreement (did both pick the same skill/strategy?)
   - Quality notes (you'll fill these in manually)

5. Save report to docs/llm_comparison.md

Add a __main__ block:
  python -m src.comparison
```

### Run it:

```powershell
python -m src.comparison
```

This will take a while — 10 questions × 2 providers × multiple nodes per
question. Expect ~5-10 minutes total. Ollama will be noticeably slower.

---

## Step 4: Analyze the Results (~30 min)

Open `docs/llm_comparison.md` and review. Here's what to look for:

### Speed comparison

| Metric | Ollama (llama3.2) | Claude API |
|--------|-------------------|------------|
| Avg time per question | Expect 15-30s | Expect 3-8s |
| Slowest question | Usually multi-step | Usually multi-step |
| Fastest question | Direct SQL route | Direct SQL route |

### Quality comparison

For each question, manually rate both answers on:
- **Accuracy** (1-5): Are the numbers correct? Did it use the right data?
- **Completeness** (1-5): Did it answer the full question?
- **Formatting** (1-5): Is the answer well-structured and easy to read?

Add your ratings to the report.

### Routing comparison

Check: did both LLMs make the same routing decisions?
- Same skill selected?
- Same retrieval strategy?
- Same number of retries?

If they diverge, the interesting question is WHO was right. Sometimes
the smaller model makes smarter routing choices because it's more
conservative. Sometimes Claude's stronger reasoning catches nuances
the small model misses.

### Cost estimate

```
Rough Claude API costs for this project:
- Sonnet: ~$3 per million input tokens, ~$15 per million output tokens
- Each question: ~2000 input tokens × 5 nodes = ~10,000 tokens
- 10 questions: ~100,000 tokens ≈ $0.30 input + $0.50 output = ~$0.80

Total API cost for comparison run: roughly $1-2
Total project API cost across all phases: roughly $5-10

Ollama cost: $0 (runs locally)
```

---

## Step 5: Document Your Learnings (~30 min)

### Prompt Claude Code:

```
Create docs/PROJECT_SUMMARY.md that documents this learning project.

Include these sections:

1. Project Overview
   - What we built and why
   - Tech stack diagram

2. Architecture
   - The 5-phase learning approach
   - The dual storage architecture (vector + SQL)
   - The skills-based agent design
   - The LangGraph state machine

3. Key Technical Decisions
   - Why dual storage (ChromaDB + SQLite)
   - Why skills with progressive disclosure
   - Why LangGraph over a simple chain
   - Why hybrid pattern matching + LLM for categorization

4. LLM Comparison Results
   - Summary table of Ollama vs Claude API
   - When to use local vs cloud LLM
   - Quality vs speed vs cost tradeoffs

5. What I Learned
   - Agentic RAG: agent decides retrieval strategy, not developer
   - Skills: description is the trigger, instructions are the payload
   - Context engineering: how to write instructions that make agents reliable
   - Self-correction: grade → rewrite → retry loop
   - LangGraph: state machines with conditional routing and loops

6. What I'd Do Differently / Next Steps
   - Add a Streamlit UI
   - Add more bank format parsers
   - Add cash flow visualization
   - Deploy as a local web app
   - Try more advanced models (llama3.1:70b, Claude Opus)

Make it concise but comprehensive. This is portfolio-ready.
```

---

## Step 6: Final Validation Run (~15 min)

Run the full system end-to-end one last time on real data:

```powershell
# Reset and re-ingest real data
python -m src.pipeline --data-dir data/real --reset

# Run the agent interactively
python -m src.agents.finance_agent
```

Ask 3-5 questions you genuinely care about:
- "What's my average monthly spending?"
- "Where is my money going? Break it down."
- "What recurring subscriptions am I paying for?"
- "Can I afford to spend $500 on [something] this month?"

These should feel like a real personal finance assistant now.

---

## Phase 5 Checklist

- [ ] Real bank statements placed in data/real/
- [ ] Pipeline runs on real data (after fixing format issues)
- [ ] Parsed transactions validated with manual spot checks
- [ ] Comparison framework running 10 questions × 2 providers
- [ ] Timing, routing, and quality metrics captured
- [ ] Manual quality ratings added to comparison report
- [ ] PROJECT_SUMMARY.md documenting architecture and learnings
- [ ] Final interactive session with real data producing useful answers
- [ ] Full project committed to git (data/real/ excluded via .gitignore)

---

## What You've Learned in Phase 5

1. **Real data is messy** — the gap between mock data and production data
   is where most engineering time goes. Column names, date formats,
   encoding, edge cases — all the things mock data doesn't test.
2. **Local vs cloud LLM tradeoffs** — Ollama is free and private but
   slower and less capable. Claude API is fast and smart but costs money
   and sends data over the network. The right choice depends on the use case.
3. **End-to-end validation** — an AI system is only as good as its
   weakest component. Parsing errors cascade into bad embeddings into
   wrong retrieval into wrong answers. Test the full pipeline, not just
   individual pieces.

---

## Project Complete — What You Can Talk About

### In interviews (like your OMERS AI Labs final round):

**Agentic RAG**: "I built a system where the agent autonomously decides
between vector search and SQL queries based on the question type. For
exact numerical questions it routes to SQL, for semantic questions it
uses ChromaDB, and for complex comparisons it uses both. It also has
a self-correction loop — if retrieved results aren't relevant, it
rewrites the query and retries, up to a configurable limit."

**Skills architecture**: "I implemented a progressive disclosure pattern
with three levels — discovery, instructions, and resources. The agent
reads skill descriptions at startup to know what's available, loads
full instructions only when activated, and pulls reference files on
demand. This scales to many skills with near-zero context cost."

**LLM comparison**: "I tested the same agent pipeline with both a local
3B parameter model via Ollama and Claude Sonnet via API. The cloud
model was 3-5x faster and produced more complete answers, but the
local model was surprisingly good at routing decisions. The hybrid
approach — local for parsing, cloud for generation — offered the
best quality-to-cost ratio."

**Context engineering**: "The most important lesson was that skill
descriptions determine whether a skill triggers, not the instructions
inside. I tested skill selection accuracy and iterated on descriptions
until routing hit 90%+ accuracy. Same principle applied to tool
docstrings — they're the LLM's decision surface."

### On your GitHub/portfolio:

Push the repo (with data/real/ gitignored) to your HLZHarry account.
Include the PROJECT_SUMMARY.md as the README. The architecture diagram,
LLM comparison results, and clean code structure make this a strong
portfolio piece showing you can build production-grade AI systems,
not just run notebooks.

---

## Congratulations — You Built an Agentic RAG System

5 phases, ~18 hours, from zero to a working personal finance agent with:
- Multi-format document parsing (CSV + PDF)
- Dual storage (vector + relational)
- 4 custom skills with progressive disclosure
- LangGraph state machine with self-correction
- Dual LLM support (local + cloud)
- Real data validation

That's a complete AI engineering project. Well done, Harry.
