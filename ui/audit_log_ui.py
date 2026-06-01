from __future__ import annotations

import html

import streamlit as st

from tools.supabase import get_supabase_client


@st.cache_data(ttl=15, show_spinner=False)
def _cached_audit_rows() -> list[dict]:
    client = get_supabase_client()
    response = (
        client.table("agent_audit_log")
        .select("id, executed_at, intent, target_table, operation, row_count, session_id")
        .order("executed_at", desc=True)
        .limit(100)
        .execute()
    )
    return response.data or []


def clear_audit_cache() -> None:
    _cached_audit_rows.clear()


def render() -> None:
    st.subheader("Audit Log")
    if st.button("Refresh audit log"):
        clear_audit_cache()
        st.rerun()

    try:
        rows = _cached_audit_rows()
    except Exception as exc:
        st.error(f"Audit log unavailable: {exc}")
        return

    if not rows:
        st.info("No writes recorded yet.")
        return

    st.markdown(_audit_rows_table(rows), unsafe_allow_html=True)

    options = {f"{row['executed_at']} | {row['target_table']} | {row['operation']}": row["id"] for row in rows}
    selected = st.selectbox("View SQL", [""] + list(options.keys()))
    if selected:
        client = get_supabase_client()
        full = (
            client.table("agent_audit_log")
            .select("proposed_sql, source_urls")
            .eq("id", options[selected])
            .single()
            .execute()
        )
        st.code((full.data or {}).get("proposed_sql", ""), language="sql")
        urls = (full.data or {}).get("source_urls") or []
        if urls:
            st.caption("Sources: " + ", ".join(urls))


def _audit_rows_table(rows: list[dict]) -> str:
    columns = ["executed_at", "intent", "target_table", "operation", "row_count", "session_id"]
    labels = {
        "executed_at": "Executed At",
        "intent": "Intent",
        "target_table": "Target Table",
        "operation": "Operation",
        "row_count": "Rows",
        "session_id": "Session",
    }
    header = "".join(f"<th>{labels[column]}</th>" for column in columns)
    body = "\n".join(
        "<tr>"
        + "".join(f"<td>{html.escape(_format_cell(row.get(column)))}</td>" for column in columns)
        + "</tr>"
        for row in rows
    )
    return f"""
<table class="audit-log-table">
  <thead><tr>{header}</tr></thead>
  <tbody>
    {body}
  </tbody>
</table>
"""


def _format_cell(value: object) -> str:
    if value is None:
        return ""
    return str(value)
