from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from tavily import TavilyClient


@lru_cache(maxsize=1)
def get_tavily_client() -> TavilyClient:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY is not set.")
    return TavilyClient(api_key=api_key)


def tavily_search(query: str, max_results: int = 10) -> list[dict[str, Any]]:
    response = get_tavily_client().search(
        query=query,
        max_results=max_results,
        search_depth="advanced",
        include_answer=False,
        include_raw_content=False,
    )
    return response.get("results", [])


def tavily_extract(urls: list[str]) -> dict[str, str]:
    if not urls:
        return {}
    response = get_tavily_client().extract(urls=urls)
    extracted: dict[str, str] = {}
    for item in response.get("results", []):
        url = item.get("url")
        if url:
            extracted[url] = item.get("raw_content", "") or item.get("content", "")
    return extracted
