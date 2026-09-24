# 2. Architecture

## Layered view

The agents sit **on top of** the existing integration layer. They never replace
the pipes; they observe events, read state through tools, and produce proposals
that a gateway executes.

```
┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│ Teamcenter  │◄─►│  SAP S/4    │◄─►│  Solumina   │
│    PLM      │   │    ERP      │   │    MES      │
└──────┬──────┘   └──────┬──────┘   └──────┬──────┘
       │                 │                 │
┌──────┴─────────────────┴─────────────────┴──────┐
│  Integration + event layer                       │
│  middleware, change data capture, sync telemetry │
└───────────────────────┬──────────────────────────┘
                        │
┌───────────────────────┴──────────────────────────┐
│  MDM hub                                          │
│  golden record · ID crosswalk · SoR matrix        │
└───────────────────────┬──────────────────────────┘
                        │
┌───────────────────────┴──────────────────────────┐
│  Agentic governance layer (LangGraph)             │
│  supervisor + specialist agents                   │
└───────┬───────────────┬───────────────┬───────────┘
        │               │               │
   ┌────┴────┐    ┌──────┴──────┐   ┌────┴─────┐
   │ Action  │    │  Steward    │   │  Evals   │
   │ gateway │    │  approvals  │   │ + traces │
   └────┬────┘    └─────────────┘   └──────────┘
        │
        └──── writes go back through the integration layer only
```

### What each layer does

**Integration + event layer.** Two jobs: carry data through the existing
middleware, and publish events the agents subscribe to. Events are of two kinds:
*business events* (item entered release workflow, ECN created, material created,
NCR raised) and *integration telemetry* (message failed, queue latency rising).
The business-event stream is what makes proactivity possible — agents can react
to intent before data actually moves.

**MDM hub.** Holds the golden record, the **ID crosswalk** (PLM part = ERP
material = MES part), the **system-of-record (SoR) matrix**, and the canonical
data model. See [06-data-models.md](06-data-models.md).

**Agentic governance layer.** The supervisor and specialists. See
[03-agents.md](03-agents.md).

**Action gateway.** The only component that writes. See below.

## The system-of-record matrix

The concept that makes bidirectional sync governable. Each attribute has exactly
**one owning system**:

| Attribute group | Owner |
|---|---|
| Part number, revision, description, engineering UoM | PLM |
| Plant extensions, procurement type, MRP/cost data, material group | ERP |
| As-built serials, execution status, actual consumption | MES |

Any change to an attribute from a non-owning system is either a governance
violation or an explicit change request — never a silent overwrite. Every agent
decision refers back to this matrix.

## The central principle: agents propose, the gateway disposes

**No LLM agent holds write credentials to any system.** Agents produce
structured proposals. A deterministic action gateway:

1. validates each proposal against policy,
2. assigns a risk tier,
3. routes high-risk proposals to human approval,
4. enforces idempotency (every action has a key, so retries can't double-write),
5. writes an audit log,
6. executes through the existing integration middleware.

This single decision answers most "what if the agent hallucinates?" questions:
a hallucinated proposal is still just a proposal, checked by deterministic policy
and (when risky) a human, before anything is written.

## Bidirectional hazards and how the design handles them

| Hazard | Handling |
|---|---|
| **Echo loops** (A updates B, B emits event, syncs back to A) | Every event carries an origin system + correlation ID; agents ignore changes whose origin matches the target |
| **Conflicting concurrent updates** | SoR matrix resolves most (only the owner's value wins); the rest become a steward case |
| **Out-of-order arrival** (rev C before rev B) | Events sequenced per entity (partitioned by golden-record ID); out-of-order arrivals held, not applied |
| **Duplicate execution** | Idempotency key on every gateway action |

## Risk tiers

The gateway assigns each proposed action a tier, which decides the path:

- **Low risk, high confidence** → auto-execute (e.g. adding a missing unit
  conversion that the source system already implies).
- **Medium / high risk** → human approval via a LangGraph interrupt (e.g.
  cancelling a purchase order, merging two parts, changing effectivity).

Autonomy is **earned per action type**: an action type moves from
approval-required to auto-execute only after its eval metrics and steward
approval rate stay high for a sustained period.
