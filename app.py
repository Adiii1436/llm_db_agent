from __future__ import annotations

import uuid

import streamlit as st
from dotenv import load_dotenv

from ui import audit_log_ui, chat
from ui.sidebar import render_sidebar


load_dotenv()

st.set_page_config(page_title="Web to DB Automator", layout="wide")

if "messages" not in st.session_state:
    st.session_state.messages = []
if "graph_state" not in st.session_state:
    st.session_state.graph_state = {}
if "awaiting_confirmation" not in st.session_state:
    st.session_state.awaiting_confirmation = False
if "awaiting_schema" not in st.session_state:
    st.session_state.awaiting_schema = False
if "pending_interrupt" not in st.session_state:
    st.session_state.pending_interrupt = None
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())

render_sidebar()

active_view = st.segmented_control(
    "View",
    ["Chat", "Audit Log"],
    key="active_view",
    label_visibility="collapsed",
)

if active_view != "Audit Log":
    chat.render()
else:
    audit_log_ui.render()
