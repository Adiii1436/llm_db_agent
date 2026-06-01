from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from agent.state import as_state
from tools.sql import build_drop_not_null_ddl, build_insert_preview, normalize_identifier
from tools.supabase import get_columns


def run(state: Any) -> dict[str, Any]:
    current = as_state(state)
    table_name = normalize_identifier(current.target_table)
    parts: list[str] = []
    migration_sql = current.proposed_ddl
    if current.proposed_ddl:
        parts.append(current.proposed_ddl.strip().rstrip(";") + ";")
    elif current.table_exists and current.structured_rows:
        migration_sql = _build_existing_table_migration(table_name, current.structured_rows, current.session_id)
        if migration_sql:
            parts.append(migration_sql)
    if current.structured_rows:
        parts.append(build_insert_preview(table_name, current.structured_rows, session_id=current.session_id))
    dry_run_sql = "\n\n".join(parts) if parts else "-- No database operation was generated."

    decision = interrupt(
        {
            "kind": "write_gate",
            "dry_run_sql": dry_run_sql,
            "row_count": len(current.structured_rows),
            "target_table": table_name,
        }
    )
    confirmed = bool(decision.get("user_confirmed")) if isinstance(decision, dict) else bool(decision)
    if not confirmed:
        return {
            "dry_run_sql": dry_run_sql,
            "proposed_ddl": migration_sql,
            "user_confirmed": False,
            "error": "aborted",
            "response_to_user": "Write cancelled. No database changes were made.",
        }
    return {"dry_run_sql": dry_run_sql, "proposed_ddl": migration_sql, "user_confirmed": True, "error": None}


def _build_existing_table_migration(table_name: str, rows: list[dict[str, Any]], session_id: str | None) -> str | None:
    try:
        migration_sql = build_drop_not_null_ddl(
            table_name,
            rows,
            get_columns(table_name),
            session_id=session_id,
        )
        return migration_sql or None
    except Exception:
        return None
