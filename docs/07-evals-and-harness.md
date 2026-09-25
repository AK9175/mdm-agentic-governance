# 7. Harness and evaluations

There are **two** harnesses. Naming both avoids confusion.

## The runtime harness (what agents run in)

- **LangGraph** for orchestration — each agent a subgraph, `PostgresSaver` for
  durable pauses.
- **Tools as MCP servers** — one per system (PLM, ERP, MES, MDM, pipeline). Plain
  LangChain tools would also work for a smaller build.
- **Pydantic** schemas enforce structured outputs.
- **LangSmith** traces every node, tool call, and state change.

## The eval harness (what tests agents)

Core: **pytest + LangSmith datasets/experiments**, plus the `agentevals` package
for agent-specific checks.

- `agentevals` provides **trajectory match** evaluators with configurable match
  modes (strict, unordered, subset, superset) and customizable tool-argument
  matching. Trajectory matching is deterministic, fast, and cost-free (no extra
  LLM call).
- For LangGraph, `agentevals` uses a **graph trajectory** format representing
  trajectories as nodes visited rather than just messages — better for evaluating
  tool calls and interrupts.
- For qualitative checks, add **LLM-as-judge** evaluators with a rubric.

**Critical detail:** evals run against **mocked systems with recorded tool
responses**, not live SAP/Teamcenter. That makes them repeatable, fast, and safe
to run in CI on every prompt/model/tool change.

## What each agent is evaluated on

| Agent | Measured | Method |
|---|---|---|
| Supervisor | Routing accuracy; correct event→case grouping | Exact match vs labeled cases |
| Change Impact | Recall of affected items; argument accuracy | Set comparison vs labeled impact lists |
| Entity Resolver | Duplicate detection precision + recall | Labeled duplicate / non-duplicate pairs |
| Data Quality | Drift detection rate; cleanup-suggestion quality; tool selection, argument accuracy, root-cause correctness and false-alarm rate on its sync-check work | Seeded drift; LLM-as-judge rubric; trajectory match (**subset** mode) and root cause vs labeled cause for sync checks |
| End to end | Proposal matches steward decision; correct approval path | Replay historical cases through the full graph |
| Online (prod) | Steward acceptance rate; false-alarm rate; time-to-resolution | LangSmith monitoring on real traffic |

## Two points worth stressing

1. **Match mode encodes intent.** Data Quality's sync-check trajectory uses
   **subset** matching: calling one extra harmless tool is fine, but *skipping
   the dry run* is not. Strict ordering would fail on harmless variation.
2. **The dataset grows from production.** Every steward approval/rejection becomes
   a new labeled example, so the eval set tracks real cases over time. Seed data
   comes from historical sync-failure logs, known duplicate merges, past change
   tickets, and hand-written edge cases.

## Metrics that matter for *proactive* agents

A proactive agent that cries wolf gets ignored, so the **false-alarm rate** is a
first-class metric alongside precision/recall. "Did we flag things that were
actually fine?" is as important as "did we catch the real problems?"

## The three eval levels (mapping to the resume line)

- **Component evals** — routing accuracy, tool selection, tool-argument accuracy.
- **Trajectory evals** — did the *sequence* of tool calls match an acceptable
  path (catching right-answer-by-luck or inefficient paths).
- **Outcome evals** — did proposals match steward decisions; precision/recall for
  duplicates; false-alarm rate.

Everything runs as a regression gate on every prompt, model, or tool change.
