# Prototype

A minimal, runnable LangGraph version of the governance workflow, on **mocked**
PLM/ERP/MES data. It uses plain Python where the real system would call an LLM,
so it runs **without an API key**.

This is intentionally tiny — it demonstrates the *shape* (supervisor → parallel
agents → policy → human interrupt → gateway), not the full design.

## Run it

```bash
pip install langgraph
python governance_graph.py
```

## Expected output

```
PAUSED FOR APPROVAL: 3 actions proposed for BRK-10442
  finding: Change Impact: 40 in stock, 1 open PO, 3 work orders on rev B
  finding: Data Quality: ERP dry run fails, no material group for AMS 4911
  action:  set_effectivity (high) start rev C after WO-7790
  action:  cancel_po (high) PO 4500018832 (60 EA)
  action:  add_mapping (medium) AMS 4911 -> MG-TI64

RESUMED, decision: approved
  gateway: [ECN-2291-A1] applied set_effectivity: start rev C after WO-7790
  gateway: [ECN-2291-A2] applied cancel_po: PO 4500018832 (60 EA)
  gateway: [ECN-2291-A3] applied add_mapping: AMS 4911 -> MG-TI64
```

## What it demonstrates

- **State + reducers** — parallel agents append findings/actions without clobbering.
- **Rules-first supervisor** — known event type routed without an LLM.
- **Parallel specialists** — Change Impact and Data Quality run together.
- **Policy check** — risk decides human-approval vs auto-execute.
- **Interrupt/resume** — the graph pauses for approval and resumes with a decision.
- **Gateway** — the only writer; idempotency keys on every action.

## What it deliberately omits

- Real LLM calls, real tools, real MCP servers.
- Entity Resolver's real duplicate-detection logic — it's stubbed as a
  placeholder here, and the demo event never actually routes to it.
- Data Quality's broader role — this prototype only exercises its sync-check
  slice (a dry run against a mapping table), not the continuous drift scans
  and pattern detection described in the docs.
- Persistence (`InMemorySaver` here; `PostgresSaver` in the design).
- The eval harness.

## Where to take it next

1. Swap the mock agent functions for real LLM + tool calls.
2. Expose the mock systems as MCP servers.
3. Add an eval script with labeled cases scoring routing + tool-argument accuracy.
4. Visualize in LangGraph Studio (`langgraph dev`).
