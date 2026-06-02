from __future__ import annotations

from typing import Any

import streamlit as st

from tools.gemini import get_model_name
from tools.supabase import list_research_tables, list_tables


@st.cache_data(ttl=30, show_spinner=False)
def _cached_tables() -> tuple[str, ...]:
    return tuple(list_tables())


def clear_sidebar_cache() -> None:
    _cached_tables.clear()

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
        
         # Initialize once
        if "research_tables" not in st.session_state:
            st.session_state.research_tables = []

        # Fetch only when user clicks refresh
        if st.button("Refresh Research Tables", use_container_width=True):
            st.session_state.research_tables = list_research_tables()

        # Always display saved tables, even after rerun
        research_tables = st.session_state.research_tables

        if research_tables:
            for table in research_tables:
                st.write(f"{table}")

        st.divider()
        if st.button("Clear Session", use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
