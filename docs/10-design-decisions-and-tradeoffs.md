# 10. Design decisions and trade-offs

Honest reasoning about the choices, including where reasonable people would
differ. This is the section most worth a second opinion.

## Why agents instead of just rules?

**Rules are the foundation, not the enemy.** The actual checks (does a value have
a mapping, is a required field filled) are deterministic, and the agent runs them
by calling the pipeline's own rule engine as a tool. An LLM should never *guess*
whether a field is empty.

Rules alone have four gaps the agents fill:

1. **Rules only run when data moves** — at sync time, i.e. after approval. Agents
   run the same checks earlier, against a draft.
2. **Rules only catch what someone anticipated.** Across three systems, all
   directions, and dozens of object types, nobody writes rules for every
   combination.
3. **Rules don't know when they're outdated.** After a system upgrade adds a
   required field, old rules keep passing; the agent compares rules against the
   current data model and notices.
4. **Rules detect but don't explain.** A rule says "mapping not found for AMS
   4911." The agent says why, how widespread it is, what the fix probably is, and
   who should approve it.

**And the agent grows the rule set:** when it repeatedly finds a new problem type,
that becomes a new rule. Agent and rules improve each other.

**Fair concession:** a pre-release validation *script* would cover many simple
cases, and that's where you'd start. Agents earn their place in the harder cases —
cross-system root cause, grouping related failures, novel problems, and
plain-language explanation for approvers.

## Is LangGraph necessary?

**No, not strictly.** Most of the system is deterministic; you could build it with
plain Python + a workflow engine (Temporal) + a state table.

**But it's a good fit** for three things it gives out of the box:

- durable **pause/resume** for approvals that take days,
- **state-based routing** between agents,
- independently testable **subgraphs**.

The deterministic parts stay outside the LLM. **If the org already ran Temporal,
using it for orchestration and keeping LangGraph just for agent logic would be
reasonable.** Downsides of LangGraph: an abstraction layer that can complicate
debugging, fast-moving versions, and less maturity than dedicated workflow
engines at very high-volume durability.

## Why question-aligned agents, not system-aligned?

A "SAP agent" / "Teamcenter agent" split looks natural but fails, because nearly
every real problem spans two or three systems. Question-aligned agents get read
access to all systems via shared tools, but own exactly one judgment — smaller
tool sets, focused prompts, independent evals.

**Counterpoint worth considering:** system-aligned *tools* (MCP servers) plus
question-aligned *agents* is exactly the split used here — the two axes aren't in
conflict.

## Why MCP servers, not in-process tools?

Standard interface (reuse across agents/teams), isolated system concerns (creds,
rate limits, translation in one service). **Trade-off:** extra hop + another
service. For a single small app, in-process LangChain tools are simpler and fine.

## Autonomy is earned, not granted

Everything starts suggestion-only. An action type moves to auto-execute only
after its eval metrics and steward approval rate stay high for a sustained
period. This is a policy choice, not a technical constraint.

## Data-boundary / compliance note

Solumina and Teamcenter environments in aerospace often hold export-controlled
(ITAR) data. Model deployment must live within an approved boundary. This is a
real-world constraint that shapes where the LLM can run and which data can leave
the environment.

## Where LLMs are used vs not

| Used (judgment) | Not used (deterministic) |
|---|---|
| Fuzzy entity matching | Validation rules |
| Cross-system root-cause reasoning | Routing of known event types |
| Explaining impact in plain language | All writes (gateway) |
| Ambiguous event classification | Mapping/schema lookups |

## Known limitations / things to challenge

- The dry run must call the **same mapping code/config** as the real integration,
  or the simulation drifts from reality. This is a hard dependency, not a nicety.
- LLM nondeterminism is managed (rules-first routing, structured outputs, no
  writes, evals as a gate) but not eliminated.
- The canonical data model is a significant build in itself; its accuracy bounds
  everything above it.
- Cost/latency of multi-agent runs vs a single agent with many tools is a real
  trade-off; question-aligned agents were chosen partly to keep each agent's tool
  set and context small.
