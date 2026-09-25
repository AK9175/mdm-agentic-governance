# 6. Data models: how agents understand the systems

## The problem

SAP alone has thousands of fields with cryptic names like `MATKL`. Teamcenter and
Solumina each have their own models. You cannot put raw schemas in a prompt — it's
huge, mostly irrelevant per case, and quickly stale.

## The solution: a canonical data model + just-in-time lookup

### 1. A canonical data model in the MDM hub

Define business entities once, in plain language, each field mapped to its
technical name in every system:

```
Entity: Material
  material_group   → SAP: MATKL          owner: ERP    required: true
                     PLM: <spec attr>
                     MES: <material fld>
  base_unit        → SAP: MEINS          owner: ERP    required: true
  material_spec    → PLM: <spec attr>    owner: PLM    required: true
  ...
```

Each field records its **owning system**, which systems **require** it, and its
**allowed values**.

### 2. Just-in-time lookup through a tool

Agents call `schema.describe` for only the entity + system in play:

```json
{"entity":"Material","system":"ERP","field":"material_group",
 "technical_name":"MATKL","owner":"ERP","required":true,
 "description":"Category used for purchasing and reporting",
 "source_mapping":"Derived from PLM material spec via mapping table"}
```

### 3. Tools translate for the agent

Tool responses use canonical names; raw codes appear only as evidence. The agent
reasons about "material group," not `MATKL`.

### 4. Short domain primers in prompts

Each agent's prompt has a compact glossary plus a few worked examples of past
cases — enough to learn patterns without seeing whole schemas.

### 5. Mappings and rules are data, not memory

The agent never memorizes that `AMS 4027` maps to a given group; it queries the
mapping table each time. Answers stay correct when mappings change.

### 6. Keep it current automatically

Each system exposes its own model metadata: SAP's data dictionary, Teamcenter's
business model (its BMIDE configuration), Solumina's configuration. `schema.diff`
compares them against the canonical model on a schedule. When a system upgrade
adds/changes a field:

- the canonical dictionary is updated,
- Data Quality flags pipeline rules that no longer fit,
- the affected evals rerun.

## The MDM hub's four assets

| Asset | What it is | Who relies on it |
|---|---|---|
| Golden record | The agreed master version of each entity | All agents |
| ID crosswalk | PLM part = ERP material = MES part | All agents (follow one part across systems) |
| SoR matrix | Which system owns each attribute | Data Quality (whose value wins), all agents |
| Canonical data model | Plain-language field defs → technical names | All agents (read/write in business terms) |

## Evaluating the data-model layer

You can eval this layer directly with a small question set — "which system owns
the unit of measure?", "what does the ERP require to create a material?" — to
confirm agents interpret the model correctly before trusting larger decisions.
