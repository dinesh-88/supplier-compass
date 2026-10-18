import json

import pytest

from app import llm, research, sanctions, search
from app.config import settings


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
        return Resp(body)


class Resp:
    status_code = 200

    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


@pytest.fixture
def tavily(monkeypatch):
    fake = FakeTavily()
    monkeypatch.setattr(settings, "mock_search", False)
    monkeypatch.setattr(settings, "tavily_api_key", "test-key")
    monkeypatch.setattr(search.httpx, "post", fake.post)
    sanctions.reset_cache()
    yield fake
    sanctions.reset_cache()


def scripted_llm(monkeypatch):
    """LLM that triages honestly but also invents claims; the agent must reject or drop them."""

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
        if "Litigation" in user and "follow-up on the lead" not in user:
            findings.append({"url": "https://invented.example/fake", "quote": "Acme Rail Systems was fined EUR 4 million",
                             "classification": "red_flag", "severity": "critical", "summary": "invented source"})
            findings.append({"url": "", "quote": "Acme hides losses.", "classification": "red_flag",
                             "severity": "critical", "summary": "no source at all"})
            findings.append({"url": "https://news.example.com/acme-fined", "quote": "Acme Rail went bankrupt in 2023.",
                             "classification": "red_flag", "severity": "critical", "summary": "misquote"})
        return {"findings": findings}

    monkeypatch.setattr(llm, "is_mock", lambda: False)
    monkeypatch.setattr(llm, "complete_json", complete_json)
    monkeypatch.setattr(llm, "chat", lambda *a, **k: {"content": "Acme Rail Systems was fined [F1] [F99].", "tool_calls": []})


def run(company="Acme Rail Systems"):
    events = list(research.ResearchAgent(company, "Germany").run())
    report = next(e["report"] for e in events if e["type"] == "report")
    return events, report


def test_plan_covers_all_angles(tavily):
    events, _ = run()
    plan = next(e["plan"] for e in events if e["type"] == "plan")
    assert [p["angle"] for p in plan] == [a[0] for a in research.ANGLES]
    assert all('"Acme Rail Systems"' in p["query"] for p in plan)


def test_red_flag_gets_follow_up_and_budget_is_respected(tavily, monkeypatch):
    scripted_llm(monkeypatch)
    events, report = run()
    digs = [e for e in events if e["type"] == "dig"]
    assert digs, "a red flag should trigger dig-deeper"
    follow = [e for e in events if e["type"] == "search" and e.get("lead")]
    assert 1 <= len(follow) <= 2 * len(digs)
    assert any("court" in e["query"].lower() or "outcome" in e["query"].lower() for e in follow)
    assert report["searches_used"] <= settings.research_search_budget == 25
    court = [f for c in report["categories"] for f in c["evidence"] if f["url"] == "https://court.example.org/acme-ruling"]
    assert court and court[0]["followup_of"] is not None


def test_verification_drops_unsourced_claims(tavily, monkeypatch):
    scripted_llm(monkeypatch)
    events, report = run()
    urls = {f["url"] for c in report["categories"] for f in c["evidence"]}
    assert "https://invented.example/fake" not in urls and "" not in urls
    dropped = report["verification"]["dropped_unsourced"]
    assert {d["reason"] for d in dropped} == {"no source URL", "source URL was not returned by any search"}
    rejected = report["verification"]["rejected_during_triage"]
    assert any(r["reason"] == "quote not found verbatim in the source text" for r in rejected)
    # Every link shown comes from a tool result.
    returned = {u for e in events if e["type"] == "search" for u in e.get("urls", [])}
    assert urls <= returned
    # The summary cited a finding that does not exist, so the template summary is used instead.
    assert "[F99]" not in report["executive_summary"]


def test_single_source_marking(tavily, monkeypatch):
    scripted_llm(monkeypatch)
    _, report = run()
    legal = next(c for c in report["categories"] if c["key"] == "legal")
    assert legal["level"] == "High"
    fined = next(f for f in legal["evidence"] if f["url"] == "https://news.example.com/acme-fined")
    assert fined["single_source"] is False  # the court ruling (another domain, follow-up) corroborates it
    esg = next(c for c in report["categories"] if c["key"] == "esg")
    assert all(f["single_source"] for f in esg["evidence"])


def test_report_lists_searches_without_findings(tavily, monkeypatch):
    scripted_llm(monkeypatch)
    _, report = run()
    empty = {x["key"] for x in report["searched_without_findings"]}
    assert {"cyber", "supply", "ownership"} <= empty
    assert report["research_date"]
    assert report["confidence"]["level"] in {"Low", "Medium", "High"}


def test_sanctions_possible_match_is_never_confirmed(tavily):
    _, report = run()
    s = report["sanctions"]
    assert s["status"] == "possible match, verify"
    assert {m["list"] for m in s["matches"]} == {"OFAC SDN", "EU consolidated"}
    assert all(m["status"] == "possible match, verify" for m in s["matches"])
    assert "confirmed" not in json.dumps(s).lower().replace("never claim", "")
    assert sanctions.check("Siemens Mobility GmbH")["status"] == "no match"


def test_research_stream_endpoint(sample_client):
    with sample_client.stream("GET", "/api/research/stream", params={"company": "Acme Rail Systems"}) as r:
        assert r.status_code == 200
        body = "".join(r.iter_text())
    assert "event: plan" in body and "event: report" in body and "event: done" in body
    reports = sample_client.get("/api/research").json()
    assert reports and reports[0]["company"] == "Acme Rail Systems"
    full = sample_client.get(f"/api/research/{reports[0]['id']}").json()
    assert full["mock"]["search"] is True
    assert sample_client.get("/api/research/../../etc").status_code == 404
