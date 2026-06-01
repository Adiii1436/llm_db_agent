from __future__ import annotations

from typing import Any


def run(state: Any) -> dict[str, Any]:
    return {
        "response_to_user": "I need a little more detail. Should I research the web, query the database, design a schema, or prepare a write?",
        "error": None,
    }
