from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


Intent = Literal["research", "write", "query", "schema", "unknown"]
SchemaSource = Literal["user-uploaded", "ai-generated"]


class AgentState(BaseModel):
    user_message: str = ""
    session_history: list[dict[str, str]] = Field(default_factory=list)
    session_id: str | None = None
    requested_actions: dict[str, bool] = Field(default_factory=dict)

    intent: Intent | None = None
    target_table: str | None = None

    search_results: list[dict[str, Any]] = Field(default_factory=list)
    extracted_urls: list[str] = Field(default_factory=list)
    raw_extracted: dict[str, str] = Field(default_factory=dict)
    structured_rows: list[dict[str, Any]] = Field(default_factory=list)
    display_rows: list[dict[str, Any]] = Field(default_factory=list)
    structured_artifacts: list[dict[str, Any]] = Field(default_factory=list)
    active_artifact_id: str | None = None

    table_exists: bool = False
    schema_source: SchemaSource | None = None
    proposed_ddl: str | None = None

    dry_run_sql: str | None = None
    user_confirmed: bool = False

    generated_sql: str | None = None
    query_explanation: str | None = None

    response_to_user: str = ""
    error: str | None = None


def as_state(value: AgentState | dict[str, Any]) -> AgentState:
    if isinstance(value, AgentState):
        return value
    return AgentState.model_validate(value or {})
