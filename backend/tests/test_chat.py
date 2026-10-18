from app import chat as chatmod
from app import llm


def ask(client, q, context=None):
    r = client.post("/api/chat", json={"messages": [{"role": "user", "content": q}], "context_ids": context or []})
    assert r.status_code == 200, r.text
    return r.json()


def test_financial_risk_ambiguity_shows_both_columns(sample_client):
    r = ask(sample_client, "Which of SUPP_00012, SUPP_00450 and SUPP_00731 has the lowest financial risk?")
    a = r["answer"]
    assert r["mock"] and a.startswith(llm.MOCK_LABEL)
    assert "Financial Health" in a and "Credit Rating" in a
    assert "disagree" in a
    assert "SUPP_00731 is best on Financial Health but worst on Credit Rating" in a
    assert "Lowest: **SUPP_00012**" in a
    assert "10:6" in a
    tools = [t["tool"] for t in r["trace"]]
    assert "compare" in tools and "define" in tools


def test_why_is_supp_00018_high(sample_client):
    r = ask(sample_client, "Why is the Total Risk Index of SUPP_00018 so high?")
    a = r["answer"]
    assert "**80**" in a and "Critical" in a
    assert "Operational Resilience" in a and "+4.5" in a
    assert "Compliance Risk" in a and "+3.8" in a
    assert "Governance Risk" in a and "+2.4" in a
    assert r["trace"][0]["tool"] == "explain_index"


def test_compare_these_uses_context_and_offers_ui_action(sample_client):
    ids = ["SUPP_00012", "SUPP_00450", "SUPP_00731"]
    r = ask(sample_client, "compare these", context=ids)
    assert r["actions"] == [{"type": "add_to_compare", "ids": ids}]
    assert r["charts"] and r["charts"][0]["type"] == "radar"


def test_sql_is_shown_in_trace(sample_client):
    r = ask(sample_client, "How many Critical suppliers are there?")
    assert "**384**" in r["answer"]
    assert r["trace"][0]["sql"].startswith("SELECT")


def test_chart_types_are_restricted(ds):
    from app.sqlguard import QueryEngine
    from app.tools import Toolbox, ToolError

    tb = Toolbox(ds, QueryEngine(str(ds.db_path)))
    try:
        tb.call("make_chart", {"type": "pie", "ids": ["SUPP_00001"]})
        raise AssertionError("pie should be rejected")
    except ToolError:
        pass
    tb.call("make_chart", {"type": "heatmap", "ids": ["SUPP_00001", "SUPP_00002"]})
    assert tb.charts[0]["option"]["series"][0]["type"] == "heatmap"


def test_tool_loop_with_scripted_llm(monkeypatch, ds):
    """The real loop: model calls a tool, gets the result, then answers."""
    from app.sqlguard import QueryEngine

    calls = []

    def fake_chat(messages, tools=None, **kw):
        calls.append(messages)
        if len(calls) == 1:
            return {"content": "", "tool_calls": [{"id": "1", "name": "query_suppliers",
                                                   "arguments": {"sql": "SELECT count(*) FROM suppliers WHERE total_risk_index >= 75; DROP TABLE suppliers"}}]}
        if len(calls) == 2:
            assert "Exactly one statement" in messages[-1]["content"]
            return {"content": "", "tool_calls": [{"id": "2", "name": "query_suppliers",
                                                   "arguments": {"sql": "SELECT count(*) FROM suppliers WHERE total_risk_index >= 75"}}]}
        assert '"rows": [[384]]' in messages[-1]["content"]
        return {"content": "There are 384 Critical suppliers.", "tool_calls": []}

    monkeypatch.setattr(llm, "is_mock", lambda: False)
    monkeypatch.setattr(llm, "chat", fake_chat)
    r = chatmod.run_chat(ds, QueryEngine(str(ds.db_path)), [{"role": "user", "content": "How many critical?"}], [])
    assert r["answer"] == "There are 384 Critical suppliers."
    assert r["trace"][0]["error"].startswith("Exactly one statement")
    assert r["trace"][1]["result"]["rows"] == [[384]]


def test_numbers_without_tools_are_challenged(monkeypatch, ds):
    from app.sqlguard import QueryEngine

    replies = iter([
        {"content": "About 400 suppliers are critical.", "tool_calls": []},
        {"content": "About 400 suppliers are critical.", "tool_calls": []},
    ])
    seen = []

    def fake_chat(messages, tools=None, **kw):
        seen.append(messages[-1]["content"])
        return next(replies)

    monkeypatch.setattr(llm, "is_mock", lambda: False)
    monkeypatch.setattr(llm, "chat", fake_chat)
    r = chatmod.run_chat(ds, QueryEngine(str(ds.db_path)), [{"role": "user", "content": "How many critical?"}], [])
    assert "Do not answer from memory" in seen[1]
    assert "not verified" in r["answer"]


def test_inline_toolcall_format_is_parsed(monkeypatch):
    class Resp:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": '<TOOLCALL>[{"name": "define", "arguments": {"term": "credit"}}]</TOOLCALL>'}}]}

    monkeypatch.setattr(llm, "is_mock", lambda: False)
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: Resp())
    out = llm.chat([{"role": "user", "content": "x"}], tools=[])
    assert out["tool_calls"][0]["name"] == "define"
    assert out["tool_calls"][0]["arguments"] == {"term": "credit"}
