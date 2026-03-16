# Phase 4: Agentic RAG with LangGraph (~5 hours)
## Personal Finance Agent — Learning Project

---

## What You're Building

A LangGraph state machine that:
1. Receives a user question about their finances
2. Routes to the right skill based on the question
3. Decides HOW to retrieve data (vector search, SQL, or both)
4. Executes multi-step reasoning (retrieve → grade → rewrite → re-retrieve if needed)
5. Generates a formatted answer

This is the capstone — everything from Phases 1-3 converges here.

---

## Key Concept: Why LangGraph, Not a Simple Chain?

A LangChain chain is linear: Input → Retrieve → Generate → Output.
If retrieval returns garbage, you get a garbage answer.

LangGraph is a **state machine with loops**. It can:
- **Self-correct**: "These retrieved docs aren't relevant, let me rewrite the query"
- **Branch**: "This is a number question, use SQL. That's a semantic question, use vector search"
- **Loop**: "I need more context, let me retrieve again with different parameters"

Your finance agent needs all three. "How much did I spend on groceries?"
requires SQL. "What were my impulse purchases?" requires vector search.
"Compare my spending habits between winter and summer" requires both +
multi-step reasoning.

---

## Architecture Overview

```
User Question
      │
      ▼
┌─────────────┐
│   Router     │ ← Reads skill descriptions, picks skill + retrieval strategy
└─────┬───────┘
      │
      ▼
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│ Vector Search│     │  SQL Query    │     │  Skill Script │
│ (ChromaDB)  │     │  (SQLite)     │     │  (pattern_cat) │
└─────┬───────┘     └──────┬───────┘     └──────┬───────┘
      │                    │                     │
      └────────┬───────────┘─────────────────────┘
               ▼
        ┌─────────────┐
        │   Grader     │ ← Are the retrieved results relevant enough?
        └─────┬───────┘
              │
         Yes? ▼         No?
        ┌──────────┐   ┌──────────────┐
        │ Generate  │   │ Rewrite Query│ ──loop back to retrieval
        │ Answer    │   └──────────────┘
        └──────────┘
```

---

## Step 1: Define the Agent State (~30 min)

The state is the "memory" that flows through every node in the graph.

### Prompt Claude Code:

```
Create src/agents/state.py that defines the LangGraph state for our
finance agent.

Use TypedDict with the following fields:
- messages: list of chat messages (use Annotated with add_messages)
- question: the user's original question (str)
- rewritten_question: if the query was rewritten for better retrieval (str)
- selected_skill: which skill the router picked (str)
- retrieval_strategy: "vector", "sql", "both", or "none" (str)
- retrieved_docs: list of retrieved document strings
- sql_results: optional pandas DataFrame as string (for SQL query results)
- skill_context: the loaded SKILL.md instructions (str)
- generation: the final answer (str)
- relevance_score: how relevant were the retrieved docs (float, 0-1)
- retry_count: number of retrieval retries (int, max 2)

Import from:
- langgraph.graph import MessagesState
- langgraph.graph.message import add_messages
- typing import Annotated, TypedDict, Optional

Keep it clean and well-documented.
```

---

## Step 2: Define the Agent Tools (~45 min)

Tools are functions the agent can call. Each tool wraps one of your
Phase 2/3 components.

### Prompt Claude Code:

```
Create src/agents/tools.py that defines LangGraph tools wrapping our
existing components.

Use the @tool decorator from langchain_core.tools.

Create these tools:

1. vector_search(query: str, n_results: int = 10) -> str
   - Wraps FinanceVectorStore.search()
   - Returns formatted results as a string
   - Docstring: "Search financial transactions by semantic meaning.
     Good for: finding specific types of purchases, unusual transactions,
     or transactions matching a description."

2. sql_query(query_type: str, start_date: str = None,
             end_date: str = None, category: str = None) -> str
   - Wraps FinanceSQLStore with pre-built query types:
     "period_summary", "category_breakdown", "top_expenses",
     "monthly_trend", "category_comparison"
   - Returns formatted table as string
   - Docstring: "Query financial data with exact calculations.
     Good for: totals, averages, counts, comparisons between periods,
     category breakdowns. Use this over vector_search when the user
     asks for specific numbers."

3. run_categorizer(filepath: str = None) -> str
   - Wraps the pattern categorization script
   - Returns categorization summary
   - Docstring: "Categorize transactions into spending categories.
     Use when transactions need category labels."

4. detect_recurring(months: int = 3) -> str
   - Wraps the recurring transaction detection script
   - Returns list of recurring transactions
   - Docstring: "Detect recurring transactions like subscriptions,
     bills, and regular payments. Use for cash flow forecasting."

5. load_skill_instructions(skill_name: str) -> str
   - Wraps the skill registry's load_skill()
   - Returns full SKILL.md content
   - Docstring: "Load detailed instructions for a specific skill.
     Available skills: statement-parser, transaction-categorizer,
     spend-analyzer, cashflow-forecaster"

CRITICAL: Tool docstrings matter enormously. The LLM reads them to
decide which tool to call. Write them like you're explaining to a
smart colleague which tool to use when.

Add a function get_all_tools() that returns the list of all tools.
```

### Why docstrings matter here:

This is the same principle as skill descriptions — the LLM reads the
docstring to decide whether to call the tool. A vague docstring means
the agent picks the wrong tool. A precise one means it routes correctly.

---

## Step 3: Build the Graph Nodes (~90 min)

This is the core of the agent. Each node is a function that transforms state.

### Prompt Claude Code:

```
Create src/agents/nodes.py with the following LangGraph node functions.

Each function takes state (AgentState) and returns a partial state update.

1. route_question(state) -> dict:
   - Reads the user's question from state
   - Uses the LLM to decide:
     a) Which skill to activate (from skill registry descriptions)
     b) Which retrieval strategy to use (vector/sql/both/none)
   - Uses structured output (Pydantic model) to force the LLM to return:
     {"skill": "spend-analyzer", "strategy": "sql", "reasoning": "..."}
   - Returns: {"selected_skill": ..., "retrieval_strategy": ...}
   - Use the LLM provider from .env (DEFAULT_LLM setting: ollama or claude)

2. load_skill(state) -> dict:
   - Loads the full SKILL.md for the selected skill
   - Returns: {"skill_context": loaded_instructions}

3. retrieve_vector(state) -> dict:
   - Calls vector_search tool with the question (or rewritten_question)
   - Returns: {"retrieved_docs": results}

4. retrieve_sql(state) -> dict:
   - Analyzes the question to determine query_type and parameters
   - Calls sql_query tool
   - Returns: {"sql_results": results}

5. retrieve_both(state) -> dict:
   - Calls both vector_search and sql_query
   - Combines results
   - Returns: {"retrieved_docs": ..., "sql_results": ...}

6. grade_retrieval(state) -> dict:
   - Uses the LLM to evaluate if retrieved results are relevant
   - Prompt: "Given this question: {question}, are these results
     relevant enough to answer? Score 0-1."
   - Returns: {"relevance_score": float}

7. rewrite_question(state) -> dict:
   - If relevance_score < 0.5, rewrites the question for better retrieval
   - Uses LLM: "The original question was: {question}. The retrieval
     returned poor results. Rewrite the question to get better results."
   - Increments retry_count
   - Returns: {"rewritten_question": ..., "retry_count": state["retry_count"] + 1}

8. generate_answer(state) -> dict:
   - Combines: skill_context + retrieved_docs + sql_results + question
   - Uses LLM to generate a comprehensive answer
   - Prompt includes the skill instructions for formatting guidance
   - Returns: {"generation": answer_text}

For the LLM, create a helper function get_llm(provider: str = None):
  - If provider == "ollama": return ChatOllama(model="llama3.2")
  - If provider == "claude": return ChatAnthropic(model="claude-sonnet-4-20250514")
  - Default: read from .env DEFAULT_LLM setting
  This lets us swap LLMs easily for Phase 5 comparison.
```

### Key learning: structured output for routing

The route_question node uses **structured output** — it forces the LLM to
return a specific JSON schema instead of freeform text. This is critical
for production agents because you can't parse "I think we should use the
spend analyzer" reliably, but you CAN parse `{"skill": "spend-analyzer"}`.

---

## Step 4: Build the Graph with Conditional Edges (~60 min)

Now wire the nodes together into a LangGraph StateGraph.

### Prompt Claude Code:

```
Create src/agents/finance_agent.py that assembles the full LangGraph agent.

Requirements:

1. Import all nodes from nodes.py and state from state.py

2. Define conditional edge functions:

   route_retrieval(state) -> str:
     - If strategy == "vector": go to "retrieve_vector"
     - If strategy == "sql": go to "retrieve_sql"
     - If strategy == "both": go to "retrieve_both"
     - If strategy == "none": go to "generate_answer" (direct LLM response)

   check_relevance(state) -> str:
     - If relevance_score >= 0.5: go to "generate_answer"
     - If relevance_score < 0.5 AND retry_count < 2: go to "rewrite_question"
     - If retry_count >= 2: go to "generate_answer" (best effort)

3. Build the StateGraph:

   START -> route_question -> load_skill -> [conditional: route_retrieval]
   
   retrieve_vector -> grade_retrieval -> [conditional: check_relevance]
   retrieve_sql -> grade_retrieval -> [conditional: check_relevance]
   retrieve_both -> grade_retrieval -> [conditional: check_relevance]
   
   rewrite_question -> [conditional: route_retrieval]  (loop back)
   
   generate_answer -> END

4. Compile the graph with a MemorySaver checkpointer for conversation memory

5. Create a run_agent(question: str, provider: str = None) function:
   - Invokes the graph with the question
   - Returns the generation
   - Prints each node as it executes (for learning/debugging)

6. Create an interactive_mode() function:
   - REPL loop: user types questions, agent responds
   - Special commands: /quit, /reset, /provider ollama|claude, /debug on|off
   - In debug mode, print the full state after each node

Add a __main__ block that runs interactive_mode().
```

### Run it:

```powershell
# Make sure Ollama is running
ollama serve

# In another terminal — run the agent!
python -m src.agents.finance_agent
```

Try these questions in order (they test different paths through the graph):

```
> How much did I spend on groceries last month?
  (Should route to: spend-analyzer → SQL)

> What were my biggest impulse purchases?
  (Should route to: spend-analyzer → vector search)

> Compare my dining spending January vs February
  (Should route to: spend-analyzer → both)

> What are my recurring monthly bills?
  (Should route to: cashflow-forecaster → SQL + skill script)

> Load my bank statement from data/mock/rbc_chequing_2025.csv
  (Should route to: statement-parser → skill script)
```

### Debug if routing is wrong:

Turn on debug mode (`/debug on`) and check:
- Does route_question pick the right skill?
- Does it pick the right retrieval strategy?
- Are the retrieved results relevant?
- Does the grader score them appropriately?

If the router picks wrong tools, tune the tool docstrings (Step 2).
If the router picks wrong skills, tune the skill descriptions (Phase 3).

---

## Step 5: Add the Self-Correction Loop (~30 min)

Test the self-correction loop specifically.

### Prompt Claude Code:

```
Create tests/test_self_correction.py that validates the agent's
ability to self-correct on poor retrieval.

Test cases:

1. Ambiguous query test:
   - Ask: "that thing I bought at the store"
   - This should trigger low relevance → rewrite → better query → answer
   - Verify retry_count > 0 in final state

2. Wrong strategy test:
   - Ask a numerical question that the vector search can't answer well
   - Verify the agent eventually gets a reasonable answer

3. Max retry test:
   - Ask something truly unanswerable from the data
   - Verify it stops after 2 retries and gives a best-effort answer
   - Verify retry_count == 2

For each test:
- Run the agent with debug output
- Print the routing decisions, retrieval results, and relevance scores
- Print PASS/FAIL based on whether the agent self-corrected appropriately
```

---

## Step 6: Visualize the Graph + Run Demo (~15 min)

### Prompt Claude Code:

```
Add a visualize_graph() function to finance_agent.py that:
1. Uses graph.get_graph().draw_mermaid() to generate a Mermaid diagram
2. Saves it to docs/agent_graph.md
3. Also prints the ASCII representation to terminal

Also create a simple run_demo() function that:
1. Runs 5 pre-defined questions through the agent
2. Prints each question, the routing decision, and the answer
3. Prints timing for each question (how long the agent took)
4. Prints a summary: average time, most common retrieval strategy, etc.
```

Run the demo:
```powershell
python -c "from src.agents.finance_agent import run_demo; run_demo()"
```

---

## Phase 4 Checklist

- [ ] Agent state defined with all necessary fields
- [ ] 5 tools created with precise docstrings
- [ ] 8 graph nodes implemented (route, load_skill, 3x retrieve, grade, rewrite, generate)
- [ ] Conditional edges wiring routing and self-correction logic
- [ ] Graph compiles and runs without errors
- [ ] Interactive mode working with REPL loop
- [ ] SQL questions route to SQL tool correctly
- [ ] Semantic questions route to vector search correctly
- [ ] Complex questions use both retrieval strategies
- [ ] Self-correction loop triggers on low relevance and rewrites query
- [ ] Max retry limit prevents infinite loops
- [ ] Debug mode shows full state transitions
- [ ] Demo runs 5 questions successfully with timing

---

## What You've Learned in Phase 4

1. **LangGraph state machines** — nodes, edges, conditional routing, and how
   state flows through the graph
2. **Agentic RAG in practice** — the agent DECIDES how to retrieve, not you.
   It picks between vector search, SQL, or both based on the question.
3. **Self-correction loops** — grade retrieval results, rewrite queries,
   retry with limits. This is what makes it "agentic" vs just a pipeline.
4. **Tool design** — docstrings are the tool's "description" just like
   SKILL.md descriptions are the skill's trigger. Same principle, different layer.
5. **Structured output** — forcing the LLM to return JSON schemas for
   reliable routing decisions
6. **LLM abstraction** — the get_llm() helper lets you swap between
   Ollama and Claude with one parameter change (prep for Phase 5)

---

## Common Issues & Fixes

**Router always picks the same skill**
- Check your skill descriptions — they might overlap too much
- Add negative examples: "Do NOT use this for numerical calculations"

**Agent loops infinitely**
- Check retry_count logic in check_relevance conditional edge
- Make sure rewrite_question increments retry_count
- Verify max retry is set to 2

**SQL tool returns errors**
- Check that the SQLite database was populated in Phase 2
- Run `python -m src.pipeline --query-only` to verify SQL works

**Vector search returns irrelevant results**
- Check that ChromaDB was populated in Phase 2
- Try broader queries — ChromaDB with small datasets can be noisy

**Ollama is slow**
- llama3.2 (3B) should respond in 2-5 seconds per node
- If slower, check `ollama ps` — make sure only one model is loaded
- Each node calls the LLM separately, so 4-5 nodes = 10-25 seconds total

**Claude API errors**
- Check your ANTHROPIC_API_KEY in .env
- Verify you have API credits on console.anthropic.com

---

## Next: Phase 5 — Real Data + Dual LLM Comparison

The final phase. You'll swap in real bank statements, run the same
questions through both Ollama and Claude API, and compare quality,
speed, and cost.

Ask me to generate Phase 5 when ready.
