from __future__ import annotations

from typing import Any

import streamlit as st

from tools.gemini import SESSION_GEMINI_API_KEY, get_model_name, has_runtime_api_key
from tools.supabase import list_research_tables, list_tables


@st.cache_data(ttl=30, show_spinner=False)
def _cached_tables() -> tuple[str, ...]:
    return tuple(list_tables())


def clear_sidebar_cache() -> None:
    _cached_tables.clear()


def _render_api_access() -> None:
    with st.container(border=True):
        st.subheader("API Access")
        st.caption("Gemini runs with your own key. Tavily and Supabase are handled by this deployment.")
        st.text_input(
            "Gemini API key",
            key=SESSION_GEMINI_API_KEY,
            type="password",
            placeholder="Paste your Gemini key",
            help="Your key is kept in this browser session and is used only for Gemini requests.",
        )
        if has_runtime_api_key():
            st.success("Gemini key added")


def render_sidebar() -> None:
    with st.sidebar:
        st.title("Web to DB Automator")
        _render_api_access()
        st.divider()

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
            gemini_api_key = st.session_state.get(SESSION_GEMINI_API_KEY, "")
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            if gemini_api_key:
                st.session_state[SESSION_GEMINI_API_KEY] = gemini_api_key
            st.rerun()
