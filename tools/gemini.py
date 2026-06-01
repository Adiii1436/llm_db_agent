from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from typing import Any

from google import genai


DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


def get_model_name() -> str:
    return os.getenv("GEMINI_MODEL", DEFAULT_MODEL)


@lru_cache(maxsize=1)
def get_client() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set.")
    return genai.Client(api_key=api_key)


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
    try:
        return json.loads(_strip_code_fence(text))
    except json.JSONDecodeError:
        match = re.search(r"(\{.*\}|\[.*\])", text, flags=re.DOTALL)
        if match:
            return json.loads(match.group(1))
        if fallback is not None:
            return fallback
        raise


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json|sql|text)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()
