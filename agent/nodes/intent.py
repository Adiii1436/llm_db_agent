from __future__ import annotations

import re
from typing import Any

from agent.state import as_state
from tools.sql import normalize_identifier


VALID_INTENTS = {"research", "write", "query", "schema", "unknown"}
TABLE_NAME_STOPWORDS = {
    "a",
    "an",
    "and",
    "the",
    "should",
    "with",
    "including",
    "include",
    "includes",
    "that",
    "which",
    "database",
    "db",
}


def run(state: Any) -> dict[str, Any]:
    current = as_state(state)
    effective_message = (
        current.user_message
        if current.requested_actions.get("query_table")
        else _effective_user_message(current.user_message, current.session_history)
    )
    intent = _intent_from_actions(current.requested_actions) or _fallback_intent(effective_message)
    inferred_table = _infer_table_name(effective_message)
    artifacts = _artifacts_with_current_rows(current)
    artifact = _resolve_artifact_for_message(effective_message, artifacts)
    target_table = _resolve_target_table(intent, inferred_table, artifact, current.target_table, current.requested_actions)
    if intent == "write" and not artifact and not inferred_table and _has_research_subject(effective_message):
        target_table = None
    structured_rows = artifact.get("rows", []) if artifact else []
    extracted_urls = artifact.get("source_urls", []) if artifact else []

    if _cannot_write_without_source(intent, effective_message, artifact, current.requested_actions):
        intent = "unknown"
        response = "I do not have an extracted table in this chat to upsert. Ask me to research one first, or name the source data to write."
    elif intent == "unknown" and target_table:
        intent = "query"
        response = ""
    else:
        response = "" if intent != "unknown" else "I need a little more detail. Should I research the web, query the database, design a schema, or prepare a write?"

    target_table = normalize_identifier(target_table) if target_table else None

    return {
        "user_message": effective_message,
        "intent": intent,
        "target_table": target_table,
        "search_results": [],
        "extracted_urls": extracted_urls,
        "raw_extracted": {},
        "structured_rows": structured_rows,
        "display_rows": [],
        "table_exists": False,
        "schema_source": None,
        "proposed_ddl": None,
        "dry_run_sql": None,
        "user_confirmed": False,
        "generated_sql": None,
        "query_explanation": None,
        "structured_artifacts": artifacts,
        "response_to_user": response,
        "error": None,
    }


def _fallback_intent(message: str) -> str:
    text = message.lower()
    if _looks_like_write_request(text):
        return "write"
    if re.search(r"\b(schema|table structure|design a table)\b", text):
        return "schema"
    if re.search(r"\b(show|list|count|how many|query|filter|from database|in the table)\b", text):
        return "query"
    if re.search(r"\b(what|which|available)\b.*\btables?\b", text):
        return "query"
    if re.search(r"\b(summarize|summarise|summary|analyze|analyse|compare|cheapest|costliest|highest|lowest|average|avg)\b", text):
        return "query"
    if re.search(r"\b(find|research|search|look up|compare|what is|who is)\b", text):
        return "research"
    return "unknown"


def _intent_from_actions(actions: dict[str, bool]) -> str | None:
    if not actions:
        return None
    if actions.get("query_table"):
        return "query"
    if actions.get("upsert_table"):
        return "write"
    if actions.get("research") or actions.get("create_table"):
        return "research"
    return None


def _cannot_write_without_source(
    intent: str,
    message: str,
    artifact: dict[str, Any] | None,
    actions: dict[str, bool],
) -> bool:
    if intent != "write" or artifact or _has_research_subject(message):
        return False
    if actions and actions.get("upsert_table") and not actions.get("research"):
        return True
    return _references_previous_table(message)


def _effective_user_message(message: str, session_history: list[dict[str, str]]) -> str:
    if not _is_procedural_followup(message):
        return message

    previous = _last_substantive_user_message(message, session_history)
    if not previous:
        return message
    return f"{previous.strip()}\n\nFollow-up instruction: {message.strip()}"


def _is_procedural_followup(message: str) -> bool:
    text = message.lower()
    if _has_research_subject(message):
        return False
    return bool(
        re.search(r"\b(research|search|web|schema|write|upsert|save|store|insert|prepare|design)\b", text)
        or _references_previous_table(message)
    )


def _last_substantive_user_message(current_message: str, session_history: list[dict[str, str]]) -> str | None:
    current_text = current_message.strip()
    user_messages = [
        str(item.get("content", "")).strip()
        for item in session_history
        if item.get("role") == "user" and str(item.get("content", "")).strip()
    ]
    for message in reversed(user_messages):
        if message == current_text:
            continue
        if _has_research_subject(message) or _has_table_context(message):
            return message
    return None


def _has_research_subject(message: str) -> bool:
    text = message.lower()
    if re.search(r"\b(about|on|for|of)\s+[\w\s,.-]{8,}", text):
        return True
    return bool(
        re.search(r"\b(top|best|latest|current|recent)\s+\d*\s*[a-z][\w\s-]{3,}", text)
        or re.search(r"\b[a-z][\w-]*\s+(information|benefits|prices?|pricing|hospitals?|foods?|companies|models)\b", text)
    )


def _has_table_context(message: str) -> bool:
    text = message.lower()
    return bool(
        re.search(r"\bcolumns?\b", text)
        or re.search(r"\binclude[s]?\b.*\b(name|address|city|state|phone|price|benefit|description)\b", text)
    )


def _looks_like_write_request(text: str) -> bool:
    if re.search(r"\b(save|store|insert|update|upsert|write)\b", text):
        return True
    if re.search(r"\b(add|create|make)\b.*\b(database|db)\b", text):
        return True
    if re.search(r"\bon\s+the\s+(database|db)\b", text):
        return True

    match = re.search(r"\bcreate\s+table\s+[\"'`]?([a-zA-Z_][\w]*)[\"'`]?", text)
    return bool(match and _is_probable_table_name(match.group(1)))


def _resolve_target_table(
    intent: str,
    inferred_table: str | None,
    artifact: dict[str, Any] | None,
    current_table: str | None,
    actions: dict[str, bool] | None = None,
) -> str | None:
    if inferred_table:
        return inferred_table
    if intent == "write" and artifact:
        return artifact.get("table_name") or current_table
    if intent in {"query", "schema"}:
        return current_table
    if actions and actions.get("upsert_table"):
        return current_table
    return None


def _resolve_artifact_for_message(message: str, artifacts: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not artifacts:
        return None

    normalized_message = normalize_identifier(message)
    inferred_table = _infer_table_name(message)
    if inferred_table:
        normalized_table = normalize_identifier(inferred_table)
        for artifact in reversed(artifacts):
            if normalize_identifier(artifact.get("table_name")) == normalized_table:
                return artifact

    for artifact in reversed(artifacts):
        table_name = normalize_identifier(artifact.get("table_name"))
        if table_name and table_name in normalized_message:
            return artifact

    if _references_previous_table(message):
        return artifacts[-1]
    return None


def _artifacts_with_current_rows(current: Any) -> list[dict[str, Any]]:
    artifacts = list(current.structured_artifacts)
    if artifacts or not current.structured_rows:
        return artifacts
    table_name = normalize_identifier(current.target_table)
    return [
        {
            "id": "structured_table_1",
            "table_name": table_name,
            "user_message": current.user_message,
            "columns": sorted({key for row in current.structured_rows for key in row.keys()}),
            "rows": current.structured_rows,
            "source_urls": current.extracted_urls,
        }
    ]


def _references_previous_table(message: str) -> bool:
    text = message.lower()
    return bool(
        re.search(r"\b(this|that|the|last|latest|previous|above|created|extracted)\s+(table|rows?|data|result|results)\b", text)
        or re.search(r"\b(table|rows?|data|result|results)\s+(above|created|extracted)\b", text)
        or re.search(r"\b(upsert|save|store|write|insert)\s+(it|this|that)\b", text)
    )


def _infer_table_name(message: str) -> str | None:
    patterns = [
        r"\bcreate\s+table\s+[\"'`]?([a-zA-Z_][\w]*)[\"'`]?",
        r"\binto\s+[\"'`]?([a-zA-Z_][\w]*)[\"'`]?",
        r"\bfrom\s+[\"'`]?([a-zA-Z_][\w]*)[\"'`]?\s+table\b",
        r"\b(?:save|store|write|upsert|insert)\s+.*?\bto\s+[\"'`]?([a-zA-Z_][\w]*)[\"'`]?",
    ]
    for pattern in patterns:
        match = re.search(pattern, message, re.I)
        if match and _is_probable_table_name(match.group(1)):
            return match.group(1)
    return None


def _is_probable_table_name(value: str | None) -> bool:
    if not value:
        return False
    return value.lower() not in TABLE_NAME_STOPWORDS
