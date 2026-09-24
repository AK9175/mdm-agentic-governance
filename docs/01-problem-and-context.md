# 1. Problem and context

## The setting

An aerospace supplier manufactures parts and assemblies for aircraft. Building a
finished part depends on several disparate software systems that each own a
different slice of the truth and must communicate constantly.

### The three systems

**PLM — Product Lifecycle Management (Teamcenter).** Version control for
physical parts and assemblies. It stores everything needed to build each part:
engineering drawings, specifications, materials, and the full revision history.
Think of it as Git for hardware — parts have revisions, and changes move through
an approval workflow.

**ERP — Enterprise Resource Planning (SAP S/4).** The business side. It manages
purchasing, inventory and stock, costing, and planning for the materials needed
to build a part.

**MES — Manufacturing Execution System (Solumina).** The shop floor. Workers use
it to see specifications and quantities and to actually manufacture the parts,
following step-by-step build and inspection instructions. It also records what
was actually built (the "as-built" record).

These systems are disparate but complementary: each is essential to producing
the final part, and they must stay in agreement.

## Why integration is hard

The systems don't share a database. To keep them in sync, **integration
pipelines** copy data between them based on rules built around each system's data
model and the purpose of each object type.

Crucially, syncs are **not one-directional**. Data flows in every direction:

| Direction | Example of what flows |
|---|---|
| PLM → ERP | Released parts become material masters; EBOM → MBOM; engineering changes |
| ERP → PLM | Assigned material numbers, procurement data, ERP-initiated change requests |
| PLM → MES | Parts, BOM, process plans, quality requirements, drawings |
| MES → PLM | Redlines on instructions, nonconformances pointing to design issues, as-built config |
| ERP → MES | Production orders, material availability, serial/lot assignments |
| MES → ERP | Order confirmations, material consumption, scrap, completions |

Each sync involves **translating between different data models** — different IDs,
field names, and allowed values. Translation is where things break.

## How drift happens

The systems are supposed to always hold the same state. But faulty integrations
cause that state to drift:

- **A sync fails.** A part is released in the PLM, but ERP material creation
  fails on a validation error (a missing mapping, an unfilled required field, a
  unit mismatch). Someone has to dig through logs to find out why.
- **Duplicate entities.** The same physical part gets created twice under
  slightly different IDs or descriptions, splitting inventory and procurement.
- **Silent divergence.** A value is edited in a system that doesn't own it, and
  the systems quietly stop matching with no error at all.

Once the systems drift, companies hire data cleanup or migration people to force
them back into the same state. This is slow, expensive, and recurring — it piles
up as technical debt.

## The assignment

Build a **data governance solution for the integration pipelines** that prevents
drift instead of cleaning it up afterward. The rest of this repo describes an
agentic approach to that problem.

## Framing for different audiences

The same system can be described at different levels depending on the listener:

- **Non-technical:** "Three departments keep their own records — a recipe book, a
  purchasing system, and kitchen instruction cards. When one changes, the others
  must agree. AI assistants catch mismatches before they cause waste."
- **Technical but domain-new:** "A distributed data-consistency problem across
  three heterogeneous systems of record, with bidirectional sync and
  schema translation. Agents do pre-commit validation, blast-radius analysis,
  and entity resolution."
- **Domain expert:** the full PLM/ERP/MES account above.
