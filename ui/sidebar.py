from __future__ import annotations

from typing import Any

import streamlit as st

from tools.gemini import get_model_name
from tools.supabase import list_research_tables, list_tables


@st.cache_data(ttl=30, show_spinner=False)
def _cached_tables() -> tuple[str, ...]:
    return tuple(list_tables())


@st.cache_data(ttl=30, show_spinner=False)
def _cached_research_tables() -> list[dict[str, Any]]:
    return list_research_tables()


def clear_sidebar_cache() -> None:
    _cached_tables.clear()
    _cached_research_tables.clear()


def render_sidebar() -> None:
    with st.sidebar:
        st.title("Web to DB Automator")
        try:
            _cached_tables()
            st.success("Supabase connected")
        except Exception as exc:
            st.error(f"Supabase unavailable: {exc}")

        thread_id = st.session_state.get("thread_id", "")
        st.caption(f"Session: `{thread_id[:8] or '-'} `")
        st.selectbox("Model", [get_model_name()], disabled=True)
        st.divider()
        st.subheader("Research Tables")
        
        st.markdown('<p style="font-size: 12px; color: gray;">To preview tables, click the button below.</p>', unsafe_allow_html=True)
        
        if st.button("Refresh tables", use_container_width=True):
            try:
                rows = _cached_research_tables()
                if not rows:
                    flag = False
                    st.caption("No tables yet.")
                for row in rows:
                    count = row.get("row_count")
                    count_text = "unknown" if count is None else str(count)
                    st.markdown(f"**{row['table_name']}** - {count_text} rows")
            except Exception:
                st.caption("No tables yet.")

        st.divider()
        if st.button("Clear Session", use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
