"""Tavily web search and extraction, with a clearly labelled offline mock."""

from __future__ import annotations

import hashlib

import httpx

from .config import settings

TAVILY = "https://api.tavily.com"
MOCK_DOMAIN = "https://mock-search.invalid"


class SearchError(RuntimeError):
    pass


def is_mock() -> bool:
    return settings.mock_search or not settings.tavily_api_key


def search(query: str, max_results: int = 5) -> list[dict]:
    """[{title, url, content, score}]"""
    if is_mock():
        return mock_search(query, max_results)
    try:
        resp = httpx.post(
            f"{TAVILY}/search",
            json={"query": query, "max_results": max_results, "search_depth": "advanced", "topic": "general"},
            headers={"Authorization": f"Bearer {settings.tavily_api_key}"},
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
    if is_mock():
        return {u: MOCK_PAGES.get(u, {}).get("full", "") for u in urls}
    try:
        resp = httpx.post(
            f"{TAVILY}/extract",
            json={"urls": urls[:5]},
            headers={"Authorization": f"Bearer {settings.tavily_api_key}"},
            timeout=45,
        )
        resp.raise_for_status()
    except httpx.HTTPError:
        return {}
    return {r.get("url"): (r.get("raw_content") or "")[:20000] for r in resp.json().get("results", [])}


# --------------------------------------------------------------------------- mock

MOCK_PAGES: dict[str, dict] = {}


def _mock_page(slug: str, title: str, full: str) -> dict:
    url = f"{MOCK_DOMAIN}/{slug}"
    MOCK_PAGES[url] = {"title": title, "full": full}
    return {"title": f"[MOCK] {title}", "url": url, "content": full[:400], "score": 0.8}


def mock_search(query: str, max_results: int = 5) -> list[dict]:
    """Canned results. Every result is marked [MOCK] and points at the reserved .invalid domain."""
    q = query.lower()
    company = query.split('"')[1] if '"' in query else query.split(" ")[0]
    h = hashlib.sha1(q.encode()).hexdigest()[:8]
    if any(w in q for w in ("follow-up", "outcome", "settlement", "fined", "court")):
        return [
            _mock_page(
                f"followup-{h}", f"{company}: regulator closes the case",
                f"This is a mock article for offline demos. The regulator closed its investigation into {company} "
                f"in March 2025 after the company paid a fine of EUR 2 million. {company} said it had improved "
                "its internal controls. No further proceedings are pending.",
            )
        ][:max_results]
    if any(w in q for w in ("lawsuit", "litigation", "regulatory", "fine")):
        return [
            _mock_page(
                f"litigation-{h}", f"{company} fined over safety documentation",
                f"This is a mock article for offline demos. The national rail safety authority fined {company} "
                "for incomplete welding inspection records at one plant. The company is appealing the decision. "
                "Analysts expect limited financial impact.",
            )
        ][:max_results]
    if any(w in q for w in ("esg", "labour", "labor", "sustainab")):
        return [
            _mock_page(
                f"esg-{h}", f"{company} publishes sustainability report",
                f"This is a mock article for offline demos. {company} published its annual sustainability report "
                "and was rated in the top quartile by an ESG rating agency. The report covers emissions, "
                "workforce safety and supplier audits.",
            )
        ][:max_results]
    return [
        _mock_page(
            f"general-{h}", f"{company} company profile",
            f"This is a mock article for offline demos. {company} is a manufacturer serving the rail industry. "
            "No incidents were reported in the period covered.",
        )
    ][:max_results]
