# 8. LangGraph primer (as used here)

LangGraph models an AI workflow as a **graph**: nodes are Python functions, edges
decide what runs next, and a shared **state** object carries data between steps.
It's built for workflows that need branching, parallelism, human pauses, and
resumption — more control than a simple chatbot loop.

## Core concepts

### State, nodes, edges

A node receives the current state and returns **only the fields it changes**.

```python
class State(TypedDict):
    part: str
    findings: list[str]

def check(state: State):
    return {"findings": [f"checked {state['part']}"]}

g = StateGraph(State)
g.add_node("check", check)
g.add_edge(START, "check"); g.add_edge("check", END)
g.compile().invoke({"part": "BRK-10442"})
```

### How a node updates state

- Return a **partial dict**; unmentioned fields are untouched.
- A field **without a reducer** is **overwritten**.
- A field **with a reducer** (`Annotated[list[str], operator.add]`) is
  **combined** — e.g. lists append.
- **Mutating state in place does nothing** — always return the change.
- **Returning an unknown key is silently ignored** — typos drop updates, so typed
  state + tests matter.

### Conditional routing

A routing function returns the **name of the next node** (it doesn't change
state):

```python
def route(state):
    return "data_quality" if state["event"] == "sync_failed" else "entity_resolver"

g.add_conditional_edges("supervisor", route, ["data_quality", "entity_resolver"])
```

### Parallel steps + reducers

If the routing function returns a **list**, those nodes run at once. A reducer
merges their writes to the same field (without one, parallel writes to the same
key raise an error):

```python
findings: Annotated[list[str], operator.add]   # both agents append here

def route(state):
    return ["change_impact", "data_quality"]   # run in parallel
```

### Pausing for a human

`interrupt()` pauses the graph and saves state via a checkpointer;
`Command(resume=...)` continues the same run later (even days later).

```python
def human_approval(state):
    decision = interrupt({"actions": state["actions"]})   # graph stops here
    return {"decision": decision}

graph = builder.compile(checkpointer=InMemorySaver())      # PostgresSaver in prod
graph.invoke({"event": event}, config)                     # runs until the pause
graph.invoke(Command(resume="approved"), config)           # resumes with the decision
```

`config = {"configurable": {"thread_id": "ECN-2291"}}` — the `thread_id` (one per
case) is how LangGraph knows which saved run to resume.

**Gotcha:** on resume, the node **re-runs from its first line**; `interrupt()`
returns the resumed value instead of pausing. Keep side effects *after* the
`interrupt()` call.

### Update + route in one step

```python
from langgraph.types import Command
def supervisor(state):
    return Command(update={"routes": ["data_quality"]}, goto="data_quality")
```

## Subgraphs

A subgraph is **a graph used as a single node inside another graph** — like a
function call. Each specialist agent is a subgraph: the parent sees one node; the
agent internally runs its own multi-step logic.

```python
def data_quality_node(state: CaseState):
    out = data_quality.invoke({"event": state["event"]})
    return {"findings": out.get("findings", []), "actions": out.get("actions", [])}

builder.add_node("data_quality", data_quality_node)   # parent sees one node
```

Why they matter here: they enforce agent **boundaries** (own tools, prompts,
private state), let each agent be **tested/evaluated independently**, allow
changing one agent without touching others, and show up **nested** in traces.

## Is LangGraph necessary here?

Honestly, no — most of this system is deterministic (routing known events,
mapping checks, policy, writes), and you could build it with plain Python + a
workflow engine (e.g. Temporal) + a state table. See
[10-design-decisions-and-tradeoffs.md](10-design-decisions-and-tradeoffs.md).

It's a **good fit** because it gives, out of the box: durable pause/resume for
approvals that can take days; state-based routing between agents; parallel
branches; independently testable subgraphs; and node/tool/state tracing. The
deterministic parts (mapping checks, gateway) stay as plain code *outside* the
LLM, so LangGraph only orchestrates.
