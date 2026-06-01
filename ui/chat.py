from __future__ import annotations

import uuid

import streamlit as st

from ui.graph_runner import stream_graph
from ui.query_results_ui import render_query_results
from ui.schema_ui import render_schema_negotiation
from ui.write_gate_ui import render_write_gate


WORKFLOW_KEYS = {
    "research": "workflow_research",
    "create_table": "workflow_create_table",
    "upsert_table": "workflow_upsert_table",
    "query_table": "workflow_query_table",
}


def render() -> None:
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if st.session_state.get("awaiting_schema"):
        render_schema_negotiation()
        return

    if st.session_state.get("awaiting_confirmation"):
        render_write_gate()
        return

    state = st.session_state.get("graph_state") or {}
    display_rows = state.get("display_rows") or []
    if display_rows:
        if state.get("intent") == "write":
            render_query_results(display_rows, max_rows=10, caption="Top 10 rows from the completed write")
        elif state.get("intent") == "query":
            render_query_results(display_rows)
        elif state.get("intent") == "research":
            render_query_results(display_rows, caption="Extracted table")

    actions = _render_workflow_controls()

    if prompt := st.chat_input("Ask me to research, query, or save data..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            with st.spinner("Working..."):
                _run_agent(prompt, actions)


def _render_workflow_controls() -> dict[str, bool]:
    _ensure_workflow_defaults()

    cols = st.columns(4)
    query_enabled = bool(st.session_state[WORKFLOW_KEYS["query_table"]])
    with cols[0]:
        st.toggle("Research", key=WORKFLOW_KEYS["research"], disabled=query_enabled, on_change=_disable_query_mode)
    with cols[1]:
        st.toggle("Create New Table", key=WORKFLOW_KEYS["create_table"], disabled=query_enabled, on_change=_disable_query_mode)
    with cols[2]:
        st.toggle("Upsert Table", key=WORKFLOW_KEYS["upsert_table"], disabled=query_enabled, on_change=_disable_query_mode)
    with cols[3]:
        st.toggle("Query Table", key=WORKFLOW_KEYS["query_table"], on_change=_enable_query_mode)

    if st.session_state[WORKFLOW_KEYS["query_table"]]:
        return {"research": False, "create_table": False, "upsert_table": False, "query_table": True}
    return {
        "research": bool(st.session_state[WORKFLOW_KEYS["research"]]),
        "create_table": bool(st.session_state[WORKFLOW_KEYS["create_table"]]),
        "upsert_table": bool(st.session_state[WORKFLOW_KEYS["upsert_table"]]),
        "query_table": False,
    }


def _ensure_workflow_defaults() -> None:
    defaults = {
        "research": True,
        "create_table": False,
        "upsert_table": False,
        "query_table": False,
    }
    for action, key in WORKFLOW_KEYS.items():
        if key not in st.session_state:
            st.session_state[key] = defaults[action]


def _enable_query_mode() -> None:
    if st.session_state[WORKFLOW_KEYS["query_table"]]:
        st.session_state[WORKFLOW_KEYS["research"]] = False
        st.session_state[WORKFLOW_KEYS["create_table"]] = False
        st.session_state[WORKFLOW_KEYS["upsert_table"]] = False


def _disable_query_mode() -> None:
    if (
        st.session_state[WORKFLOW_KEYS["research"]]
        or st.session_state[WORKFLOW_KEYS["create_table"]]
        or st.session_state[WORKFLOW_KEYS["upsert_table"]]
    ):
        st.session_state[WORKFLOW_KEYS["query_table"]] = False


def _run_agent(prompt: str, actions: dict[str, bool]) -> None:
    thread_id = st.session_state.get("thread_id") or str(uuid.uuid4())
    st.session_state.thread_id = thread_id
    config = {"configurable": {"thread_id": thread_id}}
    previous_state = st.session_state.get("graph_state") or {}
    last_state, interrupt_payload = stream_graph(
        {
            "user_message": prompt,
            "session_history": st.session_state.messages,
            "session_id": thread_id,
            "requested_actions": actions,
            "target_table": previous_state.get("target_table"),
            "structured_artifacts": previous_state.get("structured_artifacts", []),
            "active_artifact_id": previous_state.get("active_artifact_id"),
        },
        config=config,
    )
    st.session_state.graph_state = last_state

    if interrupt_payload:
        _store_interrupt(interrupt_payload)
        st.rerun()
        return

    response = last_state.get("response_to_user") or "Done."
    st.session_state.messages.append({"role": "assistant", "content": response})
    st.rerun()


def _store_interrupt(payload: dict) -> None:
    st.session_state.pending_interrupt = payload
    if payload.get("kind") == "schema":
        st.session_state.awaiting_schema = True
        st.session_state.awaiting_confirmation = False
    elif payload.get("kind") == "write_gate":
        st.session_state.awaiting_confirmation = True
        st.session_state.awaiting_schema = False
