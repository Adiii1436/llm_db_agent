from __future__ import annotations

from typing import Any

from agent.state import as_state
from tools.sql import normalize_identifier
from tools.supabase import table_exists


def run(state: Any) -> dict[str, Any]:
    current = as_state(state)
    table_name = normalize_identifier(current.target_table)
    try:
        exists = table_exists(table_name)
        return {"target_table": table_name, "table_exists": exists, "error": None}
    except Exception as exc:
        return {
            "target_table": table_name,
            "table_exists": False,
            "error": f"Could not check table existence: {exc}",
        }
