from __future__ import annotations

import streamlit as st

from ui.audit_log_ui import clear_audit_cache
from ui.graph_runner import resume_graph
from ui.sidebar import clear_sidebar_cache


def render_write_gate() -> None:
    payload = st.session_state.get("pending_interrupt") or {}
    dry_run_sql = payload.get("dry_run_sql") or ""
    row_count = payload.get("row_count", 0)
    table_name = payload.get("target_table", "unknown")

    st.warning(f"Review the proposed write to `{table_name}` before confirming.")
    st.code(dry_run_sql, language="sql")
    st.caption(f"{row_count} row(s) will be written.")

    col_confirm, col_cancel = st.columns(2)
    config = {"configurable": {"thread_id": st.session_state.thread_id}}

    with col_confirm:
        if st.button("Confirm write", type="primary", use_container_width=True):
            _continue({"user_confirmed": True}, config)

    with col_cancel:
        if st.button("Cancel", use_container_width=True):
            _continue({"user_confirmed": False}, config)


def _continue(payload: dict, config: dict) -> None:
    st.session_state.awaiting_confirmation = False
    last_state, interrupt_payload = resume_graph(payload, config)
    st.session_state.graph_state = last_state
    if payload.get("user_confirmed") and not interrupt_payload:
        clear_sidebar_cache()
        clear_audit_cache()
    if interrupt_payload:
        st.session_state.pending_interrupt = interrupt_payload
        st.session_state.awaiting_confirmation = interrupt_payload.get("kind") == "write_gate"
        st.session_state.awaiting_schema = interrupt_payload.get("kind") == "schema"
        st.rerun()
        return
    response = last_state.get("response_to_user") or "Done."
    st.session_state.messages.append({"role": "assistant", "content": response})
    st.session_state.pending_interrupt = None
    st.rerun()
