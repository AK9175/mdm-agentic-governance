# 5. Context and data per agent

## Three layers of context

Every agent's context is organized as:

1. **Shared foundation** — in every agent's system prompt.
2. **Agent-specific context** — for its one job.
3. **Per-case context** — injected at runtime.

### Layer 1: shared foundation (every agent)

- **Role and boundary** — one sentence: the question it owns and what it must not
  do.
- **Compact domain glossary** — 10–15 one-line definitions (part, revision, ECN,
  effectivity, crosswalk, golden record, plant, work order, material group).
- **Three systems in one line each**, plus the SoR rule and that `sor.get_owner`
  checks ownership.
- **Rules of engagement:**
  - Every finding must cite tool evidence. No evidence, no finding.
  - If data is missing/unclear, say so and lower confidence. Never assume.
  - Use canonical names; look up schema details rather than guessing.
  - Read-only. Propose actions; never claim something changed.
- **Output contract** — the `Finding` / `ProposedAction` schemas.

### Layer 2: agent-specific

| Agent | Minimum to work | Makes it better |
|---|---|---|
| Supervisor | Specialists + their questions, routing rules, case-state schema | Ambiguous-event examples, event-linking rules, second-routing rules |
| Sync Guardian | Which targets each object syncs to (all directions), how to read dry runs, failure categories | Error→root-cause patterns per system, blast-radius estimation, past failures + fixes |
| Change Impact | What "depends on a revision" means + which tool answers each | Interchangeability rules, effectivity patterns, lead-time/cost signals |
| Entity Resolver | What makes two parts the same, match thresholds | False-positive traps, abbreviation dictionary, labeled past merges |
| Data Quality | The rules it can run, the SoR matrix | Benign vs harmful drift, noisy fields to deprioritize, recurring NCR patterns |

Most quality gains come from the "makes it better" column — **worked examples and
patterns**, not more instructions.

### Layer 3: per-case (runtime)

- The triggering event, crosswalk IDs, and any prior agents' findings.
- Relevant **schema slices** only (via `schema.describe`), never whole schemas.
- Two or three **similar past cases** (via `cases.search_similar`), including what
  the steward decided.

## Core vs runtime data (the token-efficiency split)

A key optimization: don't preload the big, stable stuff. Make it look-up-able.

| Bucket | Examples | Where it lives | Fetched when |
|---|---|---|---|
| **Core, always loaded** | Route map, failure taxonomy, glossary, dry-run reading rules | Static prompt | Once at startup |
| **Core, looked up** | Mapping tables, schemas, field ownership | Behind tools | Only the slice a case needs |
| **Runtime** | Event, crosswalk IDs, changed values, dry-run results, queue state, prior findings, similar cases | Injected per case | Every run |

**Rule of thumb:** small and universal → prompt; large but stable → tool lookup;
case-specific → runtime injection.

Preloading the mapping tables into the prompt would burn thousands of tokens on
data a case doesn't use and *lower* accuracy (the model must wade through
irrelevant rows). Keeping them behind a tool means paying only for the handful of
mappings actually checked.

## Is this just RAG?

No — the pieces belong in different mechanisms, and mixing them up is dangerous:

- **In the prompt:** small, stable, needed every case (sync map, failure
  taxonomy, glossary). The sync map should be **generated from pipeline config**,
  not hand-written, so it can't drift.
- **Through tools:** exact facts that must be correct and may change (mappings,
  schemas, live data). Exact lookup, not similarity.
- **Through RAG:** large, unstructured knowledge where *similarity* is the point
  (past incidents, runbooks, docs).

**Why not put mappings in RAG?** A similarity search for `AMS 4911` might return
rows for `AMS 4928` and `AMS 4027` because they look alike, and the agent could
wrongly conclude a mapping exists. "Is there a row for this value?" needs an exact
lookup that definitively finds it or doesn't. That's a tool.

## Worked example: Sync Guardian's data buckets

**Core, in prompt (loaded once):**
```
Sync route map (generated from pipeline config):
  Part/revision:  PLM → ERP, PLM → MES
  Material data:  ERP → PLM
  Change request: ERP → PLM
  Work order:     ERP → MES
  Confirmation:   MES → ERP
  Redline / NCR:  MES → PLM
Failure taxonomy: missing mapping · missing required field · unit mismatch ·
  out-of-order revision · locked record · schema change
```

**Core, looked up (only the slice used):** `mapping.lookup("AMS 4911")`,
`schema.describe(entity, system)`, `sor.get_owner(attribute)`.

**Runtime (every case):** the event, crosswalk IDs, the changed attribute values,
the dry-run results per target, queue state for this part, prior findings,
similar past failures.
