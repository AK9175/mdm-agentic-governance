# Agentic Data Governance for Manufacturing MDM

A design write-up for an agentic data governance layer that sits on top of the
integration pipelines connecting three enterprise systems in an aerospace
manufacturing environment:

- **PLM** (Teamcenter) — engineering truth: parts, revisions, BOMs, specs, changes
- **ERP** (SAP S/4) — business truth: inventory, purchasing, planning, classification
- **MES** (Solumina) — shop-floor truth: work orders, build instructions, as-built records

These systems must stay in sync. Faulty integrations cause the systems to drift
apart, which is normally fixed by expensive manual data cleanup and migration
work. This project replaces that reactive cleanup with a team of AI agents that
catch problems **before** they cause drift.

> **Status: design + minimal prototype.** This repository is a written
> architecture plus a small runnable LangGraph example on synthetic data. It is
> intended for review and discussion, not as production code. All part numbers,
> material codes, and scenarios are invented for illustration.

## The core idea

Instead of waiting for a sync to fail and then cleaning up, agents watch every
change and answer specific questions before the change is committed:

- **Will this data actually flow correctly into the other systems?** (Sync Guardian)
- **What existing inventory, orders, and production does this change affect?** (Change Impact)
- **Does this thing already exist?** (Entity Resolver)
- **Is this record correct and complete?** (Data Quality)

A supervisor routes each case; agents only ever *propose*; a deterministic
gateway is the only component that writes, with human approval for anything
risky.

## How to read this repo

| Doc | What's in it |
|---|---|
| [01-problem-and-context.md](docs/01-problem-and-context.md) | The domain, the three systems, why drift happens |
| [02-architecture.md](docs/02-architecture.md) | Layered architecture, bidirectional flows, the propose/dispose principle |
| [03-agents.md](docs/03-agents.md) | Agent boundaries, responsibilities, and the runtime graph |
| [04-tools-and-mcp.md](docs/04-tools-and-mcp.md) | Tool catalogue, the MCP server layer, wire-level protocol |
| [05-context-and-data.md](docs/05-context-and-data.md) | What context each agent gets; core vs runtime data; RAG vs tools |
| [06-data-models.md](docs/06-data-models.md) | The canonical data model and how agents understand schemas |
| [07-evals-and-harness.md](docs/07-evals-and-harness.md) | Runtime harness and evaluation harness |
| [08-langgraph-primer.md](docs/08-langgraph-primer.md) | LangGraph concepts used here, with code |
| [09-worked-example.md](docs/09-worked-example.md) | The bracket rev B → rev C change, end to end |
| [10-design-decisions-and-tradeoffs.md](docs/10-design-decisions-and-tradeoffs.md) | Honest trade-offs: is LangGraph needed, rules vs agents, etc. |
| [11-open-questions.md](docs/11-open-questions.md) | Things worth a second opinion |
| [prototype/](prototype/) | A runnable LangGraph mini-version on mocked systems |

## A note on scope and honesty

This write-up describes a **rebuilt, simplified version** of a pattern, using
synthetic data. It deliberately fills in plausible detail (specific tools, field
names, scenarios) to make the design concrete. Where something is an assumption
rather than a hard requirement, the docs try to say so. Reviewers should treat
the specifics as one reasonable instantiation, not the only correct one.
