from __future__ import annotations

from typing import Any

from agent.state import as_state
from tools.sql import normalize_identifier
from tools.supabase import (
    ensure_system_tables,
    execute_sql,
    insert_audit_log,
    reload_postgrest_schema_cache,
    upsert_rows,
    upsert_schema_registry,
)


def run(state: Any) -> dict[str, Any]:
    current = as_state(state)
    if not current.user_confirmed:
        return {"response_to_user": "Write cancelled. No database changes were made.", "error": "aborted"}

    table_name = normalize_identifier(current.target_table)
    try:
        ensure_system_tables()
        operation = "UPSERT"
        if current.proposed_ddl:
            execute_sql(current.proposed_ddl, reload_schema=True)
            reload_postgrest_schema_cache()
            operation = "CREATE TABLE" if not current.table_exists else "ALTER TABLE"

        written = upsert_rows(table_name, current.structured_rows, session_id=current.session_id)
        display_rows = (written or current.structured_rows)[:10]
        registry_ddl = current.proposed_ddl if current.proposed_ddl and not current.table_exists else ""
        upsert_schema_registry(table_name, registry_ddl, row_count_delta=len(current.structured_rows))
        insert_audit_log(
            intent=current.intent or "write",
            target_table=table_name,
            operation=operation,
            row_count=len(current.structured_rows),
            source_urls=current.extracted_urls,
            proposed_sql=current.dry_run_sql or "",
            session_id=current.session_id,
        )
        return {
            "response_to_user": f"Write completed. {len(written) or len(current.structured_rows)} row(s) saved to `{table_name}`.",
            "display_rows": display_rows,
            "error": None,
        }
    except Exception as exc:
        return {"error": str(exc), "response_to_user": f"Database write failed: {exc}"}
