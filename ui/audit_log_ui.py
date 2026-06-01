from __future__ import annotations

import pandas as pd
import streamlit as st

from tools.supabase import get_supabase_client


def render() -> None:
    st.subheader("Audit Log")
    try:
        client = get_supabase_client()
        response = (
            client.table("agent_audit_log")
            .select("id, executed_at, intent, target_table, operation, row_count, session_id")
            .order("executed_at", desc=True)
            .limit(100)
            .execute()
        )
    except Exception as exc:
        st.error(f"Audit log unavailable: {exc}")
        return

    rows = response.data or []
    if not rows:
        st.info("No writes recorded yet.")
        return

    df = pd.DataFrame(rows)
    st.dataframe(df.drop(columns=["id"], errors="ignore"), use_container_width=True)

    options = {f"{row['executed_at']} | {row['target_table']} | {row['operation']}": row["id"] for row in rows}
    selected = st.selectbox("View SQL", [""] + list(options.keys()))
    if selected:
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
