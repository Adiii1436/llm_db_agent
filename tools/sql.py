from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any


AUDIT_COLUMNS = {
    "source_url": "TEXT",
    "scraped_at": "TIMESTAMPTZ DEFAULT now()",
    "session_id": "TEXT",
}

WRITE_KEYWORDS = ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE")


def normalize_identifier(value: str | None, default: str = "research_results") -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9_]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    if not value or not re.match(r"^[a-z_]", value):
        return default
    return value[:63]


def quote_ident(identifier: str) -> str:
    identifier = normalize_identifier(identifier)
    return '"' + identifier.replace('"', '""') + '"'


def sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, (list, dict)):
        value = json.dumps(value, ensure_ascii=False)
    return "'" + str(value).replace("'", "''") + "'"


def extract_table_name_from_ddl(ddl: str) -> str | None:
    match = re.search(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-zA-Z_][\w.]*)", ddl, re.I)
    if not match:
        return None
    return normalize_identifier(match.group(1).split(".")[-1].strip('"'))


def infer_pg_type(values: list[Any]) -> str:
    concrete = [value for value in values if value is not None]
    if not concrete:
        return "TEXT"
    if all(isinstance(value, bool) for value in concrete):
        return "BOOLEAN"
    if all(isinstance(value, int) and not isinstance(value, bool) for value in concrete):
        return "BIGINT"
    if all(isinstance(value, (int, float, Decimal)) and not isinstance(value, bool) for value in concrete):
        return "DECIMAL(10,2)"
    if all(isinstance(value, list) and all(isinstance(item, str) for item in value) for value in concrete):
        return "TEXT[]"
    if any(isinstance(value, (dict, list)) for value in concrete):
        return "JSONB"
    return "TEXT"


def infer_create_table(table_name: str, rows: list[dict[str, Any]]) -> str:
    columns = sorted({normalize_identifier(key) for row in rows for key in row if key})
    table = quote_ident(table_name)
    lines = ["    id UUID PRIMARY KEY DEFAULT gen_random_uuid()"]
    for column in columns:
        if column in ("id", *AUDIT_COLUMNS.keys()):
            continue
        values = [row.get(column) for row in rows]
        pg_type = infer_pg_type(values)
        lines.append(f"    {quote_ident(column)} {pg_type}")
    for column, definition in AUDIT_COLUMNS.items():
        lines.append(f"    {quote_ident(column)} {definition}")
    return "CREATE TABLE IF NOT EXISTS " + table + " (\n" + ",\n".join(lines) + "\n);"


def append_audit_columns_to_ddl(ddl: str) -> str:
    ddl = ddl.strip().rstrip(";")
    lower = ddl.lower()
    additions = []
    for column, definition in AUDIT_COLUMNS.items():
        if re.search(rf"\b{re.escape(column)}\b", lower) is None:
            additions.append(f"    {quote_ident(column)} {definition}")
    if not additions:
        return ddl + ";"
    close = ddl.rfind(")")
    if close == -1:
        return ddl + ";\n"
    prefix = ddl[:close].rstrip()
    suffix = ddl[close:]
    comma = "," if not prefix.endswith("(") else ""
    return prefix + comma + "\n" + ",\n".join(additions) + "\n" + suffix + ";"


def build_insert_preview(table_name: str, rows: list[dict[str, Any]], session_id: str | None = None) -> str:
    if not rows:
        return "-- No rows to insert."
    normalized_rows = [normalize_row(row, session_id=session_id) for row in rows]
    columns = sorted({key for row in normalized_rows for key in row.keys() if key != "scraped_at"})
    values = []
    for row in normalized_rows:
        values.append("(" + ", ".join(sql_literal(row.get(column)) for column in columns) + ")")
    return (
        f"INSERT INTO {quote_ident(table_name)} ({', '.join(quote_ident(column) for column in columns)})\n"
        "VALUES\n"
        + ",\n".join(values)
        + ";"
    )


def build_drop_not_null_ddl(
    table_name: str,
    rows: list[dict[str, Any]],
    columns: list[dict[str, Any]],
    session_id: str | None = None,
) -> str:
    if not rows or not columns:
        return ""

    normalized_rows = [normalize_row(row, session_id=session_id) for row in rows]
    statements: list[str] = []
    for column in columns:
        column_name = normalize_identifier(str(column.get("column_name", "")))
        if not column_name or column_name in {"id", "scraped_at"}:
            continue
        if str(column.get("is_nullable", "")).upper() != "NO":
            continue
        if column.get("column_default") not in (None, ""):
            continue
        if any(row.get(column_name) is None for row in normalized_rows):
            statements.append(
                f"ALTER TABLE {quote_ident(table_name)} ALTER COLUMN {quote_ident(column_name)} DROP NOT NULL;"
            )
    return "\n".join(statements)


def normalize_row(row: dict[str, Any], session_id: str | None = None) -> dict[str, Any]:
    normalized = {normalize_identifier(key): value for key, value in row.items() if key}
    normalized.setdefault("source_url", row.get("source_url"))
    if session_id:
        normalized["session_id"] = session_id
    return normalized


def strip_sql_literals(sql: str) -> str:
    sql = re.sub(r"--.*?$", "", sql, flags=re.MULTILINE)
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    return re.sub(r"'(?:''|[^'])*'", "''", sql)


def ensure_select_only(sql: str) -> str:
    sql = sql.strip().rstrip(";")
    stripped = strip_sql_literals(sql)
    if not re.match(r"^\s*SELECT\b", stripped, flags=re.I):
        raise ValueError("Only SELECT statements are allowed in query mode.")
    if re.search(r"\b(" + "|".join(WRITE_KEYWORDS) + r")\b", stripped, flags=re.I):
        raise ValueError("Generated SQL contains a forbidden write keyword.")
    return sql + ";"
