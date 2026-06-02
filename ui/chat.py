from __future__ import annotations

import uuid
from typing import Any

import streamlit as st

from tools.gemini import has_runtime_api_key
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

WORKFLOW_LABELS = {
    "research": "Research",
    "create_table": "Extract Table",
    "upsert_table": "Upsert Table",
    "query_table": "Query Table",
}


def render() -> None:
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    state = st.session_state.get("graph_state") or {}
    display_rows = state.get("display_rows") or []
    if display_rows:
        if state.get("intent") == "write":
            if st.session_state.get("awaiting_schema") or st.session_state.get("awaiting_confirmation"):
                caption = "Extracted table to review before upsert"
            else:
                caption = "Top 10 rows from the completed write"
            render_query_results(display_rows, max_rows=10, caption=caption)
        elif state.get("intent") == "query":
            render_query_results(display_rows)
        elif state.get("intent") == "research":
            render_query_results(display_rows, caption="Extracted table (not saved)")

    if st.session_state.get("awaiting_schema"):
        render_schema_negotiation()
        return

    if st.session_state.get("awaiting_confirmation"):
        render_write_gate()
        return

    actions = _render_workflow_controls()

    prompt = _render_query_form()
    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            with st.status("Starting...", expanded=False) as status:
                _run_agent(prompt, actions, status)


def _render_workflow_controls() -> dict[str, bool]:
    _ensure_workflow_defaults()

    cols = st.columns(4)
    query_enabled = bool(st.session_state[WORKFLOW_KEYS["query_table"]])
    with cols[0]:
        st.toggle(WORKFLOW_LABELS["research"], key=WORKFLOW_KEYS["research"], disabled=query_enabled, on_change=_select_research_mode)
    with cols[1]:
        st.toggle(WORKFLOW_LABELS["create_table"], key=WORKFLOW_KEYS["create_table"], disabled=query_enabled, on_change=_select_extract_mode)
    with cols[2]:
        st.toggle(WORKFLOW_LABELS["upsert_table"], key=WORKFLOW_KEYS["upsert_table"], disabled=query_enabled, on_change=_select_upsert_mode)
    with cols[3]:
        st.toggle(WORKFLOW_LABELS["query_table"], key=WORKFLOW_KEYS["query_table"], on_change=_enable_query_mode)

    if st.session_state[WORKFLOW_KEYS["query_table"]]:
        return {"research": False, "create_table": False, "upsert_table": False, "query_table": True}
    return {
        "research": bool(st.session_state[WORKFLOW_KEYS["research"]]),
        "create_table": bool(st.session_state[WORKFLOW_KEYS["create_table"]]),
        "upsert_table": bool(st.session_state[WORKFLOW_KEYS["upsert_table"]]),
        "query_table": False,
    }


def _render_query_form() -> str | None:
    gemini_ready = has_runtime_api_key()
    if not gemini_ready:
        st.info("Add your Gemini API key in the sidebar to begin.")

    with st.form("query_form", clear_on_submit=True, border=False):
        input_col, submit_col = st.columns([12, 1])
        with input_col:
            prompt = st.text_input(
                "Query",
                placeholder=(
                    "Ask me to research, extract a table, query saved data, or save data..."
                    if gemini_ready
                    else "Waiting for your Gemini API key..."
                ),
                disabled=not gemini_ready,
                label_visibility="collapsed",
            )
        with submit_col:
            submitted = st.form_submit_button(
                "Send",
                type="primary",
                use_container_width=True,
                disabled=not gemini_ready,
            )

    if not submitted:
        return None
    prompt = prompt.strip()
    return prompt or None


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


def _select_research_mode() -> None:
    if st.session_state[WORKFLOW_KEYS["research"]]:
        st.session_state[WORKFLOW_KEYS["create_table"]] = False
        st.session_state[WORKFLOW_KEYS["upsert_table"]] = False
        st.session_state[WORKFLOW_KEYS["query_table"]] = False


def _select_extract_mode() -> None:
    if st.session_state[WORKFLOW_KEYS["create_table"]]:
        st.session_state[WORKFLOW_KEYS["research"]] = False
        st.session_state[WORKFLOW_KEYS["upsert_table"]] = False
        st.session_state[WORKFLOW_KEYS["query_table"]] = False


def _select_upsert_mode() -> None:
    if st.session_state[WORKFLOW_KEYS["upsert_table"]]:
        st.session_state[WORKFLOW_KEYS["research"]] = False
        st.session_state[WORKFLOW_KEYS["create_table"]] = False
        st.session_state[WORKFLOW_KEYS["query_table"]] = False


def _run_agent(prompt: str, actions: dict[str, bool], status: Any | None = None) -> None:
    thread_id = st.session_state.get("thread_id") or str(uuid.uuid4())
    st.session_state.thread_id = thread_id
    config = {"configurable": {"thread_id": thread_id}}
    previous_state = st.session_state.get("graph_state") or {}

    def update_status(event_state: dict[str, Any]) -> None:
        if status:
            status.update(label=_progress_label(event_state))

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
        on_event=update_status,
    )
    st.session_state.graph_state = last_state

    if interrupt_payload:
        _append_assistant_response_once(last_state.get("response_to_user"))
        _store_interrupt(interrupt_payload)
        if status:
            status.update(label="Waiting for your review", state="complete")
        st.rerun()
        return

    _append_assistant_response_once(last_state.get("response_to_user") or "Done.")
    if status:
        status.update(label="Done", state="complete")
    st.rerun()


def _progress_label(event_state: dict[str, Any]) -> str:
    if event_state.get("error"):
        return "Preparing an error response..."
    if event_state.get("generated_sql"):
        return "Fetching query results..."
    if event_state.get("display_rows"):
        return "Preparing results..."

    intent = event_state.get("intent")
    if intent == "query":
        return "Generating a safe SQL query..."
    if intent == "write":
        if event_state.get("proposed_ddl") or event_state.get("dry_run_sql"):
            return "Preparing write review..."
        return "Checking the target table..."
    if intent == "research":
        if event_state.get("search_results") or event_state.get("raw_extracted"):
            return "Structuring extracted data..."
        return "Searching and extracting evidence..."
    if intent == "schema":
        return "Preparing schema options..."
    return "Understanding the request..."


def _store_interrupt(payload: dict) -> None:
    st.session_state.pending_interrupt = payload
    if payload.get("kind") == "schema":
        st.session_state.awaiting_schema = True
        st.session_state.awaiting_confirmation = False
    elif payload.get("kind") == "write_gate":
        st.session_state.awaiting_confirmation = True
        st.session_state.awaiting_schema = False


def _append_assistant_response_once(response: str | None) -> None:
    if not response:
        return
    messages = st.session_state.messages
    if messages and messages[-1].get("role") == "assistant" and messages[-1].get("content") == response:
        return
    messages.append({"role": "assistant", "content": response})
