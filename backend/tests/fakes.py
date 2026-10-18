"""Test-only stand-ins for the external APIs (OpenAI-compatible LLM and Tavily)."""

import json
import re

from app import llm, search
from app.config import settings


class ScriptedChatLLM:
    """Plays a fixed list of turns: each turn is a list of tool calls, or a function building the final answer
    from the tool results seen so far."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.requests = []

    def __call__(self, messages, tools=None, **kw):
        self.requests.append(messages)
        turn = self.turns.pop(0)
        if callable(turn):
            results = [json.loads(m["content"]) for m in messages if m.get("role") == "tool"]
            return {"content": turn(results, messages), "tool_calls": []}
        return {"content": "", "tool_calls": [{"id": f"c{i}", "name": n, "arguments": a} for i, (n, a) in enumerate(turn)]}


def use_llm(monkeypatch, fake=None):
    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    if fake is not None:
        monkeypatch.setattr(llm, "chat", fake)


class FakeTavily:
    """Stands in for api.tavily.com: /search returns canned results, /extract returns page text."""

    PAGES = {
        "https://news.example.com/acme-fined": (
            "Acme Rail fined by regulator",
            "Acme Rail Systems was fined EUR 4 million by the rail safety regulator in 2024 for falsified weld "
            "inspection records. The company said it would appeal.",
        ),
        "https://court.example.org/acme-ruling": (
            "Court upholds fine against Acme Rail",
            "In June 2025 the administrative court upheld the fine against Acme Rail Systems and rejected the appeal.",
        ),
        "https://esg.example.net/acme": (
            "Acme Rail ESG rating",
            "Acme Rail Systems received an improved ESG rating after cutting emissions by a third.",
        ),
    }

    def __init__(self):
        self.searches = []

    def post(self, url, json=None, headers=None, timeout=None):
        assert headers["Authorization"] == "Bearer test-key"
        if url.endswith("/search"):
            q = json["query"].lower()
            self.searches.append(q)
            if "lawsuit" in q:
                urls = ["https://news.example.com/acme-fined"]
            elif "outcome" in q or "court" in q:
                urls = ["https://court.example.org/acme-ruling"]
            elif "esg" in q:
                urls = ["https://esg.example.net/acme"]
            else:
                urls = []
            body = {"results": [{"url": u, "title": self.PAGES[u][0], "content": self.PAGES[u][1][:80], "score": 0.9} for u in urls]}
        else:
            body = {"results": [{"url": u, "raw_content": self.PAGES[u][1]} for u in json["urls"] if u in self.PAGES]}
        return _Resp(body)


class _Resp:
    status_code = 200

    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


def use_tavily(monkeypatch) -> FakeTavily:
    fake = FakeTavily()
    monkeypatch.setattr(settings, "tavily_api_key", "test-key")
    monkeypatch.setattr(search.httpx, "post", fake.post)
    return fake


def use_research_llm(monkeypatch, invent_claims: bool = True):
    """LLM for the research agent: triages honestly, and (optionally) also invents claims that must be removed."""

    def complete_json(system, user, fast=True, max_tokens=1500):
        if "plan" in system.lower():
            return {"plan": []}  # fall back to the default plan
        if "follow-up" in system.lower():
            return {"queries": ['"Acme Rail Systems" weld records fine outcome', '"Acme Rail Systems" court appeal ruling']}
        findings = []
        for url, (_, text) in FakeTavily.PAGES.items():
            if url in user:
                first = text.split(". ")[0].rstrip(".") + "."
                red = "fined" in first or "upheld" in first
                findings.append({"url": url, "quote": first, "classification": "red_flag" if red else "positive",
                                 "severity": "high" if red else "low", "summary": first[:60]})
        if invent_claims and "Litigation" in user and "follow-up on the lead" not in user:
            findings.append({"url": "https://invented.example/fake", "quote": "Acme Rail Systems was fined EUR 4 million",
                             "classification": "red_flag", "severity": "critical", "summary": "invented source"})
            findings.append({"url": "", "quote": "Acme hides losses.", "classification": "red_flag",
                             "severity": "critical", "summary": "no source at all"})
            findings.append({"url": "https://news.example.com/acme-fined", "quote": "Acme Rail went bankrupt in 2023.",
                             "classification": "red_flag", "severity": "critical", "summary": "misquote"})
        return {"findings": findings}

    use_llm(monkeypatch)
    monkeypatch.setattr(llm, "complete_json", complete_json)
    monkeypatch.setattr(llm, "chat", lambda *a, **k: {"content": "Acme Rail Systems was fined [F1] [F99].", "tool_calls": []})


IDS_RE = re.compile(r"SUPP_\d{5}")
