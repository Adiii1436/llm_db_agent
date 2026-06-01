from __future__ import annotations

import re
from typing import Any

from agent.state import as_state
from tools.gemini import generate_json, generate_text
from tools.sql import ensure_select_only, normalize_identifier, quote_ident
from tools.supabase import fetch_all, get_columns, list_tables, table_exists


def run(state: Any) -> dict[str, Any]:
    current = as_state(state)
    try:
        available_tables = list_tables()
        if _is_table_list_question(current.user_message):
            table_list = "\n".join(f"- `{table}`" for table in available_tables) if available_tables else "No public tables were found."
            return {
                "intent": "query",
                "response_to_user": f"Available tables:\n{table_list}",
                "display_rows": [{"table_name": table} for table in available_tables],
                "error": None,
            }

        target_table = _resolve_table(current.target_table, current.user_message, available_tables)
        if not target_table or not table_exists(target_table):
            return _table_not_found_response(current.target_table, current.user_message, available_tables)

        columns = get_columns(target_table)
        if not columns:
            return _table_not_found_response(target_table, current.user_message, available_tables)

        prompt = f"""
You are a Postgres query generator. Generate only SELECT statements.
If the user asks for a write, return {{"error":"write_required","message":"This requires the write path."}}.

Target table:
{target_table}

Live information_schema columns:
{_to_json(columns)}

User question:
{current.user_message}

Rules:
- Query only the target table unless the user explicitly asks for joins.
- For summarize/overview questions, return rows with enough raw data to summarize, not just a count.
- Use LIMIT 200 unless the user asks for an aggregate-only answer.
- Never use INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, or TRUNCATE.

Return only JSON:
{{"sql": "SELECT ...", "explanation": "plain English description"}}
"""
        result = generate_json(prompt, fallback={})
        if result.get("error"):
            return {"intent": "write", "error": result.get("error"), "response_to_user": result.get("message")}
        sql = _fallback_sql_for_question(current.user_message, target_table, result.get("sql", ""))
        try:
            rows = fetch_all(sql)
            query_error = None
        except Exception as exc:
            query_error = str(exc)
            sql = ensure_select_only(f"SELECT * FROM {quote_ident(target_table)} LIMIT 200")
            rows = fetch_all(sql)
        answer = _answer_from_rows(current.user_message, target_table, columns, rows, result.get("explanation"))
        if query_error:
            answer = f"{answer}\n\nI answered from table rows because the generated SQL failed: `{query_error}`"
        return {
            "target_table": target_table,
            "generated_sql": sql,
            "query_explanation": result.get("explanation"),
            "structured_rows": rows,
            "display_rows": rows,
            "response_to_user": answer,
            "error": None,
        }
    except Exception as exc:
        return {"error": str(exc), "response_to_user": f"Query failed: {exc}"}


def _resolve_table(target_table: str | None, user_message: str, available_tables: list[str]) -> str | None:
    candidates: list[str] = []
    if target_table:
        candidates.append(target_table)

    quoted = re.findall(r"[\"'`]([a-zA-Z_][\w]*)[\"'`]", user_message)
    candidates.extend(quoted)
    patterns = [
        r"\btable\s+([a-zA-Z_][\w]*)",
        r"\bfrom\s+([a-zA-Z_][\w]*)",
        r"\bin\s+([a-zA-Z_][\w]*)",
    ]
    for pattern in patterns:
        match = re.search(pattern, user_message, flags=re.I)
        if match:
            candidates.append(match.group(1))

    normalized_available = {normalize_identifier(table): table for table in available_tables}
    for candidate in candidates:
        normalized = normalize_identifier(candidate)
        if normalized in normalized_available:
            return normalized_available[normalized]

    message = user_message.lower()
    mentioned = [table for table in available_tables if table.lower() in message]
    if len(mentioned) == 1:
        return mentioned[0]
    if not candidates and len(available_tables) == 1:
        return available_tables[0]
    return None


def _is_table_list_question(user_message: str) -> bool:
    text = user_message.lower()
    return bool(
        re.search(r"\b(what|which|show|list|display)\b.*\btables?\b", text)
        or re.search(r"\bavailable\s+tables?\b", text)
    )


def _table_not_found_response(
    target_table: str | None,
    user_message: str,
    available_tables: list[str],
) -> dict[str, Any]:
    requested = target_table or _best_effort_requested_table(user_message) or "the requested table"
    table_list = "\n".join(f"- `{table}`" for table in available_tables) if available_tables else "No public tables were found."
    return {
        "intent": "query",
        "structured_rows": [],
        "display_rows": [{"table_name": table} for table in available_tables],
        "response_to_user": f"I cannot find `{requested}` in Supabase.\n\nAvailable tables:\n{table_list}",
        "error": "table_not_found",
    }


def _best_effort_requested_table(user_message: str) -> str | None:
    quoted = re.findall(r"[\"'`]([a-zA-Z_][\w]*)[\"'`]", user_message)
    if quoted:
        return normalize_identifier(quoted[0])
    match = re.search(r"\btable\s+([a-zA-Z_][\w]*)", user_message, flags=re.I)
    return normalize_identifier(match.group(1)) if match else None


def _fallback_sql_for_question(user_message: str, table_name: str, generated_sql: str) -> str:
    text = user_message.lower()
    if not generated_sql or "summar" in text or "overview" in text:
        return ensure_select_only(f"SELECT * FROM {quote_ident(table_name)} LIMIT 200")
    return ensure_select_only(generated_sql)


def _answer_from_rows(
    user_message: str,
    table_name: str,
    columns: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    explanation: str | None,
) -> str:
    if not rows:
        return f"I queried `{table_name}`, but it returned no rows."

    sample_rows = rows[:80]
    prompt = f"""
Answer the user's question using only the query result rows.

User question:
{user_message}

Table:
{table_name}

Columns:
{_to_json(columns)}

SQL explanation:
{explanation or "Query completed."}

Rows:
{_to_json(sample_rows)}

Rules:
- Give the direct answer first.
- For summaries, mention notable providers/models/prices and obvious gaps/nulls.
- Do not claim facts that are not present in the rows.
- Keep it concise.
"""
    try:
        answer = generate_text(prompt).strip()
    except Exception:
        answer = ""
    if answer:
        return answer
    return f"Query completed on `{table_name}`. Returned {len(rows)} row(s)."


def _to_json(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, default=str)
