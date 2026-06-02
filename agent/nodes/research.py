from __future__ import annotations

import json
import re
from typing import Any

from agent.state import as_state
from tools.gemini import generate_json, generate_text
from tools.sql import normalize_identifier
from tools.tavily import tavily_extract, tavily_search


URL_RE = re.compile(r"https?://[^\s)>\]]+")
MAX_EXTRACT_URLS = 5
MAX_EVIDENCE_CHARS = 32000
KEY_TERMS = (
    "price",
    "pricing",
    "token",
    "tokens",
    "million",
    "input",
    "output",
    "model",
    "tier",
    "plan",
    "api",
    "$",
)
FOOD_NUTRITION_TERMS = (
    "gen z",
    "gen-z",
    "food",
    "foods",
    "order",
    "orders",
    "ordered",
    "restaurant",
    "delivery",
    "preference",
    "preferences",
    "frequent",
    "frequency",
    "health",
    "healthy",
    "nutrition",
    "nutrient",
    "nutrients",
    "protein",
    "fiber",
    "vitamin",
    "vitamins",
    "mineral",
    "minerals",
    "sugar",
    "calorie",
    "plant-based",
    "fresh",
    "natural",
    "organic",
)


def run(state: Any) -> dict[str, Any]:
    current = as_state(state)
    if current.structured_rows:
        return {}

    try:
        urls = _urls_from_message(current.user_message)
        search_results: list[dict[str, Any]] = []
        if not urls:
            search_query = _build_search_query(current.user_message)
            search_results = tavily_search(search_query, max_results=8)
            urls = _select_urls(search_results)

        urls = urls[:MAX_EXTRACT_URLS]
        raw_extracted = tavily_extract(urls)
        if not raw_extracted and search_results:
            raw_extracted = _raw_from_search_results(search_results[:MAX_EXTRACT_URLS])

        structured_rows = _extract_rows(current, raw_extracted, search_results)
        response = _research_response(current, structured_rows, raw_extracted, search_results)
        error = None if structured_rows else "no_structured_rows"
        artifact = _build_artifact(current, structured_rows, raw_extracted)
        artifacts = _append_artifact(current.structured_artifacts, artifact) if artifact else current.structured_artifacts
        return {
            "search_results": search_results,
            "extracted_urls": list(raw_extracted.keys()),
            "raw_extracted": raw_extracted,
            "structured_rows": structured_rows,
            "display_rows": structured_rows if _should_display_table(current) else [],
            "structured_artifacts": artifacts,
            "active_artifact_id": artifact.get("id") if artifact else current.active_artifact_id,
            "target_table": artifact.get("table_name") if artifact and not current.target_table else current.target_table,
            "response_to_user": response,
            "error": error,
        }
    except Exception as exc:
        return {
            "error": str(exc),
            "response_to_user": f"I could not complete the research step: {exc}",
        }


def _urls_from_message(message: str) -> list[str]:
    return [url.rstrip(".,") for url in URL_RE.findall(message)]


def _build_search_query(message: str) -> str:
    text = message.split("Follow-up instruction:", 1)[0]
    text = re.sub(r"\b(?:and\s+)?(?:create|make)\s+an?\s+table\b.*$", "", text, flags=re.I)
    text = re.sub(r"\b(create|make)\s+table\s+[\"'`]?[a-zA-Z_][\w]*[\"'`]?", "", text, flags=re.I)
    text = re.sub(r"\b(save|store|write|insert|upsert|add)\b.*?\b(database|db)\b", "", text, flags=re.I)
    text = re.sub(r"\bon\s+the\s+database\b", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" .")
    lower = text.lower()
    if "llm" in lower and ("price" in lower or "pricing" in lower or "tier" in lower):
        return "LLM API pricing input output price per million tokens OpenAI Anthropic Google Gemini Mistral xAI"
    if _is_food_nutrition_request(lower):
        return "Gen Z food preferences most frequently ordered food items nutrients nutrition healthy food delivery restaurant trends"
    return text or message


def _select_urls(results: list[dict[str, Any]]) -> list[str]:
    if not results:
        return []
    urls: list[str] = []
    for item in sorted(results, key=lambda row: row.get("score") or 0, reverse=True):
        url = item.get("url")
        if url and url not in urls:
            urls.append(url)
    return urls[:MAX_EXTRACT_URLS]


def _extract_rows(current, raw_extracted: dict[str, str], search_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence = _build_evidence(current.user_message, raw_extracted, search_results)
    if not evidence.strip():
        return []

    field_contract = _field_contract(current.user_message, current.target_table)
    important_fields = _important_columns(current.user_message, current.target_table, [])
    prompt = f"""
You are a structured data extraction agent.
Extract rows from the evidence below.

Hard rules:
- Return only valid JSON with this exact shape: {{"rows": [{{...}}]}}
- Prefer detailed rows where user-critical fields can be filled from evidence.
- If an optional value is missing in the evidence, use null.
- Do not include rows that cannot support the important fields requested by the user.
- Do not invent prices, providers, model names, or URLs.
- One row should represent one concrete entity from the user request.
- Keep numeric price fields as numbers, not strings.
- Every row must include source_url when a URL is known.

Target table: {current.target_table or "unknown"}
User request: {current.user_message}

Expected fields:
{field_contract}

Important fields that must be complete when present in the expected fields:
{json.dumps(important_fields, ensure_ascii=False)}

Evidence:
{evidence}
"""
    extracted = generate_json(prompt, fallback={"rows": []})
    if isinstance(extracted, list):
        extracted = {"rows": extracted}
    rows = extracted.get("rows", []) if isinstance(extracted, dict) else []
    return _quality_gate_rows(current, rows, evidence)


def _build_evidence(
    user_message: str,
    raw_extracted: dict[str, str],
    search_results: list[dict[str, Any]],
) -> str:
    sections: list[str] = []
    for result in search_results[:8]:
        if result.get("url") or result.get("content"):
            sections.append(
                "\n".join(
                    [
                        f"URL: {result.get('url', '')}",
                        f"TITLE: {result.get('title', '')}",
                        f"SNIPPET: {result.get('content', '')}",
                    ]
                )
            )

    for url, raw_markdown in raw_extracted.items():
        compact = _compact_text(user_message, raw_markdown)
        if compact:
            sections.append(f"URL: {url}\nCONTENT:\n{compact}")

    evidence = "\n\n---\n\n".join(sections)
    return evidence[:MAX_EVIDENCE_CHARS]


def _compact_text(user_message: str, text: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return ""

    query_terms = {
        normalize_identifier(term)
        for term in re.findall(r"[a-zA-Z][a-zA-Z0-9_]{2,}", user_message.lower())
    }
    scored: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        lower = line.lower()
        score = sum(3 for term in _key_terms_for_message(user_message) if term in lower)
        score += sum(1 for term in query_terms if term and term in lower)
        if "$" in line or re.search(r"\b\d+(?:\.\d+)?\s*(?:/|per)\s*(?:m|million|1m)\b", lower):
            score += 4
        if score:
            scored.append((score, index, line))

    if not scored:
        return "\n".join(lines[:80])[:8000]

    selected_indexes: set[int] = set()
    for _, index, _ in sorted(scored, reverse=True)[:80]:
        for nearby in range(max(0, index - 1), min(len(lines), index + 2)):
            selected_indexes.add(nearby)
    return "\n".join(lines[index] for index in sorted(selected_indexes))[:10000]


def _key_terms_for_message(user_message: str) -> tuple[str, ...]:
    if _is_food_nutrition_request(user_message):
        return KEY_TERMS + FOOD_NUTRITION_TERMS
    return KEY_TERMS


def _is_food_nutrition_request(text: str) -> bool:
    lower = text.lower()
    return "food" in lower and (
        "gen z" in lower
        or "genz" in lower
        or "generation z" in lower
        or "nutrition" in lower
        or "nutrient" in lower
        or "healthy" in lower
        or "health" in lower
    )


def _field_contract(user_message: str, target_table: str | None) -> str:
    text = f"{user_message} {target_table or ''}".lower()
    if "food" in text and (
        "nutrition" in text
        or "nutritional" in text
        or "nutrient" in text
        or "diet" in text
        or "benefit" in text
    ):
        return json.dumps(
            {
                "preference_item": "food item, cuisine, meal type, or food category preferred by the audience",
                "audience_segment": "consumer segment, such as Gen Z, when known",
                "order_frequency_signal": "evidence about how often or commonly it is ordered, or null",
                "preference_driver": "why the audience prefers it, such as convenience, taste, value, health, or novelty",
                "key_nutrients": "nutrients or nutrition attributes mentioned in the evidence, or null",
                "marketing_note": "short implication for food delivery or restaurant marketing, or null",
                "source_url": "URL used as evidence",
            },
            indent=2,
        )
    if "llm" in text and ("pricing" in text or "price" in text or "tier" in text):
        return json.dumps(
            {
                "provider": "company/provider name",
                "model": "model or tier name",
                "product_type": "API, chat, embedding, image, or other category",
                "input_price_per_million_tokens": "number or null",
                "output_price_per_million_tokens": "number or null",
                "cached_input_price_per_million_tokens": "number or null",
                "context_window_tokens": "integer or null",
                "currency": "ISO currency code, usually USD",
                "notes": "short text for caveats",
                "source_url": "URL used as evidence",
            },
            indent=2,
        )
    return "Infer concise snake_case fields from the user request and evidence. Include source_url."


def _clean_rows(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        normalized = {normalize_identifier(str(key)): value for key, value in row.items() if key}
        meaningful_values = [
            value
            for key, value in normalized.items()
            if key not in {"source_url", "scraped_at", "session_id"} and value not in (None, "", [], {})
        ]
        if meaningful_values:
            cleaned.append(normalized)
    return cleaned


def _quality_gate_rows(current: Any, rows: Any, evidence: str) -> list[dict[str, Any]]:
    cleaned = _clean_rows(rows)
    if not cleaned:
        return []

    important_columns = _important_columns(current.user_message, current.target_table, cleaned)
    if important_columns and _has_missing_required_cells(cleaned, important_columns):
        repaired = _repair_rows_from_evidence(current, cleaned, important_columns, evidence)
        if repaired:
            cleaned = _clean_rows(repaired)

    return _prune_sparse_table(cleaned, important_columns)


def _important_columns(user_message: str, target_table: str | None, rows: list[dict[str, Any]]) -> list[str]:
    columns = _ordered_columns(rows)
    text = f"{user_message} {target_table or ''}".lower()
    important: set[str] = {"source_url"}
    if _is_food_nutrition_request(text):
        ordered = [
            "preference_item",
            "audience_segment",
            "preference_driver",
            "key_nutrients",
            "marketing_note",
            "source_url",
        ]
        if re.search(r"\b(order|ordered|orders|frequent|frequently|frequency)\b", text):
            ordered.insert(2, "order_frequency_signal")
        return ordered
    elif "llm" in text and ("pricing" in text or "price" in text or "tier" in text):
        important.update({"provider", "model", "product_type", "currency", "source_url"})
    return [column for column in columns if column in important]


def _repair_rows_from_evidence(
    current: Any,
    rows: list[dict[str, Any]],
    important_columns: list[str],
    evidence: str,
) -> list[dict[str, Any]]:
    prompt = f"""
You are a table quality reviewer for web research extraction.
Repair the extracted rows using only the evidence below.

Hard rules:
- Return only valid JSON with this exact shape: {{"rows": [{{...}}]}}
- Keep only rows that can be populated with evidence-backed values for every important column.
- Fill missing important columns with concise, specific values from the evidence.
- Do not invent facts. If a row cannot support an important column, remove that row.
- Drop optional columns that are sparse or not useful.
- Preserve source_url for every row.
- Prefer detailed but compact cell values, not blanks or nulls.

Important columns:
{json.dumps(important_columns, ensure_ascii=False)}

User request:
{current.user_message}

Current rows:
{json.dumps(rows[:40], ensure_ascii=False, default=str)}

Evidence:
{evidence[:MAX_EVIDENCE_CHARS]}
"""
    repaired = generate_json(prompt, fallback={"rows": rows})
    if isinstance(repaired, list):
        return repaired
    if isinstance(repaired, dict) and isinstance(repaired.get("rows"), list):
        return repaired["rows"]
    return rows


def _prune_sparse_table(rows: list[dict[str, Any]], important_columns: list[str]) -> list[dict[str, Any]]:
    if not rows:
        return []

    important = set(important_columns)
    complete_rows = [
        row
        for row in rows
        if all(not _is_empty_cell(row.get(column)) for column in important)
    ]
    if important and not complete_rows:
        return []
    if important:
        rows = complete_rows

    columns = _ordered_columns(rows)
    kept_columns = [
        column
        for column in columns
        if column in important or all(not _is_empty_cell(row.get(column)) for row in rows)
    ]
    if not kept_columns:
        return []

    return [
        {column: row.get(column) for column in kept_columns}
        for row in rows
        if any(not _is_empty_cell(row.get(column)) for column in kept_columns if column != "source_url")
    ]


def _has_missing_required_cells(rows: list[dict[str, Any]], columns: list[str]) -> bool:
    return any(_is_empty_cell(row.get(column)) for row in rows for column in columns)


def _ordered_columns(rows: list[dict[str, Any]]) -> list[str]:
    columns: list[str] = []
    for row in rows:
        for column in row:
            if column not in columns:
                columns.append(column)
    return columns


def _is_empty_cell(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _build_artifact(current, rows: list[dict[str, Any]], raw_extracted: dict[str, str]) -> dict[str, Any] | None:
    if not rows:
        return None
    table_name = normalize_identifier(current.target_table or _suggest_table_name(current.user_message, rows))
    columns = sorted({key for row in rows for key in row.keys()})
    next_index = _next_artifact_index(current.structured_artifacts)
    return {
        "id": f"structured_table_{next_index}",
        "table_name": table_name,
        "user_message": current.user_message,
        "columns": columns,
        "rows": rows,
        "source_urls": list(raw_extracted.keys()),
    }


def _append_artifact(artifacts: list[dict[str, Any]], artifact: dict[str, Any]) -> list[dict[str, Any]]:
    retained = [
        existing
        for existing in artifacts
        if existing.get("id") != artifact.get("id") and existing.get("rows")
    ]
    return (retained + [artifact])[-10:]


def _next_artifact_index(artifacts: list[dict[str, Any]]) -> int:
    indexes: list[int] = []
    for artifact in artifacts:
        match = re.search(r"(\d+)$", str(artifact.get("id", "")))
        if match:
            indexes.append(int(match.group(1)))
    return (max(indexes) if indexes else 0) + 1


def _suggest_table_name(user_message: str, rows: list[dict[str, Any]]) -> str:
    text = user_message.lower()
    columns = sorted({key for row in rows for key in row.keys()})
    prefixes = [
        column[:-5]
        for column in columns
        if column.endswith("_name") and column not in {"source_name"}
    ]
    if "hospital" in text and "cancer" in text:
        return "cancer_hospitals"
    if "gen" in text and "food" in text:
        return "gen_z_food_preferences"
    if "food" in text and ("nutrition" in text or "nutrient" in text or "diet" in text or "benefit" in text):
        return "food_preferences"
    if prefixes:
        prefix = prefixes[0]
        return prefix if prefix.endswith("s") else f"{prefix}s"
    return "research_results"


def _raw_from_search_results(results: list[dict[str, Any]]) -> dict[str, str]:
    raw: dict[str, str] = {}
    for index, result in enumerate(results):
        url = result.get("url") or f"search-result-{index + 1}"
        raw[url] = "\n".join(
            part
            for part in [result.get("title", ""), result.get("content", "")]
            if part
        )
    return raw


def _should_display_table(current: Any) -> bool:
    return bool(
        current.requested_actions.get("create_table")
        or current.requested_actions.get("upsert_table")
        or current.intent == "write"
    )


def _research_response(
    current: Any,
    rows: list[dict[str, Any]],
    raw_extracted: dict[str, str],
    search_results: list[dict[str, Any]],
) -> str:
    if not raw_extracted:
        return "I did not find extractable pages for that request."
    if not rows:
        return f"I extracted {len(raw_extracted)} page(s), but could not confidently structure rows from them."

    answer = _summarize_research(current.user_message, rows, raw_extracted, search_results)
    if answer:
        return answer

    columns = sorted({key for row in rows for key in row.keys() if key != "source_url"})
    if _should_display_table(current):
        return f"I found {len(rows)} relevant item(s) and extracted them into a table with columns: {', '.join(columns)}."
    return _fallback_text_summary(rows)


def _summarize_research(
    user_message: str,
    rows: list[dict[str, Any]],
    raw_extracted: dict[str, str],
    search_results: list[dict[str, Any]],
) -> str:
    prompt = f"""
Answer the user's research request using only the extracted evidence rows.

User request:
{user_message}

Extracted rows:
{json.dumps(rows[:30], ensure_ascii=False, default=str)}

Source pages:
{json.dumps(list(raw_extracted.keys()) or [result.get("url") for result in search_results[:5]], ensure_ascii=False)}

Rules:
- Give a normal prose answer, like an analyst briefing.
- Do not include a markdown table.
- Mention key patterns, caveats, and useful source-backed details.
- Keep it concise.
"""
    try:
        return generate_text(prompt).strip()
    except Exception:
        return ""


def _fallback_text_summary(rows: list[dict[str, Any]]) -> str:
    examples: list[str] = []
    for row in rows[:5]:
        values = [
            str(value)
            for key, value in row.items()
            if key != "source_url" and value not in (None, "", [], {})
        ]
        if values:
            examples.append("; ".join(values[:3]))
    if not examples:
        return f"I found {len(rows)} relevant item(s), but the extracted details were sparse."
    return "I found these main patterns: " + " ".join(f"{item}." for item in examples)
