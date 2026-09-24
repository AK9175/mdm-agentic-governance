# 3. Agents

## Boundary principle: one question per agent

Agents are divided by **the question each one owns**, not by source system. A
"SAP agent" or "Teamcenter agent" looks intuitive but breaks down, because nearly
every real problem spans two or three systems. Question-aligned agents each get
read access to all systems through shared tools, but own exactly one kind of
judgment.

| Agent | Owns the question | Proactive work | Reactive work | Not its job |
|---|---|---|---|---|
| **Supervisor** | What kind of case is this, and who handles it? | Groups related events into one case per entity | Routes failures | Making any data judgment itself |
| **Sync Guardian** | Will this data propagate correctly, in every direction? | Pre-flight dry run of mappings before release | Root-cause diagnosis of failed syncs, replay proposals | Deciding if two records are duplicates |
| **Change Impact** | What will this change break downstream? | Impact forecast when a change is drafted | Explaining a failure caused by a change | Approving the change |
| **Entity Resolver** | Is this the same thing as something that exists? | Search-before-create on new part/material requests | Merge/unmerge proposals, crosswalk repair | Fixing attribute values |
| **Data Quality** | Is this record correct and complete? | Continuous drift scans, pattern detection | Cleanup suggestions with evidence | Deciding sync timing or routing |

> **Note on Change Impact vs the resume line.** Earlier framing sometimes folded
> "change impact" into the other three agents. Treating it as its own agent is a
> design choice: impact analysis is a distinct judgment (what *depends on* the old
> state) from sync validation (will the *new* state flow). Reviewers may reasonably
> merge or split these differently.

## Boundary rules

- **Agents never talk to each other directly.** They read/write a shared, typed
  **case state** object; only the supervisor decides the next hop.
- **Each specialist is its own LangGraph subgraph** with its own tools and
  prompts, so it can be versioned, tested, and rolled back independently.
- **A case can visit several specialists.** A sync failure might turn out to be
  caused by a duplicate: Sync Guardian hands back to the supervisor, which routes
  to Entity Resolver.

## The supervisor

Rules first, LLM second. A known event type (`sync_failed`, `change_drafted`,
`create_requested`) maps straight to a specialist via a routing rule — no LLM
call, which keeps routing cheap, fast, and easy to test. The LLM is only invoked
for ambiguous events that no rule covers.

The supervisor also:

- opens one **case** per affected entity and links related events into it,
- decides when a case needs a second specialist,
- merges specialists' findings into a single proposal.

## Runtime graph

```
                    ┌─────────────┐
                    │  Triggers   │  business events, sync telemetry, schedules
                    └──────┬──────┘
                    ┌──────┴──────────┐
                    │ Case builder +  │  rules first, LLM for ambiguity
                    │  supervisor     │
                    └──────┬──────────┘
        ┌────────────┬─────┴──────┬─────────────┐
   ┌────┴────┐  ┌────┴────┐  ┌────┴────┐   ┌─────┴────┐
   │  Sync   │  │ Entity  │  │  Data   │   │  Change  │
   │ Guardian│  │Resolver │  │ Quality │   │  Impact  │
   └────┬────┘  └────┬────┘  └────┬────┘   └─────┬────┘
        └────────────┴─────┬──────┴──────────────┘
                    ┌──────┴──────────┐
                    │ Proposal +      │  risk tier, confidence, evidence
                    │ policy check    │
                    └──────┬──────────┘
                 ┌─────────┴─────────┐
            ┌────┴─────┐       ┌─────┴──────┐
            │  Auto-   │       │  Steward   │  LangGraph interrupt
            │ execute  │       │  approval  │
            └────┬─────┘       └─────┬──────┘
                 └─────────┬─────────┘
                    ┌──────┴──────┐
                    │   Action    │  idempotent writes, audit, rollback
                    │   gateway   │
                    └─────────────┘
```

## Agent internals

Every specialist follows the same loop inside its subgraph: read case state →
decide which tools to call → call them → reason over results → return a
**structured output** (never free text). The structured shape lets the
supervisor, policy check, and evals all read it reliably.

```python
class Finding(BaseModel):
    summary: str            # plain-language finding
    evidence: list[str]     # tool results that support it
    confidence: float

class ProposedAction(BaseModel):
    action: str             # e.g. "add_mapping"
    params: dict
    risk: Literal["low", "medium", "high"]
```
