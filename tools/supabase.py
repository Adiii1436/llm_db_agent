from __future__ import annotations

import os
import time
from typing import Any

import psycopg2
from psycopg2.extras import Json, RealDictCursor
from supabase import Client, create_client

from tools.sql import normalize_identifier, normalize_row, quote_ident


SYSTEM_DDL = """
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS agent_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    executed_at TIMESTAMPTZ DEFAULT now(),
    intent TEXT NOT NULL,
    target_table TEXT NOT NULL,
    operation TEXT NOT NULL,
    row_count INTEGER,
    source_urls TEXT[],
    proposed_sql TEXT NOT NULL,
    session_id TEXT
);

CREATE TABLE IF NOT EXISTS schema_registry (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    table_name TEXT UNIQUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    last_updated TIMESTAMPTZ DEFAULT now(),
    description TEXT,
    ddl TEXT NOT NULL,
    row_count INTEGER DEFAULT 0
);
"""


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is not set.")
    return value


def get_supabase_client() -> Client:
    return create_client(
        supabase_url=_require_env("SUPABASE_URL"),
        supabase_key=_require_env("SUPABASE_SERVICE_ROLE_KEY"),
    )


def get_pg_connection():
    return psycopg2.connect(
        host=_require_env("SUPABASE_DB_HOST"),
        port=os.getenv("SUPABASE_DB_PORT", "5432"),
        dbname=os.getenv("SUPABASE_DB_NAME", "postgres"),
        user=os.getenv("SUPABASE_DB_USER", "postgres"),
        password=_require_env("SUPABASE_DB_PASSWORD"),
        sslmode=os.getenv("SUPABASE_DB_SSLMODE", "require"),
    )


def execute_sql(sql: str, *, reload_schema: bool = False) -> None:
    with get_pg_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            if reload_schema:
                cur.execute("NOTIFY pgrst, 'reload schema'")
        conn.commit()


def fetch_all(sql: str, params: tuple[Any, ...] | None = None) -> list[dict[str, Any]]:
    with get_pg_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]


def ensure_system_tables() -> None:
    execute_sql(SYSTEM_DDL, reload_schema=True)


def table_exists(table_name: str) -> bool:
    table_name = normalize_identifier(table_name)
    rows = fetch_all(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = %s
        ) AS exists
        """,
        (table_name,),
    )
    return bool(rows and rows[0]["exists"])


def list_tables() -> list[str]:
    rows = fetch_all(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_type = 'BASE TABLE'
        ORDER BY table_name
        """
    )
    return [str(row["table_name"]) for row in rows]


def list_research_tables() -> list[str]:
    actual_tables = [
        table
        for table in list_tables()
        if table not in {"agent_audit_log", "schema_registry"}
    ]
    
    return actual_tables


def get_columns(table_name: str | None = None) -> list[dict[str, Any]]:
    params: tuple[Any, ...] | None = None
    condition = "table_schema = 'public'"
    if table_name:
        condition += " AND table_name = %s"
        params = (normalize_identifier(table_name),)
    return fetch_all(
        f"""
        SELECT table_name, column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE {condition}
        ORDER BY table_name, ordinal_position
        """,
        params,
    )


def upsert_rows(table_name: str, rows: list[dict[str, Any]], session_id: str | None = None) -> list[dict[str, Any]]:
    if not rows:
        return []
    payload = [normalize_row(row, session_id=session_id) for row in rows]
    table_name = normalize_identifier(table_name)
    last_error: Exception | None = None
    for _ in range(3):
        try:
            response = get_supabase_client().table(table_name).upsert(payload).execute()
            return response.data or []
        except Exception as exc:
            last_error = exc
            if not _is_schema_cache_error(exc):
                raise
            reload_postgrest_schema_cache()
            time.sleep(1)
    return insert_rows_direct(table_name, rows, session_id=session_id, cause=last_error)


def reload_postgrest_schema_cache() -> None:
    execute_sql("NOTIFY pgrst, 'reload schema'")


def insert_rows_direct(
    table_name: str,
    rows: list[dict[str, Any]],
    session_id: str | None = None,
    cause: Exception | None = None,
) -> list[dict[str, Any]]:
    if not rows:
        return []

    table_name = normalize_identifier(table_name)
    column_meta = {row["column_name"]: row for row in get_columns(table_name)}
    if not column_meta:
        message = f"Table `{table_name}` does not exist or has no visible columns."
        if cause:
            message += f" Original Supabase error: {cause}"
        raise RuntimeError(message)

    payload = []
    for row in rows:
        normalized = normalize_row(row, session_id=session_id)
        filtered = {key: value for key, value in normalized.items() if key in column_meta}
        if filtered:
            payload.append(filtered)

    if not payload:
        return []

    inserted: list[dict[str, Any]] = []
    with get_pg_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            for row in payload:
                columns = list(row.keys())
                placeholders = ", ".join(["%s"] * len(columns))
                sql = (
                    f"INSERT INTO {quote_ident(table_name)} "
                    f"({', '.join(quote_ident(column) for column in columns)}) "
                    f"VALUES ({placeholders}) RETURNING *"
                )
                values = [_adapt_value(row[column], column_meta[column]) for column in columns]
                cur.execute(sql, values)
                inserted.append(dict(cur.fetchone()))
        conn.commit()
    return inserted


def _adapt_value(value: Any, column_meta: dict[str, Any]) -> Any:
    if value is None:
        return None
    data_type = str(column_meta.get("data_type", "")).lower()
    if data_type in {"json", "jsonb"}:
        return Json(value)
    if isinstance(value, dict):
        return Json(value)
    if isinstance(value, list) and data_type != "array":
        return Json(value)
    return value


def _is_schema_cache_error(exc: Exception) -> bool:
    text = str(exc)
    return "PGRST205" in text or "schema cache" in text.lower()


def insert_audit_log(
    *,
    intent: str,
    target_table: str,
    operation: str,
    row_count: int,
    source_urls: list[str],
    proposed_sql: str,
    session_id: str | None,
) -> None:
    payload = {
        "intent": intent,
        "target_table": normalize_identifier(target_table),
        "operation": operation,
        "row_count": row_count,
        "source_urls": source_urls,
        "proposed_sql": proposed_sql,
        "session_id": session_id,
    }
    for attempt in range(3):
        try:
            get_supabase_client().table("agent_audit_log").insert(payload).execute()
            return
        except Exception as exc:
            if attempt == 2 or not _is_schema_cache_error(exc):
                raise
            reload_postgrest_schema_cache()
            time.sleep(1)


def upsert_schema_registry(table_name: str, ddl: str, row_count_delta: int = 0) -> None:
    client = get_supabase_client()
    table_name = normalize_identifier(table_name)
    existing = _select_schema_registry_row(client, table_name)
    current_count = (existing.data or [{}])[0].get("row_count", 0) if existing.data else 0
    current_ddl = (existing.data or [{}])[0].get("ddl", "") if existing.data else ""
    payload = {
        "table_name": table_name,
        "ddl": ddl or current_ddl or "-- Existing table; DDL not available.",
        "row_count": int(current_count or 0) + row_count_delta,
    }
    for attempt in range(3):
        try:
            client.table("schema_registry").upsert(payload, on_conflict="table_name").execute()
            return
        except Exception as exc:
            if attempt == 2 or not _is_schema_cache_error(exc):
                raise
            reload_postgrest_schema_cache()
            time.sleep(1)


def _select_schema_registry_row(client: Client, table_name: str):
    for attempt in range(3):
        try:
            return client.table("schema_registry").select("row_count, ddl").eq("table_name", table_name).execute()
        except Exception as exc:
            if attempt == 2 or not _is_schema_cache_error(exc):
                raise
            reload_postgrest_schema_cache()
            time.sleep(1)
