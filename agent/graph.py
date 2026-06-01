from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from agent.nodes import check_table, db_write, intent, nl_query, research, schema, unknown, write_gate
from agent.state import AgentState


def route_intent(state: AgentState) -> str:
    if state.intent == "research":
        return "research"
    if state.intent == "write":
        return "research"
    if state.intent == "query":
        return "nl_query"
    if state.intent == "schema":
        return "schema"
    return "unknown"


def route_after_research(state: AgentState) -> str:
    if state.error or not state.structured_rows:
        return END
    if state.intent == "write":
        return "check_table"
    return END


def route_table_exists(state: AgentState) -> str:
    return "write_gate" if state.table_exists else "schema"


def route_confirmed(state: AgentState) -> str:
    return "db_write" if state.user_confirmed else END


builder = StateGraph(AgentState)
builder.add_node("intent", intent.run)
builder.add_node("research", research.run)
builder.add_node("check_table", check_table.run)
builder.add_node("schema", schema.run)
builder.add_node("write_gate", write_gate.run)
builder.add_node("db_write", db_write.run)
builder.add_node("nl_query", nl_query.run)
builder.add_node("unknown", unknown.run)

builder.set_entry_point("intent")
builder.add_conditional_edges(
    "intent",
    route_intent,
    {
        "research": "research",
        "nl_query": "nl_query",
        "schema": "schema",
        "unknown": "unknown",
    },
)
builder.add_conditional_edges("research", route_after_research, {"check_table": "check_table", END: END})
builder.add_conditional_edges("check_table", route_table_exists, {"write_gate": "write_gate", "schema": "schema"})
builder.add_edge("schema", "write_gate")
builder.add_conditional_edges("write_gate", route_confirmed, {"db_write": "db_write", END: END})
builder.add_edge("db_write", END)
builder.add_edge("nl_query", END)
builder.add_edge("unknown", END)

checkpointer = MemorySaver()
graph = builder.compile(checkpointer=checkpointer)
