from __future__ import annotations

import json
import re
from typing import Any

from langgraph.types import interrupt

from agent.state import as_state
from tools.gemini import generate_text
from tools.sql import append_audit_columns_to_ddl, infer_create_table, normalize_identifier


def run(state: Any) -> dict[str, Any]:
    current = as_state(state)
    table_name = normalize_identifier(current.target_table)
    schema_source = current.schema_source
    proposed_ddl = current.proposed_ddl

    if not schema_source and current.requested_actions.get("create_table"):
        schema_source = "ai-generated"

    if not schema_source:
        detected_fields = sorted({key for row in current.structured_rows for key in row.keys()})
        decision = interrupt(
            {
                "kind": "schema",
                "table_name": table_name,
                "detected_fields": detected_fields,
                "message": "Choose a schema source before any write can be prepared.",
            }
        )
        schema_source = decision.get("schema_source") if isinstance(decision, dict) else None
        proposed_ddl = decision.get("proposed_ddl") if isinstance(decision, dict) else None

    if schema_source == "user-uploaded":
        if not proposed_ddl:
            return {"error": "No schema was provided.", "response_to_user": "No schema was provided."}
        ddl = _normalize_user_schema(table_name, proposed_ddl)
    else:
        ddl = _generate_schema(table_name, current.structured_rows, current.user_message)

    return {
        "target_table": table_name,
        "schema_source": schema_source or "ai-generated",
        "proposed_ddl": ddl,
        "table_exists": False,
        "error": None,
    }


def _normalize_user_schema(table_name: str, schema_text: str) -> str:
    text = schema_text.strip().rstrip(";")
    if "CREATE TABLE" not in text.upper():
        text = f"CREATE TABLE IF NOT EXISTS {table_name} (\n{text}\n)"
    return append_audit_columns_to_ddl(text)


def _generate_schema(table_name: str, rows: list[dict[str, Any]], user_message: str) -> str:
    if not rows:
        rows = [{"notes": user_message}]
    prompt = f"""
You are a Postgres schema designer.
Produce a single CREATE TABLE IF NOT EXISTS statement for the target table.

Rules:
1. Use specific Postgres types: TEXT, INTEGER, BIGINT, DECIMAL(10,2), BOOLEAN, TIMESTAMPTZ, TEXT[], JSONB.
2. Do not add NOT NULL to extracted data columns. Web data is often partial.
3. Always include id UUID PRIMARY KEY DEFAULT gen_random_uuid().
4. Always include source_url TEXT, scraped_at TIMESTAMPTZ DEFAULT now(), session_id TEXT.
5. Use snake_case column names.
6. Return only SQL. No markdown.

Table name: {table_name}
Sample rows:
{json.dumps(rows[:3], ensure_ascii=False, indent=2)}
"""
    try:
        ddl = generate_text(prompt).strip().strip("`")
        if "CREATE TABLE" in ddl.upper():
            return append_audit_columns_to_ddl(_remove_generated_not_null(ddl))
    except Exception:
        pass
    return infer_create_table(table_name, rows)


def _remove_generated_not_null(ddl: str) -> str:
    return re.sub(r"\s+NOT\s+NULL\b", "", ddl, flags=re.IGNORECASE)
