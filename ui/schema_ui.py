from __future__ import annotations

import streamlit as st

from ui.graph_runner import resume_graph


def render_schema_negotiation() -> None:
    payload = st.session_state.get("pending_interrupt") or {}
    detected_fields = payload.get("detected_fields") or []
    table_name = payload.get("table_name") or "research_results"

    st.info(f"Table `{table_name}` does not exist yet.")
    if detected_fields:
        st.caption("Detected fields: " + ", ".join(f"`{field}`" for field in detected_fields))

    choice = st.radio(
        "Schema source",
        ["Generate from extracted data", "Use my schema"],
        horizontal=True,
    )
    config = {"configurable": {"thread_id": st.session_state.thread_id}}

    if choice == "Use my schema":
        user_ddl = st.text_area(
            "CREATE TABLE statement or column list",
            height=180,
            placeholder="CREATE TABLE competitor_pricing (\n  company TEXT,\n  plan_name TEXT,\n  price_monthly DECIMAL(10,2)\n);",
        )
        if st.button("Use schema", type="primary") and user_ddl.strip():
            _continue(
                {"schema_source": "user-uploaded", "proposed_ddl": user_ddl.strip()},
                config,
            )
    elif st.button("Generate schema", type="primary"):
        _continue({"schema_source": "ai-generated"}, config)


def _continue(payload: dict, config: dict) -> None:
    st.session_state.awaiting_schema = False
    last_state, interrupt_payload = resume_graph(payload, config)
    st.session_state.graph_state = last_state
    if interrupt_payload:
        st.session_state.pending_interrupt = interrupt_payload
        if interrupt_payload.get("kind") == "write_gate":
            st.session_state.awaiting_confirmation = True
    st.rerun()
