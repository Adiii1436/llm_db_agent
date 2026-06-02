from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from typing import Any

from google import genai


DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
SESSION_GEMINI_API_KEY = "gemini_api_key"


def get_model_name() -> str:
    return os.getenv("GEMINI_MODEL", DEFAULT_MODEL)


def has_runtime_api_key() -> bool:
    return bool(_active_api_key())


def get_client() -> genai.Client:
    api_key = _active_api_key()
    if not api_key:
        raise RuntimeError("Enter your Gemini API key in the sidebar to continue.")
    return _client_for_api_key(api_key)


@lru_cache(maxsize=8)
def _client_for_api_key(api_key: str) -> genai.Client:
    return genai.Client(api_key=api_key)


def _active_api_key() -> str | None:
    session_key = _streamlit_session_api_key()
    if session_key or _in_streamlit_runtime():
        return session_key

    env_key = os.getenv("GEMINI_API_KEY")
    return env_key.strip() if env_key else None


def _streamlit_session_api_key() -> str | None:
    if not _in_streamlit_runtime():
        return None

    try:
        import streamlit as st

        api_key = st.session_state.get(SESSION_GEMINI_API_KEY, "")
    except Exception:
        return None
    return api_key.strip() or None


def _in_streamlit_runtime() -> bool:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        return get_script_run_ctx() is not None
    except Exception:
        return False


def generate_text(prompt: str, system: str = "", temperature: float = 0.2) -> str:
    client = get_client()
    full_prompt = prompt if not system else f"{system.strip()}\n\n{prompt.strip()}"
    response = client.models.generate_content(
        model=get_model_name(),
        contents=full_prompt,
    )
    return (getattr(response, "text", None) or "").strip()


def generate_json(prompt: str, system: str = "", fallback: Any | None = None) -> Any:
    text = generate_text(prompt, system=system)
    candidates = [_strip_code_fence(text)]
    match = re.search(r"(\{.*\}|\[.*\])", text, flags=re.DOTALL)
    if match:
        candidates.append(match.group(1))

    last_error: json.JSONDecodeError | None = None
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc

    if fallback is not None:
        return fallback
    if last_error:
        raise last_error
    raise ValueError("Model did not return JSON.")


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json|sql|text)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()
