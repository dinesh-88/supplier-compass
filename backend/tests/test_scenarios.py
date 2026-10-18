import numpy as np
import pytest

from app import index_model, plugins, scenarios
from app.plugins.base import PluginError

from .fakes import ScriptedChatLLM, use_llm

IDS = ["SUPP_00012", "SUPP_00450", "SUPP_00731", "SUPP_00018"]
FLOOD = scenarios.PRESETS[0]


def test_shock_is_proportional_to_exposure(ds):
    sim = scenarios.simulate(ds, FLOOD, 50)
    exp = ds.scores[:, ds.score_cols.index(FLOOD.exposure_column)]
    for imp in FLOOD.impacts:
        j = ds.score_cols.index(imp.column)
        expected = np.minimum(100, np.round(ds.scores[:, j] + 0.5 * imp.weight * exp))
        assert np.array_equal(sim.scores[:, j], expected)
    untouched = [j for j, c in enumerate(ds.score_cols) if c not in {i.column for i in FLOOD.impacts}]
    assert np.array_equal(sim.scores[:, untouched], ds.scores[:, untouched])
    assert sim.scores.max() <= 100 and (sim.delta >= 0).all()


def test_index_and_levels_are_recomputed_with_the_dataset_formula(ds):
    sim = scenarios.simulate(ds, FLOOD, 80)
    assert ds.verified
    assert np.array_equal(sim.index_after, index_model.index_from_weights(sim.scores, ds.weights))
    assert all(sim.level_after[i] == index_model.level_of(sim.index_after[i], ds.bands) for i in range(0, ds.n, 97))


def test_zero_severity_changes_nothing_and_more_severity_moves_more(ds):
    zero = scenarios.simulate(ds, FLOOD, 0)
    assert np.array_equal(zero.index_after, ds.index) and not zero.moved_up.any()
    moved = [int(scenarios.simulate(ds, FLOOD, s).moved_up.sum()) for s in (20, 50, 100)]
    assert moved == sorted(moved) and moved[0] > 0


def test_alternatives_stay_low(ds):
    sim = scenarios.simulate(ds, FLOOD, 60)
    alt = scenarios.alternatives(ds, sim, exclude=IDS)
    assert len(alt) == 5
    for i in alt:
        assert sim.level_after[i] == sim.level_before[i] == ds.bands[0]["level"]
        assert ds.ids[i] not in IDS
    after = [sim.index_after[i] for i in alt]
    assert after == sorted(after)


def test_preset_run(ds):
    r = plugins.run(ds, "scenario", IDS, {"scenario": FLOOD.text, "severity": 60})
    d = r["data"]
    assert d["scenario"]["source"] == "preset" and d["severity"] == 60
    assert d["moved_up"] > d["new_top_level"] > 0
    assert d["level_counts"]["after"]["Critical"] == d["level_counts"]["before"]["Critical"] + d["new_top_level"]
    assert 0 < d["po_volume_affected"] < d["po_volume_total"]
    assert d["top_level_volume"]["after"] > d["top_level_volume"]["before"]
    assert [s["supplierID"] for s in d["selected"]] == IDS
    assert all(s["index_after"] >= s["index_before"] for s in d["selected"])
    assert len(d["alternatives"]) == 5
    assert "into Critical" in r["summary"]
    types = [b["type"] for b in r["blocks"]]
    assert types[:3] == ["text", "metrics", "table"] and types.count("chart") == 2


def test_runs_without_selected_suppliers_and_uses_suggested_severity(ds):
    r = plugins.run(ds, "scenario", [], {"scenario": "sanctions escalate", "severity": 0})
    assert r["data"]["severity"] == scenarios.PRESETS[1].severity and r["data"]["selected"] == []


def test_custom_text_needs_llm(ds):
    with pytest.raises(PluginError, match="not configured"):
        plugins.run(ds, "scenario", [], {"scenario": "port strike in Rotterdam"})


def test_llm_mapping_is_validated(ds, monkeypatch):
    use_llm(monkeypatch)
    monkeypatch.setattr(scenarios.llm, "complete_json", lambda system, user, **kw: {
        "title": "Rotterdam port strike", "exposure_column": "not_a_column",
        "impacts": [{"column": "operational_resilience_score", "weight": 3, "why": "ships wait"},
                    {"column": "DROP TABLE", "weight": 1},
                    {"column": "sub_tier_visibility_score", "weight": 0.4}],
        "severity": 250})
    r = plugins.run(ds, "scenario", IDS[:1], {"scenario": "Port strike in Rotterdam (test)"})
    sc = r["data"]["scenario"]
    assert sc["source"] == "llm"
    assert [i["column"] for i in sc["impacts"]] == ["operational_resilience_score", "sub_tier_visibility_score"]
    assert sc["impacts"][0]["weight"] == 1.0 and sc["exposure_column"] == "operational_resilience_score"
    assert r["data"]["severity"] == 100


def test_unmappable_text_is_an_error(ds, monkeypatch):
    use_llm(monkeypatch)
    monkeypatch.setattr(scenarios.llm, "complete_json", lambda *a, **kw: {"impacts": []})
    with pytest.raises(PluginError, match="does not map"):
        plugins.run(ds, "scenario", [], {"scenario": "what a lovely day (test)"})


def test_describe_has_presets_and_text_param(ds):
    d = plugins.get("scenario").describe(ds)
    assert d["min_suppliers"] == 0 and len(d["presets"]) == len(scenarios.PRESETS)
    assert {p["key"]: p["type"] for p in d["params"]} == {"scenario": "text", "severity": "number"}


def test_scenario_api_and_chat(sample_client, monkeypatch):
    r = sample_client.post("/api/plugins/scenario/run", json={"ids": IDS[:2], "params": {"scenario": FLOOD.title}})
    assert r.status_code == 200 and r.json()["data"]["scenario"]["key"] == FLOOD.key
    assert sample_client.post("/api/plugins/scenario/run", json={"ids": [], "params": {"scenario": ""}}).status_code == 422
    fake = ScriptedChatLLM([
        [("run_analysis", {"plugin": "scenario", "ids": [], "params": {"scenario": FLOOD.text, "severity": 40}})],
        lambda res, _: res[0]["summary"],
    ])
    use_llm(monkeypatch, fake)
    out = sample_client.post("/api/chat", json={"messages": [{"role": "user", "content": "What if Central Europe floods?"}]}).json()
    assert out["trace"][0]["tool"] == "run_analysis" and "higher risk level" in out["answer"]
    assert out["actions"][0]["params"] == {"scenario": FLOOD.text, "severity": 40}
