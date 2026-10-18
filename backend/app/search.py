"""Tavily web search and extraction."""

from __future__ import annotations

import httpx

from .config import settings

TAVILY = "https://api.tavily.com"


class SearchError(RuntimeError):
    pass


def configured() -> bool:
    return bool(settings.tavily_api_key)


def _headers() -> dict:
    if not configured():
        raise SearchError("TAVILY_API_KEY is not set")
    return {"Authorization": f"Bearer {settings.tavily_api_key}"}


def search(query: str, max_results: int = 5) -> list[dict]:
    """[{title, url, content, score}]"""
    try:
        resp = httpx.post(
            f"{TAVILY}/search",
            json={"query": query, "max_results": max_results, "search_depth": "advanced", "topic": "general"},
            headers=_headers(),
            timeout=30,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise SearchError(f"Tavily search failed: {exc}") from exc
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""), "content": r.get("content", ""),
         "score": float(r.get("score") or 0)}
        for r in resp.json().get("results", [])
        if r.get("url", "").startswith(("http://", "https://"))
    ]


def extract(urls: list[str]) -> dict[str, str]:
    """{url: full text}"""
    if not urls:
        return {}
    try:
        resp = httpx.post(f"{TAVILY}/extract", json={"urls": urls[:5]}, headers=_headers(), timeout=45)
        resp.raise_for_status()
    except (httpx.HTTPError, SearchError):
        return {}
    return {r.get("url"): (r.get("raw_content") or "")[:20000] for r in resp.json().get("results", [])}
