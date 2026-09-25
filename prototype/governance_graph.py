"""
Mini version of the agentic governance workflow in LangGraph.

The PLM, ERP and MES are mocked with dictionaries, and the "agents" use plain
Python where the real system would call an LLM, so this runs without an API key.

    pip install langgraph
    python governance_graph.py
"""
import operator
from typing import Annotated, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

# ---------------------------------------------------------------------------
# Mock systems (stand-ins for Teamcenter, SAP and Solumina)
# ---------------------------------------------------------------------------
CROSSWALK = {"BRK-10442": "50010442"}                   # PLM part -> ERP material
ERP_STOCK = {"50010442": 40}                            # rev B units in stock
ERP_OPEN_POS = {"50010442": ["PO 4500018832 (60 EA)"]}
MES_WORK_ORDERS = {"BRK-10442": ["WO-7781", "WO-7782", "WO-7790"]}
MAPPING = {"AMS 4027": "MG-AL6061", "AMS 4037": "MG-AL2024"}  # no AMS 4911 yet


# ---------------------------------------------------------------------------
# Shared case state. Annotated lists use a reducer (operator.add), so agents
# running in parallel can each append without overwriting each other.
# ---------------------------------------------------------------------------
class CaseState(TypedDict, total=False):
    event: dict
    routes: list[str]
    findings: Annotated[list[str], operator.add]
    actions: Annotated[list[dict], operator.add]
    summary: str
    decision: str
    log: Annotated[list[str], operator.add]


# ---------------------------------------------------------------------------
# Supervisor: rules first, LLM only for events no rule covers
# ---------------------------------------------------------------------------
ROUTING_RULES = {
    "change_drafted": ["change_impact", "data_quality"],
    "create_requested": ["entity_resolver"],
    "sync_failed": ["data_quality"],
}


def llm_classify(event: dict) -> list[str]:
    # Real system: an LLM with structured output picks the route, e.g.
    #   llm.with_structured_output(Route).invoke(f"Classify this event: {event}")
    return ["data_quality"]


def supervisor(state: CaseState):
    routes = ROUTING_RULES.get(state["event"]["type"]) or llm_classify(state["event"])
    return {"routes": routes}


def route(state: CaseState) -> list[str]:
    return state["routes"]  # returning several node names runs them in parallel


# ---------------------------------------------------------------------------
# Specialist agents (each would be its own subgraph with LLM + tools)
# ---------------------------------------------------------------------------
def change_impact(state: CaseState):
    part = state["event"]["part"]
    material = CROSSWALK[part]
    stock = ERP_STOCK.get(material, 0)
    pos = ERP_OPEN_POS.get(material, [])
    wos = MES_WORK_ORDERS.get(part, [])
    if not (stock or pos or wos):
        return {"findings": ["Change Impact: nothing depends on the old revision"]}
    actions = [{"action": "set_effectivity", "detail": f"start rev C after {wos[-1]}", "risk": "high"}]
    actions += [{"action": "cancel_po", "detail": po, "risk": "high"} for po in pos]
    return {
        "findings": [f"Change Impact: {stock} in stock, {len(pos)} open PO, {len(wos)} work orders on rev B"],
        "actions": actions,
    }


def data_quality(state: CaseState):
    spec = state["event"]["new_spec"]
    if spec in MAPPING:  # dry run: same mapping rules the pipeline uses
        return {"findings": ["Data Quality: ERP dry run passes"]}
    return {
        "findings": [f"Data Quality: ERP dry run fails, no material group for {spec}"],
        "actions": [{"action": "add_mapping", "detail": f"{spec} -> MG-TI64", "risk": "medium"}],
    }


def entity_resolver(state: CaseState):
    return {"findings": ["Entity Resolver: no similar parts found"]}


# ---------------------------------------------------------------------------
# Proposal, policy, human approval, gateway
# ---------------------------------------------------------------------------
def proposal(state: CaseState):
    # Real system: an LLM turns findings + actions into a plain-language summary
    return {"summary": f"{len(state.get('actions', []))} actions proposed for {state['event']['part']}"}


def policy(state: CaseState) -> str:
    risky = any(a["risk"] in ("medium", "high") for a in state.get("actions", []))
    return "human_approval" if risky else "gateway"


def human_approval(state: CaseState):
    # Pauses the graph. State is saved by the checkpointer until someone resumes it.
    decision = interrupt({"summary": state["summary"], "findings": state["findings"],
                          "actions": state["actions"]})
    return {"decision": decision}


def gateway(state: CaseState):
    # The only component allowed to write. Idempotency keys make retries safe.
    if state.get("decision") == "rejected":
        return {"log": ["Nothing written. Decision saved as an eval example."]}
    case = state["event"]["case"]
    return {"log": [f"[{case}-A{i}] applied {a['action']}: {a['detail']}"
                    for i, a in enumerate(state.get("actions", []), start=1)]}


# ---------------------------------------------------------------------------
# Wire up the graph
# ---------------------------------------------------------------------------
builder = StateGraph(CaseState)
for name, fn in [("supervisor", supervisor), ("change_impact", change_impact),
                 ("data_quality", data_quality), ("entity_resolver", entity_resolver),
                 ("proposal", proposal), ("human_approval", human_approval), ("gateway", gateway)]:
    builder.add_node(name, fn)

builder.add_edge(START, "supervisor")
builder.add_conditional_edges("supervisor", route, ["change_impact", "data_quality", "entity_resolver"])
for agent in ["change_impact", "data_quality", "entity_resolver"]:
    builder.add_edge(agent, "proposal")
builder.add_conditional_edges("proposal", policy, ["human_approval", "gateway"])
builder.add_edge("human_approval", "gateway")
builder.add_edge("gateway", END)

graph = builder.compile(checkpointer=InMemorySaver())  # use PostgresSaver in production


if __name__ == "__main__":
    config = {"configurable": {"thread_id": "ECN-2291"}}  # one thread per case
    event = {"type": "change_drafted", "case": "ECN-2291", "part": "BRK-10442",
             "old_spec": "AMS 4027", "new_spec": "AMS 4911"}

    # 1) Run until the graph pauses for approval
    result = graph.invoke({"event": event}, config)
    paused = result["__interrupt__"][0].value
    print("PAUSED FOR APPROVAL:", paused["summary"])
    for f in paused["findings"]:
        print("  finding:", f)
    for a in paused["actions"]:
        print(f"  action:  {a['action']} ({a['risk']}) {a['detail']}")

    # 2) Later (could be days), the change board approves and the same run resumes
    result = graph.invoke(Command(resume="approved"), config)
    print("\nRESUMED, decision:", result["decision"])
    for line in result["log"]:
        print("  gateway:", line)
