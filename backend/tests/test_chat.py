from app import llm

from .fakes import IDS_RE, ScriptedChatLLM, use_llm

TRIO = ["SUPP_00012", "SUPP_00450", "SUPP_00731"]


def ask(client, q, context=None):
    r = client.post("/api/chat", json={"messages": [{"role": "user", "content": q}], "context_ids": context or []})
    assert r.status_code == 200, r.text
    return r.json()


def test_not_configured_is_an_explicit_error(sample_client):
    r = ask(sample_client, "Why is SUPP_00018 high?")
    assert r["error"] and "not configured" in r["answer"]
    assert r["trace"] == []


def test_financial_risk_ambiguity_reports_both_columns(sample_client, monkeypatch):
    def answer(results, messages):
        cmp = results[1]
        term = cmp["multi_column_terms"][0]
        lines = [f"{c}: best {b['supplierID']}" for c, b in term["best_per_column"].items()]
        if term["columns_disagree"]:
            lines.append("The columns disagree.")
        lines.append(f"Combined lowest: {term['combined']['lowest']}")
        return "\n".join(lines)

    fake = ScriptedChatLLM([
        [("define", {"term": "financial risk"}), ("compare", {"ids": TRIO, "fields": ["financial risk"]})],
        answer,
    ])
    use_llm(monkeypatch, fake)
    r = ask(sample_client, "Which of SUPP_00012, SUPP_00450 and SUPP_00731 has the lowest financial risk?")
    # The system prompt tells the model to report each column and say when they disagree.
    system = fake.requests[0][0]["content"]
    assert "report each column separately" in system and "disagree" in system
    define, compare = r["trace"][0]["result"], r["trace"][1]["result"]
    assert define["ambiguous"] and define["columns"] == ["financial_health_score", "credit_rating_score"]
    term = compare["multi_column_terms"][0]
    assert term["columns_disagree"]
    assert term["best_per_column"]["financial_health_score"]["supplierID"] == "SUPP_00731"
    assert term["worst_per_column"]["credit_rating_score"]["supplierID"] == "SUPP_00731"
    assert term["combined"]["lowest"] == "SUPP_00012"
    assert [v["combined"] for v in term["combined"]["values"]] == [55.1, 61.6, 62.4]
    assert "10:6" in term["combined"]["method"]
    assert "financial_health_score: best SUPP_00731" in r["answer"]
    assert "credit_rating_score: best SUPP_00012" in r["answer"]
    assert "disagree" in r["answer"] and "Combined lowest: SUPP_00012" in r["answer"]


def test_why_is_supp_00018_high(sample_client, monkeypatch):
    fake = ScriptedChatLLM([
        [("explain_index", {"id": "SUPP_00018"})],
        lambda res, _: ", ".join(f"{d['label']} {d['points_above_average']:+.1f}" for d in res[0]["top_drivers"][:3]),
    ])
    use_llm(monkeypatch, fake)
    r = ask(sample_client, "Why is the Total Risk Index of SUPP_00018 so high?")
    e = r["trace"][0]["result"]
    assert e["total_risk_index"] == 80 and e["level"] == "Critical" and int(e["percentile"]) == 98
    assert r["answer"] == "Operational Resilience +4.5, Compliance Risk +3.8, Governance Risk +2.4"


def test_compare_these_uses_context_and_offers_ui_action(sample_client, monkeypatch):
    def turn(messages, tools=None, **kw):
        if any(m.get("role") == "tool" for m in messages):
            return {"content": "Added.", "tool_calls": []}
        ctx = IDS_RE.findall(messages[0]["content"].split("selection:")[1])
        return {"content": "", "tool_calls": [{"id": "1", "name": "add_to_compare", "arguments": {"ids": ctx}},
                                              {"id": "2", "name": "make_chart", "arguments": {"type": "radar", "ids": ctx}}]}

    use_llm(monkeypatch, turn)
    r = ask(sample_client, "compare these", context=TRIO)
    assert r["actions"] == [{"type": "add_to_compare", "ids": TRIO}]
    assert r["charts"] and r["charts"][0]["type"] == "radar"


def test_sql_is_shown_in_trace(sample_client, monkeypatch):
    fake = ScriptedChatLLM([
        [("query_suppliers", {"sql": "SELECT count(*) AS n FROM suppliers WHERE total_risk_index >= 75"})],
        lambda res, _: f"There are {res[0]['rows'][0][0]} Critical suppliers.",
    ])
    use_llm(monkeypatch, fake)
    r = ask(sample_client, "How many Critical suppliers are there?")
    assert r["answer"] == "There are 384 Critical suppliers."
    assert r["trace"][0]["sql"].startswith("SELECT") and r["trace"][0]["sql"].endswith("LIMIT 200")


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


def test_rejected_sql_is_returned_to_the_model(monkeypatch, ds):
    from app import chat as chatmod
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

    use_llm(monkeypatch, fake_chat)
    r = chatmod.run_chat(ds, QueryEngine(str(ds.db_path)), [{"role": "user", "content": "How many critical?"}], [])
    assert r["answer"] == "There are 384 Critical suppliers."
    assert r["trace"][0]["error"].startswith("Exactly one statement")
    assert r["trace"][1]["result"]["rows"] == [[384]]


def test_numbers_without_tools_are_challenged(monkeypatch, ds):
    from app import chat as chatmod
    from app.sqlguard import QueryEngine

    seen = []

    def fake_chat(messages, tools=None, **kw):
        seen.append(messages[-1]["content"])
        return {"content": "About 400 suppliers are critical.", "tool_calls": []}

    use_llm(monkeypatch, fake_chat)
    r = chatmod.run_chat(ds, QueryEngine(str(ds.db_path)), [{"role": "user", "content": "How many critical?"}], [])
    assert "Do not answer from memory" in seen[1]
    assert "not verified" in r["answer"]


def test_inline_toolcall_format_is_parsed(monkeypatch):
    class Resp:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": '<TOOLCALL>[{"name": "define", "arguments": {"term": "credit"}}]</TOOLCALL>'}}]}

    use_llm(monkeypatch)
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: Resp())
    out = llm.chat([{"role": "user", "content": "x"}], tools=[])
    assert out["tool_calls"][0]["name"] == "define"
    assert out["tool_calls"][0]["arguments"] == {"term": "credit"}
