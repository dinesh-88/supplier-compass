import itertools
import math

import pytest

from app import plugins
from app.plugins import fault_tree as fta
from app.plugins.base import PluginError

from .fakes import ScriptedChatLLM, use_llm

IDS = ["SUPP_00012", "SUPP_00450", "SUPP_00731", "SUPP_00018"]


def brute_force(tree, p):
    """Enumerate every combination of basic-event states (ground truth)."""
    events = list(fta.basic_events(tree))

    def holds(n, state):
        if "ref" in n:
            return state[n["ref"]]
        if "column" in n:
            return state[n["id"]]
        vals = [holds(c, state) for c in n["children"]]
        if n["gate"] == "OR":
            return any(vals)
        if n["gate"] == "AND":
            return all(vals)
        return sum(vals) >= n["k"]

    total = 0.0
    for bits in itertools.product((0, 1), repeat=len(events)):
        state = dict(zip(events, bits))
        if holds(tree["top"], state):
            total += math.prod(p[e] if state[e] else 1 - p[e] for e in events)
    return total


TOY = {"id": "toy", "name": "toy", "top": {"id": "T", "label": "top", "gate": "OR", "children": [
    {"id": "A", "label": "a", "column": "x"},
    {"id": "G1", "label": "g1", "gate": "AND", "children": [{"id": "B", "label": "b", "column": "y"}, {"ref": "A"}]},
    {"id": "G2", "label": "g2", "gate": "VOTE", "k": 2, "children": [
        {"id": "C", "label": "c", "column": "z"}, {"id": "D", "label": "d", "column": "w"}, {"ref": "B"}]},
]}}


def test_gate_math():
    assert fta._gate("OR", [0.1, 0.2]) == pytest.approx(1 - 0.9 * 0.8)
    assert fta._gate("AND", [0.1, 0.2]) == pytest.approx(0.02)
    assert fta._gate("VOTE", [0.5, 0.5, 0.5], k=2) == pytest.approx(0.5)


def test_exact_with_repeated_events_matches_brute_force():
    fta.validate(TOY)
    p = {"A": 0.1, "B": 0.3, "C": 0.2, "D": 0.4}
    top, _ = fta.exact(TOY, p)
    assert top == pytest.approx(brute_force(TOY, p))
    naive = fta.evaluate(TOY["top"], p)
    assert naive != pytest.approx(top)  # independence-only evaluation would be wrong here


def test_minimal_cut_sets():
    cuts = {frozenset(c) for c in fta.minimal_cut_sets(TOY)}
    # A alone; A·B is absorbed by A; 2-of-3 of {C, D, B}
    assert cuts == {frozenset("A"), frozenset("CD"), frozenset("CB"), frozenset("DB")}


def test_bundled_tree_is_exact(ds):
    t = fta.load_templates()["rail_supply"]
    p = {b: 0.05 + 0.01 * k for k, b in enumerate(fta.basic_events(t))}
    assert fta.exact(t, p)[0] == pytest.approx(brute_force(t, p))


def test_invalid_trees_are_rejected():
    with pytest.raises(PluginError):
        fta.validate({"id": "x", "top": {"id": "T", "label": "t", "gate": "XOR", "children": [{"id": "A", "column": "a"}]}})
    with pytest.raises(PluginError):
        fta.validate({"id": "x", "top": {"id": "T", "label": "t", "gate": "OR", "children": [{"ref": "NOPE"}]}})


def test_registry_discovers_fault_tree(ds):
    names = {p.id: p.describe(ds) for p in plugins.all_plugins()}
    assert names["fault_tree"]["available"]
    assert {p["key"] for p in names["fault_tree"]["params"]} >= {"tree", "p_at_0", "p_at_100", "mapping"}


def test_fault_tree_run(ds):
    r = plugins.run(ds, "fault_tree", IDS)
    sups = r["data"]["suppliers"]
    probs = [s["top_probability"] for s in sups]
    assert probs == sorted(probs)  # ranked lowest first
    assert sups[-1]["supplierID"] == "SUPP_00018"  # Critical supplier is most likely to fail
    for s in sups:
        assert 0 < s["top_probability"] < 1
        assert all(0 <= x["fussell_vesely"] <= 1 for x in s["importance"])
        assert s["best_mitigation"]["top_after_mitigation"] < s["top_probability"]
    types = [b["type"] for b in r["blocks"]]
    assert types == ["text", "table", "chart", "tabs"]
    tree = r["blocks"][3]["tabs"][0]["blocks"][1]
    assert tree["type"] == "fault_tree" and tree["tree"]["gate"] == "OR"
    assert any("not calibrated" in a for a in r["assumptions"])


def test_higher_scores_mean_higher_probability(ds):
    lo = plugins.run(ds, "fault_tree", ["SUPP_00018"], {"p_at_100": 5})["data"]["suppliers"][0]["top_probability"]
    hi = plugins.run(ds, "fault_tree", ["SUPP_00018"], {"p_at_100": 20})["data"]["suppliers"][0]["top_probability"]
    assert hi > lo


def test_plugin_api(sample_client):
    lst = sample_client.get("/api/plugins").json()
    assert lst[0]["id"] == "fault_tree"
    r = sample_client.post("/api/plugins/fault_tree/run", json={"ids": IDS[:2], "params": {"mapping": "linear"}})
    assert r.status_code == 200 and r.json()["params"]["mapping"] == "linear"
    assert sample_client.post("/api/plugins/nope/run", json={"ids": IDS[:1]}).status_code == 422
    assert sample_client.post("/api/plugins/fault_tree/run", json={"ids": ["SUPP_99999"]}).status_code == 422


def test_unavailable_without_columns(other_client):
    import io

    csv = "supplierID,Total_Risk_Index,Alpha_Score\n" + "\n".join(f"S{i},50,50" for i in range(5)) + "\n"
    other_client.post("/api/dataset/upload", files={"csv": ("x.csv", io.BytesIO(csv.encode()), "text/csv")}, data={"replace": "true"})
    lst = other_client.get("/api/plugins").json()
    ft = next(p for p in lst if p["id"] == "fault_tree")
    assert not ft["available"] and "needs columns" in ft["unavailable_reason"]
    assert other_client.post("/api/plugins/fault_tree/run", json={"ids": ["S1"]}).status_code == 422
    other_client.delete("/api/dataset")


def test_chat_can_run_fault_tree(sample_client, monkeypatch):
    fake = ScriptedChatLLM([
        [("run_analysis", {"plugin": "fault_tree", "ids": IDS[:2]})],
        lambda res, _: res[0]["summary"],
    ])
    use_llm(monkeypatch, fake)
    r = sample_client.post("/api/chat", json={"messages": [{"role": "user", "content": "Run a fault tree"}]}).json()
    assert r["trace"][0]["tool"] == "run_analysis"
    assert "lowest probability that supply fails" in r["answer"]
    assert r["actions"] == [{"type": "open_analysis", "plugin": "fault_tree", "ids": IDS[:2]}]
