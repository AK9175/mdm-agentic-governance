# 12. Sync Guardian: full input/output spec, tool catalogue, and harness

A complete, implementation-level spec for one agent, worked all the way down —
every input the LLM sees, at every stage, with schemas; the exact prompt
templates; the tool catalogue it can call; the output contract; and how to
build both harnesses (runtime + eval) around it specifically. Companion to
[03-agents.md](03-agents.md), [04-tools-and-mcp.md](04-tools-and-mcp.md),
[05-context-and-data.md](05-context-and-data.md), and
[07-evals-and-harness.md](07-evals-and-harness.md) — this doc makes those
generic descriptions concrete for one agent so the pattern can be copied for
the other three.

## 1. Role recap

**Question owned:** will this data propagate correctly, in every direction it
needs to?

**Not its job:** deciding if two records are duplicates (Entity Resolver),
approving a change (the gateway/steward), judging downstream business impact
(Change Impact).

**Position in the graph:** a LangGraph subgraph node, invoked by the
supervisor for `change_drafted` and `sync_failed` events (rule-routed, no LLM
call to reach it), often running in parallel with Change Impact.

---

## 2. Inputs, stage by stage

Three stages, matching the bucket model in
[05-context-and-data.md](05-context-and-data.md), but split here into what's
**handed to the agent before it starts reasoning** vs. what **the agent
fetches itself mid-reasoning** via tool calls — that distinction matters for
implementation and doesn't come through in the conceptual version.

### 2.1 Bucket 1 — static system prompt (identical every call)

```python
class SyncGuardianSystemPromptConfig(BaseModel):
    role_and_boundary: str
    glossary: dict[str, str]
    systems_and_sor_rule: str
    route_map: dict[str, str]          # generated from pipeline config
    failure_taxonomy: list[str]
    rules_of_engagement: list[str]
    output_contract: str               # Finding / ProposedAction schema, as text
```

Rendered as the actual system prompt text:

```
You are Sync Guardian, one specialist in a data-governance system for an
aerospace manufacturer running Teamcenter (PLM), SAP S/4 (ERP), and Solumina
(MES).

YOUR QUESTION: will this data propagate correctly, in every direction it
needs to?
NOT YOUR JOB: judging if two records are duplicates, approving changes,
assessing downstream business impact. Hand those observations to the
supervisor, don't act on them yourself.

GLOSSARY
  part / revision   – a versioned physical part or assembly; changes go
                       through an approval workflow
  effectivity       – the point a new revision becomes "live"
  crosswalk         – the same real-world entity's ID across PLM/ERP/MES
  golden record     – the agreed master version of an entity
  SoR               – system of record; the one system allowed to originate
                       a given attribute's value

SYSTEMS
  PLM (Teamcenter) — engineering truth. ERP (SAP S/4) — business truth.
  MES (Solumina) — shop-floor truth. Every attribute has exactly one owning
  system (check with sor.get_owner); a change from a non-owning system is a
  governance violation or an explicit change request, never a silent write.

SYNC ROUTE MAP (generated from pipeline config)
  Part/revision:  PLM -> ERP, PLM -> MES
  Material data:  ERP -> PLM
  Change request: ERP -> PLM
  Work order:     ERP -> MES
  Confirmation:   MES -> ERP
  Redline / NCR:  MES -> PLM

FAILURE TAXONOMY
  missing mapping | missing required field | unit mismatch |
  out-of-order revision | locked record | schema change

RULES OF ENGAGEMENT
  - Every finding must cite tool evidence. No evidence, no finding.
  - If data is missing or unclear, say so and lower confidence. Never assume.
  - Use canonical names; look up schema details rather than guessing.
  - You are read-only. Propose actions; never claim something changed.

OUTPUT CONTRACT
  Return exactly one SyncGuardianOutput: a list of Finding objects and a list
  of ProposedAction objects. No free text outside these fields.
```

~550–650 tokens. Paid once per call, identical for every case, every entity.

### 2.2 Bucket 3 (upfront) — what the case builder hands the agent before it reasons

The supervisor's case builder assembles this automatically — no LLM call
needed to produce it, since it's either off the trigger event or cheap
deterministic lookups the pipeline already does at draft time.

```python
class SyncGuardianCaseInput(BaseModel):
    case_id: str
    event: dict                        # the triggering event, verbatim
    crosswalk: dict[str, str]          # {"PLM": ..., "ERP": ..., "MES": ...}
    golden_record_before: dict         # entity state prior to this change
    dry_run_results: list[DryRunResult]  # pre-run by the pipeline at draft time,
                                          # against every target the route map
                                          # says this entity type syncs to
    prior_findings: list[Finding]      # from other agents already in this case
    similar_past_cases: list[SimilarCase]  # top 2-3, via cases.search_similar

class DryRunResult(BaseModel):
    target: str                        # "ERP" | "MES" | ...
    result: Literal["PASS", "FAIL"]
    reason: str | None
    field: str | None
    value: str | None

class SimilarCase(BaseModel):
    case_id: str
    issue: str
    resolution: str
    approved: bool
```

Example, filled in for the bracket scenario:

```json
{
  "case_id": "ECN-2291",
  "event": {
    "event_type": "change_drafted",
    "entity": { "type": "Part", "id": "BRK-10442" },
    "change": {
      "from_revision": "B", "to_revision": "C",
      "attribute": "material_spec",
      "old_value": "AMS 4027", "new_value": "AMS 4911"
    },
    "origin_system": "PLM"
  },
  "crosswalk": { "PLM": "BRK-10442", "ERP": "50010442", "MES": "BRK-10442" },
  "golden_record_before": { "material_spec": "AMS 4027", "revision": "B" },
  "dry_run_results": [
    { "target": "ERP", "result": "FAIL", "reason": "missing mapping", "field": "MATKL", "value": "AMS 4911" },
    { "target": "MES", "result": "PASS", "reason": null, "field": null, "value": null }
  ],
  "prior_findings": [],
  "similar_past_cases": [
    { "case_id": "ECN-1904", "issue": "missing mapping for AMS 4622",
      "resolution": "added mapping row", "approved": true }
  ]
}
```

**Why pre-run the dry run instead of letting the agent call it?** It's cheap,
deterministic, and needed for every case of this event type regardless of
what the agent decides to investigate — running it once at draft time (and
handing the result in) avoids every agent invocation re-triggering the same
check. The agent can still call `pipeline.dry_run` itself, live, for a
scenario the pre-run didn't cover (see 2.3).

### 2.3 Bucket 2 — tools the agent calls itself, mid-reasoning

Everything below is *not* handed to the agent upfront. The agent decides
whether it needs it, calls the tool, gets a result message back, and keeps
reasoning (standard tool-calling loop). This is where diagnosis and
fix-proposal actually happen.

| Tool | Called because | Example call | Example result |
|---|---|---|---|
| `mapping.lookup` | dry run failed with "missing mapping" — confirm and get exact field | `mapping.lookup(attribute="material_spec", source_system="PLM", source_value="AMS 4911", target_system="ERP")` | `{"found": false, "target_field": "MATKL"}` |
| `mapping.find_similar` | no exact row — is there a plausible fix | `mapping.find_similar("AMS 4911")` | `{"suggestions": [{"value": "MG-TI64", "reason": "titanium bar stock, same family"}]}` |
| `schema.describe` | confirm the failing field's ownership/requiredness | `schema.describe(entity="Material", field="material_group")` | field def with per-system technical names |
| `sor.get_owner` | confirm PLM is allowed to originate this attribute | `sor.get_owner("material_spec")` | `{"owner": "PLM"}` |
| `schema.diff` | rule out "the canonical model itself is stale" as a separate cause | `schema.diff(system="MES", entity="ProcessPlan")` | `{"drift_detected": false}` |
| `pipeline.pending_messages` | check nothing's already queued/stuck for this entity | `pipeline.pending_messages(entity="BRK-10442")` | `{"pending": []}` |
| `pipeline.get_message` | inspect a specific stuck message in detail | `pipeline.get_message(id="MSG-88213")` | full message payload + error |
| `pipeline.find_similar_failures` | broaden beyond the 2-3 pre-fetched similar cases if needed | `pipeline.find_similar_failures(reason="missing mapping", entity_type="Material")` | list of past failure records |
| `pipeline.dry_run` (re-called) | **validate a candidate fix before proposing it** — simulate as if `AMS 4911 -> MG-TI64` already existed | `pipeline.dry_run(entity="BRK-10442", target="ERP", proposed_attributes={"material_spec":"AMS 4911"}, assume_mapping={"AMS 4911":"MG-TI64"})` | `{"result": "PASS"}` |
| `mdm.get_golden_record` | re-check current state if the case has been open a while | as in 2.2 of the prior conversation | current entity snapshot |
| `mdm.get_crosswalk` | re-confirm identity mapping if not in the upfront payload (e.g. new entity, no row yet) | `mdm.get_crosswalk(entity="BRK-10442")` | `{"PLM": ..., "ERP": ..., "MES": ...}` |
| `cases.search_similar` | look past the 2-3 pre-fetched cases for a closer match | `cases.search_similar(text="missing material group mapping titanium")` | ranked case list |

The **simulate-before-propose** pattern (last `pipeline.dry_run` row) is the
one worth calling out: instead of just reporting "no mapping exists," Sync
Guardian re-runs the dry run *as if* its proposed fix were already applied,
and only proposes the action once that comes back PASS. This turns "I think
this might fix it" into "I confirmed this fixes it" — raises confidence, and
gives the steward a stronger basis to approve.

---

## 3. Output schema

```python
class Finding(BaseModel):
    summary: str
    evidence: list[str]      # tool calls / results that support it, as strings
    confidence: float        # 0-1

class ProposedAction(BaseModel):
    action: str               # e.g. "add_mapping"
    params: dict
    risk: Literal["low", "medium", "high"]

class SyncGuardianOutput(BaseModel):
    findings: list[Finding]
    proposed_actions: list[ProposedAction]
```

Filled example:

```json
{
  "findings": [
    {
      "summary": "ERP would reject rev C: no material group mapping exists for AMS 4911. MES sync is fine.",
      "evidence": [
        "pipeline.dry_run(ERP) -> FAIL, missing mapping for MATKL",
        "mapping.lookup(AMS 4911, ERP) -> not found",
        "mapping.find_similar -> MG-TI64 (titanium bar stock)",
        "pipeline.dry_run(ERP, assume_mapping=AMS 4911->MG-TI64) -> PASS"
      ],
      "confidence": 0.94
    }
  ],
  "proposed_actions": [
    {
      "action": "add_mapping",
      "params": {
        "attribute": "material_spec",
        "value": "AMS 4911",
        "target_field": "MATKL",
        "proposed_target_value": "MG-TI64"
      },
      "risk": "medium"
    }
  ]
}
```

This is what the supervisor merges with Change Impact's output into the
single case proposal (see [09-worked-example.md](09-worked-example.md)).

---

## 4. Assembled prompt: what the LLM literally sees

**Turn 1 — system message:** the rendered Bucket-1 text from §2.1, plus the
tool definitions (name, description, JSON schema) for every tool in §2.3's
table, passed via the model's native tool-calling interface — not inlined
as text.

**Turn 1 — human message:** the rendered Bucket-3 upfront payload from
§2.2, as structured text:

```
Case ECN-2291. Event: change_drafted on Part BRK-10442, PLM initiated.
Change: material_spec AMS 4027 -> AMS 4911 (rev B -> rev C).

Crosswalk: PLM=BRK-10442, ERP=50010442, MES=BRK-10442.

Golden record before: material_spec=AMS 4027, revision=B.

Dry-run results (pre-run at draft time):
  ERP: FAIL - missing mapping, field MATKL, value AMS 4911
  MES: PASS

Similar past cases:
  ECN-1904: missing mapping for AMS 4622 -> added mapping row (approved)

No prior findings from other agents yet in this case.

Diagnose the ERP failure and propose a fix if one is warranted.
```

**Turns 2..n:** standard tool-call / tool-result exchanges as the agent
works through §2.3, ending with a final assistant turn constrained (via
structured output / forced tool call) to `SyncGuardianOutput`.

---

## 5. Tool catalogue (complete, with descriptions)

Shared tools (every agent gets these — described fully in
[04-tools-and-mcp.md](04-tools-and-mcp.md)):

| Tool | Description | Input | Output |
|---|---|---|---|
| `mdm.get_golden_record` | The master version of an entity | `{entity_id}` | current attribute snapshot |
| `mdm.get_crosswalk` | IDs for one entity across all systems | `{entity_id}` | `{PLM, ERP, MES}` |
| `schema.describe` | Canonical field → technical field, owner, requiredness | `{entity, field}` | field definition |
| `sor.get_owner` | Which system owns an attribute | `{attribute}` | `{owner}` |
| `cases.search_similar` | Past resolved cases (RAG) | `{text}` | ranked case list |

Sync-Guardian-specific tools:

| Tool | Description | Input | Output |
|---|---|---|---|
| `pipeline.dry_run` | Runs the real mapping/validation logic against a target without writing | `{entity, target, proposed_attributes, assume_mapping?}` | `{result: PASS/FAIL, reason?, field?, value?}` |
| `pipeline.get_message` | Full detail on one integration message | `{message_id}` | payload + status + error |
| `pipeline.pending_messages` | Queue state for an entity | `{entity_id}` | list of pending messages |
| `pipeline.find_similar_failures` | Past failures matching a pattern | `{reason, entity_type}` | list of past failure records |
| `mapping.lookup` | Exact value-level translation row, source value → target value | `{attribute, source_system, source_value, target_system}` | `{found, target_field, target_value?}` |
| `mapping.find_similar` | Near-miss suggestions when no exact row exists | `{value}` | ranked suggestions |
| `schema.diff` | Has a system's live schema drifted from the canonical model | `{system, entity}` | `{drift_detected, field?, change?}` |

All tools are **read-only**; only the gateway's tools (`policy.evaluate`,
`gateway.apply`, `gateway.replay`, `gateway.log_decision`) can write, and
Sync Guardian never calls them.

---

## 6. Adding the harness for this agent

Two harnesses, per [07-evals-and-harness.md](07-evals-and-harness.md), made
concrete for Sync Guardian specifically.

### 6.1 Runtime harness — wiring it into the graph

The current prototype (`prototype/governance_graph.py`) stubs
`sync_guardian` as a plain Python function. To make it real:

```python
from langgraph.graph import StateGraph
from langchain_mcp_adapters.client import MultiServerMCPClient

sync_guardian_tools = await MultiServerMCPClient({
    "pipeline": {"url": "https://pipeline-mcp.internal/mcp", "transport": "streamable_http"},
    "mdm":      {"url": "https://mdm-mcp.internal/mcp",      "transport": "streamable_http"},
}).get_tools(server_name=["pipeline", "mdm"])   # namespaced: pipeline.dry_run, mdm.get_crosswalk, ...

sync_guardian_llm = llm.bind_tools(sync_guardian_tools).with_structured_output(SyncGuardianOutput)

def sync_guardian_node(state: CaseState) -> dict:
    case_input = build_sync_guardian_input(state)     # assembles Bucket 1 + Bucket 3
    out = sync_guardian_agent.invoke(case_input)        # runs the tool-call loop internally
    return {
        "findings": [f.model_dump() for f in out.findings],
        "actions":  [a.model_dump() for a in out.proposed_actions],
    }

builder.add_node("sync_guardian", sync_guardian_node)
```

Sync Guardian is its own subgraph (an agent loop, not a single LLM call) so
it can be versioned, tested, and traced independently of the parent case
graph — the parent only ever sees the one node.

### 6.2 Eval harness — testing it in isolation

**Dataset.** Seed from: historical sync-failure logs (labeled with actual
root cause + the fix a steward approved), hand-written edge cases (out-of-
order revisions, echo loops, schema-change scenarios), and — going forward —
every real case's steward decision, logged automatically as a new example.

```python
class SyncGuardianEvalCase(BaseModel):
    case_input: SyncGuardianCaseInput
    expected_trajectory: list[str]        # tool names, e.g. ["mapping.lookup", "mapping.find_similar", "pipeline.dry_run"]
    expected_root_cause: str              # from the failure taxonomy
    expected_action: ProposedAction | None
    steward_decision: Literal["approved", "rejected"] | None
```

**Component evals** — cheapest, run on every change:
- Tool selection: did it call `pipeline.dry_run` at all? (skipping it is a
  hard fail — the taxonomy's whole point is "check before it happens")
- Argument accuracy: right `entity`, `target`, `attribute` passed to each
  call

**Trajectory evals** — via `agentevals`, **subset match mode**: calling an
extra harmless tool (e.g. `schema.diff` out of caution) is fine; skipping
the dry run or the mapping lookup is not.

```python
from agentevals.trajectory.match import create_trajectory_match_evaluator

evaluator = create_trajectory_match_evaluator(
    trajectory_match_mode="subset",
    tool_args_match_mode="exact",
)
```

**Outcome evals:**
- Root-cause correctness: does the returned finding's failure category match
  `expected_root_cause`?
- Proposed-fix correctness: does `proposed_actions[0].params` match the
  steward-approved fix (set comparison on the key fields, not string match)?
- **False-alarm rate**: over cases where the dry run actually passed clean,
  did Sync Guardian still raise a finding? This is tracked as its own
  first-class metric — a specialist that cries wolf gets ignored.

**Running it:**

```python
import pytest
from langsmith import Client

@pytest.mark.parametrize("case", load_eval_dataset("sync_guardian"))
def test_sync_guardian(case: SyncGuardianEvalCase):
    result = sync_guardian_agent.invoke(case.case_input, mock_tools=True)  # against recorded fixtures, not live systems
    assert evaluator(outputs=result.trajectory, reference_outputs=case.expected_trajectory)["score"]
    assert result.output.findings[0].summary_category == case.expected_root_cause
```

Evals run against **mocked MCP servers with recorded tool responses** (not
live SAP/Teamcenter), so they're fast, repeatable, and safe to run in CI on
every prompt, tool-description, or model change — the same gate described
generally in [07-evals-and-harness.md](07-evals-and-harness.md), scoped here
to one agent's own dataset and trajectory expectations.

### 6.3 Minimal path to get something running

1. Start with the component + trajectory evals only (cheap, deterministic,
   no LLM-as-judge) — they catch the majority of regressions (wrong tool,
   wrong args, skipped dry run).
2. Add outcome evals once there's a real steward-decision history to compare
   against.
3. Add false-alarm tracking as soon as the agent runs against any live
   traffic, even in shadow mode (proposals generated but not shown to
   stewards yet) — it's the metric most likely to be quietly bad without
   anyone noticing.
