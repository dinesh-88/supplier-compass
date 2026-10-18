import json

import pytest

from app import research, sanctions
from app.config import settings

from .fakes import use_research_llm, use_tavily


@pytest.fixture
def tavily(monkeypatch):
    fake = use_tavily(monkeypatch)
    use_research_llm(monkeypatch)
    sanctions.reset_cache()
    yield fake
    sanctions.reset_cache()


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
    _, report = run()
    legal = next(c for c in report["categories"] if c["key"] == "legal")
    assert legal["level"] == "High"
    fined = next(f for f in legal["evidence"] if f["url"] == "https://news.example.com/acme-fined")
    assert fined["single_source"] is False  # the court ruling (another domain, follow-up) corroborates it
    esg = next(c for c in report["categories"] if c["key"] == "esg")
    assert all(f["single_source"] for f in esg["evidence"])


def test_report_lists_searches_without_findings(tavily, monkeypatch):
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


def test_research_requires_keys():
    events = list(research.ResearchAgent("Acme Rail Systems").run())
    assert [e["type"] for e in events] == ["error"]
    assert "TAVILY_API_KEY" in events[0]["message"] and "LLM_API_KEY" in events[0]["message"]


def test_research_stream_endpoint(sample_client, tavily):
    with sample_client.stream("GET", "/api/research/stream", params={"company": "Acme Rail Systems"}) as r:
        assert r.status_code == 200
        body = "".join(r.iter_text())
    assert "event: plan" in body and "event: report" in body and "event: done" in body
    reports = sample_client.get("/api/research").json()
    assert reports and reports[0]["company"] == "Acme Rail Systems"
    full = sample_client.get(f"/api/research/{reports[0]['id']}").json()
    assert full["sources"] and all(src["url"].startswith("https://") for src in full["sources"])
    assert sample_client.get("/api/research/../../etc").status_code == 404
