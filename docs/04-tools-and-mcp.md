# 4. Tools and the MCP layer

## Tool catalogue

All agent tools are **read-only**. Only the gateway has write tools.

### Shared tools (every agent)

- `mdm.get_golden_record` — the master version of an entity
- `mdm.get_crosswalk` — IDs across systems (PLM part = ERP material = MES part)
- `schema.describe` — canonical field → technical field, ownership, requiredness
- `sor.get_owner` — which system owns an attribute
- `cases.search_similar` — past resolved cases (RAG)

### Per-agent tools

| Agent | Tools | What they answer |
|---|---|---|
| Supervisor | `router.match_rule`, `case.create`, `case.link_events` | Who handles this; is it part of an existing case |
| Change Impact | `plm.get_change`, `plm.compare_revisions`, `plm.where_used`, `erp.get_stock`, `erp.get_open_pos`, `erp.get_planned_orders`, `mes.get_open_work_orders`, `mes.get_process_plan`, `mes.get_as_built` | What exists / is in progress on the old revision |
| Entity Resolver | `mdm.search_similar`, `mdm.compare_records`, `plm.get_item`, `erp.get_plant_extensions`, `mdm.get_merge_history` | Does this already exist; how strong is the evidence |
| Data Quality | `dq.list_rules`, `dq.run_rule`, `dq.reconcile`, `dq.profile_field`, `mes.get_nonconformances`, `pipeline.dry_run`, `pipeline.get_message`, `pipeline.pending_messages`, `pipeline.find_similar_failures`, `mapping.lookup`, `mapping.find_similar`, `schema.diff` | Is data correct; has it drifted; are shop-floor issues a pattern; will this data be accepted; why did a sync fail; has a data model changed |
| Gateway (not an agent) | `policy.evaluate`, `gateway.apply`, `gateway.replay`, `gateway.log_decision` | Is this allowed; apply safely; record it |

### Tool-layer rules

- Tools take **typed inputs** and return **compact, summarized** results, not raw
  system dumps (raw ERP payloads waste context and confuse the model).
- The actual checks (dry runs, rule execution) are **deterministic code** inside
  the tools; the LLM decides *what* to check and interprets results.
- Tools own the enterprise concerns: timeouts, retries, rate limits, caching.

## The MCP server layer

Each enterprise system sits behind its own **read-only MCP server**. There are
five: PLM, ERP, MES, MDM hub, and the integration pipeline (whose tools —
`pipeline.dry_run`, `mapping.lookup` — belong to the middleware, not any one
system).

```
┌──────────────────────────────────────────────┐
│  Agent backend (MCP host)                      │
│  LangGraph agents + one MCP client per server  │
└───┬──────┬──────┬──────┬──────┬────────────────┘
    │      │      │      │      │
 ┌──┴─┐ ┌──┴─┐ ┌──┴─┐ ┌──┴──┐ ┌─┴──────┐
 │PLM │ │ERP │ │MES │ │MDM  │ │Pipeline│   MCP servers (read-only)
 │MCP │ │MCP │ │MCP │ │MCP  │ │MCP     │
 └─┬──┘ └─┬──┘ └─┬──┘ └─┬───┘ └─┬──────┘
   │      │      │      │       │
 Team-   SAP   Solu-  MDM     Middle-
 center  S/4   mina   hub DB  ware
```

### What's inside one MCP server (e.g. ERP)

An agent tool call passes through these layers before reaching SAP:

1. **Tool definitions** — name, description, typed input/output schemas. Good
   descriptions matter: the model reads them when choosing tools, so they
   directly affect tool-selection accuracy.
2. **Access control** — every call runs under a read-only service account and is
   audit-logged.
3. **Guardrails** — timeouts, rate limits, short-lived caching, to protect
   production SAP from agent traffic.
4. **Canonical translation** — inbound: `material_number` → `MATNR`; outbound:
   `MATKL` → `material_group`, with raw codes kept as evidence.
5. **System connector** — the actual OData/BAPI call.

The MDM hub server has an extra role: it serves the **canonical data model**
itself, so `schema.describe` and `sor.get_owner` come from there.

### Why MCP instead of plain tools

- **Standard interface:** the same ERP server can be reused by other agents,
  teams, or a steward's assistant, without rewriting integrations.
- **Isolated concerns:** SAP credentials, rate limits, and translation live in
  one deployable service, owned by the team that knows SAP.
- **Trade-off:** an extra network hop and another service to run. For a single
  small app, plain in-process LangChain tools would be simpler and valid.

### Two credentials, never one

- **Agent backend → MCP server:** OAuth/service token per HTTP request.
- **MCP server → SAP:** the server's own read-only service account.

The agent backend never holds SAP credentials. Even if compromised, it could
only call the handful of read-only tools the MCP server exposes.

## Wire-level protocol

MCP is **JSON-RPC 2.0** over stdio or Streamable HTTP. For shared services, use
HTTP with token auth. The message never says where it's going — the **connection**
(the HTTP endpoint / the launched subprocess) determines that.

### Handshake (once per connection)

```json
→ {"jsonrpc":"2.0","id":1,"method":"initialize",
   "params":{"protocolVersion":"2025-06-18","capabilities":{},
             "clientInfo":{"name":"governance-agents","version":"1.4.0"}}}
← {"jsonrpc":"2.0","id":1,
   "result":{"protocolVersion":"2025-06-18","capabilities":{"tools":{}},
             "serverInfo":{"name":"erp-mcp","version":"2.1.0"}}}
```

Sent as an HTTP POST to `https://erp-mcp.internal/mcp` with an
`Authorization: Bearer` header. The server returns a session ID; later requests
carry it and the agreed `MCP-Protocol-Version`.

### Discover tools

```json
→ {"jsonrpc":"2.0","id":2,"method":"tools/list"}
← {"jsonrpc":"2.0","id":2,"result":{"tools":[{
     "name":"get_stock",
     "description":"Current unrestricted stock for a material, by revision and plant.",
     "inputSchema":{"type":"object","properties":{
       "material_number":{"type":"string"},"revision":{"type":"string"}},
       "required":["material_number"]},
     "outputSchema":{"type":"object","properties":{
       "quantity":{"type":"number"},"unit":{"type":"string"},"plant":{"type":"string"}}}}]}}
```

The `erp.` prefix used elsewhere is added by the **client** to namespace each
server's tools; on the wire the tool is just `get_stock`.

### Call a tool

```json
→ {"jsonrpc":"2.0","id":7,"method":"tools/call",
   "params":{"name":"get_stock","arguments":{"material_number":"50010442","revision":"B"}}}
← {"jsonrpc":"2.0","id":7,"result":{
     "content":[{"type":"text","text":"40 EA of 50010442 rev B in plant 1000"}],
     "structuredContent":{"quantity":40,"unit":"EA","plant":"1000"},
     "isError":false}}
```

`structuredContent` (added in MCP 2025-06-18) is validated JSON matching the
declared `outputSchema`; the `content` text is a human-readable fallback for
clients that haven't upgraded. The agents and evals depend on the structured
form.

### Two kinds of error

- **Protocol error** (invalid call, e.g. missing argument): JSON-RPC `error`
  object with a code like `-32602`. The model usually can't self-fix.
- **Tool execution error** (valid call, operation failed): a normal result with
  `"isError": true`, shown to the model so it can react.

### How it reaches the LLM

The LLM never sees JSON-RPC. An adapter (LangChain's MCP adapters) in the client
turns `tools/list` into normal tool definitions, converts the model's tool
choice into `tools/call`, and turns the result back into a tool message.
