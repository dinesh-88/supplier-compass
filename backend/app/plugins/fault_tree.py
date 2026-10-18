"""Fault tree analysis (FTA) of supply failure, driven by the dataset's risk scores.

Tree templates live in `fault_trees/*.json` (edit or add files to model other top events). Gates: OR, AND,
and "k/N" voting (`"gate": "VOTE", "k": 2`). A basic event names a score column; `{"ref": "<id>"}` reuses
an event elsewhere in the tree (a repeated event).

Basic-event probability from a 0–100 risk score is an explicit, adjustable assumption:
log-linear between p(0) and p(100) by default. Events are assumed independent. The top-event probability is
exact even with repeated events (Shannon decomposition over the repeated events).
"""

from __future__ import annotations

import itertools
import json
import math
from functools import lru_cache
from pathlib import Path

from .. import index_model
from ..dataset import Dataset
from . import register
from .base import Param, PluginError, Result, RiskAnalysisPlugin

TREE_DIR = Path(__file__).parent / "fault_trees"
MAX_REPEATED = 12
MAX_CUT_SETS = 2000


# --------------------------------------------------------------------------- tree loading


@lru_cache(maxsize=None)
def load_templates() -> dict[str, dict]:
    out = {}
    for p in sorted(TREE_DIR.glob("*.json")):
        t = json.loads(p.read_text(encoding="utf-8"))
        validate(t)
        out[t["id"]] = t
    return out


def validate(t: dict) -> None:
    basics: dict[str, dict] = {}
    refs: list[str] = []
    ids: set[str] = set()

    def walk(n: dict) -> None:
        if "ref" in n:
            refs.append(n["ref"])
            return
        if n.get("id") in ids:
            raise PluginError(f"Duplicate node id {n.get('id')} in tree {t.get('id')}")
        ids.add(n["id"])
        if "column" in n:
            basics[n["id"]] = n
            return
        gate = n.get("gate")
        if gate not in ("OR", "AND", "VOTE") or not n.get("children"):
            raise PluginError(f"Node {n['id']} needs a gate (OR, AND, VOTE) and children")
        if gate == "VOTE" and not 1 <= int(n.get("k", 0)) <= len(n["children"]):
            raise PluginError(f"VOTE gate {n['id']} needs 1 ≤ k ≤ number of children")
        for c in n["children"]:
            walk(c)

    walk(t["top"])
    for r in refs:
        if r not in basics:
            raise PluginError(f"Reference {r} does not point to a basic event")


def basic_events(t: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}

    def walk(n):
        if "column" in n:
            out[n["id"]] = n
        for c in n.get("children", []):
            walk(c)

    walk(t["top"])
    return out


def occurrences(t: dict) -> dict[str, int]:
    count: dict[str, int] = {}

    def walk(n):
        bid = n.get("ref") or (n["id"] if "column" in n else None)
        if bid:
            count[bid] = count.get(bid, 0) + 1
        for c in n.get("children", []):
            walk(c)

    walk(t["top"])
    return count


# --------------------------------------------------------------------------- probability


def score_to_p(score: float, p0: float, p100: float, mapping: str) -> float:
    s = min(100.0, max(0.0, score)) / 100.0
    if mapping == "linear":
        return p0 + (p100 - p0) * s
    return p0 * (p100 / p0) ** s


def _gate(gate: str, ps: list[float], k: int = 1) -> float:
    if gate == "OR":
        return 1.0 - math.prod(1.0 - p for p in ps)
    if gate == "AND":
        return math.prod(ps)
    # VOTE: at least k of n (dynamic programming over children)
    dist = [1.0]
    for p in ps:
        nxt = [0.0] * (len(dist) + 1)
        for j, q in enumerate(dist):
            nxt[j] += q * (1 - p)
            nxt[j + 1] += q * p
        dist = nxt
    return sum(dist[k:])


def evaluate(node: dict, p: dict[str, float], out: dict[str, float] | None = None) -> float:
    """Probability of a node assuming independent inputs (exact when no event repeats below it)."""
    if "ref" in node:
        return p[node["ref"]]
    if "column" in node:
        v = p[node["id"]]
    else:
        v = _gate(node["gate"], [evaluate(c, p, out) for c in node["children"]], int(node.get("k", 1)))
    if out is not None:
        out[node["id"]] = v
    return v


def exact(t: dict, p: dict[str, float]) -> tuple[float, dict[str, float]]:
    """Exact top-event and gate probabilities, conditioning on repeated basic events."""
    repeated = [b for b, n in occurrences(t).items() if n > 1]
    if len(repeated) > MAX_REPEATED:
        raise PluginError(f"Too many repeated events ({len(repeated)}) for exact evaluation")
    top = 0.0
    gates: dict[str, float] = {}
    for states in itertools.product((0, 1), repeat=len(repeated)):
        w = 1.0
        q = dict(p)
        for b, s in zip(repeated, states):
            w *= p[b] if s else 1 - p[b]
            q[b] = float(s)
        if w == 0:
            continue
        g: dict[str, float] = {}
        top += w * evaluate(t["top"], q, g)
        for k, v in g.items():
            gates[k] = gates.get(k, 0.0) + w * v
    for b in repeated:  # basic events report their own probability, not the conditioned 0/1
        gates[b] = p[b]
    return top, gates


def minimal_cut_sets(t: dict) -> list[frozenset[str]]:
    """MOCUS: expand gates top-down into cut sets, then keep only the minimal ones."""

    def expand(n) -> list[frozenset[str]]:
        if "ref" in n:
            return [frozenset([n["ref"]])]
        if "column" in n:
            return [frozenset([n["id"]])]
        kids = [expand(c) for c in n["children"]]
        if n["gate"] == "OR":
            return [cs for k in kids for cs in k]
        if n["gate"] == "AND":
            combos = [frozenset()]
            for k in kids:
                combos = [a | b for a in combos for b in k]
                if len(combos) > MAX_CUT_SETS:
                    raise PluginError("Too many cut sets")
            return combos
        k_needed = int(n.get("k", 1))
        out = []
        for subset in itertools.combinations(kids, k_needed):
            combos = [frozenset()]
            for k in subset:
                combos = [a | b for a in combos for b in k]
            out.extend(combos)
        return out

    sets = sorted(set(expand(t["top"])), key=len)
    minimal: list[frozenset[str]] = []
    for s in sets:
        if not any(m <= s for m in minimal):
            minimal.append(s)
    return minimal


# --------------------------------------------------------------------------- plugin


@register
class FaultTreePlugin(RiskAnalysisPlugin):
    id = "fault_tree"
    name = "Fault tree analysis"
    description = (
        "Models how a supplier can fail to deliver acceptable parts as a fault tree (OR/AND gates). Each basic event's "
        "probability comes from the supplier's risk score. Computes the top-event probability, the gates that matter, "
        "minimal cut sets, importance of each cause and the most effective mitigation."
    )
    version = "1.0"
    max_suppliers = 20

    def _tree(self, key: str) -> dict:
        t = load_templates().get(key)
        if t is None:
            raise PluginError(f"Unknown fault tree {key}")
        return t

    def available(self, ds: Dataset) -> tuple[bool, str]:
        templates = load_templates()
        if not templates:
            return False, "no fault tree templates found"
        usable = [k for k, t in templates.items() if not self._missing(ds, t)]
        if not usable:
            t = next(iter(templates.values()))
            return False, "needs columns: " + ", ".join(self._missing(ds, t))
        return True, ""

    @staticmethod
    def _missing(ds: Dataset, t: dict) -> list[str]:
        return sorted({b["column"] for b in basic_events(t).values() if b["column"] not in ds.score_cols})

    def params(self, ds: Dataset) -> list[Param]:
        templates = load_templates()
        return [
            Param("tree", "Fault tree", "select", next(iter(templates), ""),
                  options=[{"value": k, "label": t["name"]} for k, t in templates.items()],
                  help="Tree templates are JSON files in backend/app/plugins/fault_trees/."),
            Param("p_at_0", "Event probability at score 0 (%)", "number", 0.1, min=0.01, max=50, step=0.05,
                  help="Assumed yearly probability of a basic event for a supplier with risk score 0."),
            Param("p_at_100", "Event probability at score 100 (%)", "number", 10.0, min=0.1, max=99, step=0.5,
                  help="Assumed yearly probability of a basic event for a supplier with risk score 100."),
            Param("mapping", "Score → probability", "select", "log",
                  options=[{"value": "log", "label": "Log-linear (each point multiplies the odds)"},
                           {"value": "linear", "label": "Linear"}]),
            Param("mitigation_points", "Mitigation scenario (score points)", "number", 20, min=1, max=50, step=1,
                  help="How much a mitigation is assumed to lower one score, to rank mitigations."),
        ]

    # ------------------------------------------------------------------ analysis

    def analyse(self, ds: Dataset, sid: str, t: dict, prm: dict) -> dict:
        i = ds.pos[sid]
        events = basic_events(t)
        p0, p100 = prm["p_at_0"] / 100.0, prm["p_at_100"] / 100.0
        if p100 <= p0:
            raise PluginError("Probability at score 100 must be higher than at score 0")
        scores = {b: float(ds.scores[i, ds.score_cols.index(e["column"])]) for b, e in events.items()}
        p = {b: score_to_p(s, p0, p100, prm["mapping"]) for b, s in scores.items()}
        top, gates = exact(t, p)

        importance = []
        for b, e in events.items():
            hi, _ = exact(t, {**p, b: 1.0})
            lo, _ = exact(t, {**p, b: 0.0})
            mitigated_score = max(0.0, scores[b] - prm["mitigation_points"])
            mit, _ = exact(t, {**p, b: score_to_p(mitigated_score, p0, p100, prm["mapping"])})
            importance.append({
                "event": b,
                "label": e["label"],
                "column": e["column"],
                "original": ds.original(e["column"]),
                "score": scores[b],
                "level": index_model.level_of(scores[b], ds.bands),
                "probability": p[b],
                "fussell_vesely": (top - lo) / top if top else 0.0,
                "birnbaum": hi - lo,
                "mitigation_score": mitigated_score,
                "top_after_mitigation": mit,
                "mitigation_gain": top - mit,
            })
        importance.sort(key=lambda r: -r["fussell_vesely"])

        cuts = []
        for cs in minimal_cut_sets(t):
            cuts.append({"events": sorted(cs), "labels": [events[b]["label"] for b in sorted(cs)],
                         "order": len(cs), "probability": math.prod(p[b] for b in cs)})
        cuts.sort(key=lambda c: -c["probability"])

        branch = max(t["top"]["children"], key=lambda c: gates.get(c.get("id"), 0.0))
        best_mit = max(importance, key=lambda r: r["mitigation_gain"])
        return {
            "supplierID": sid,
            "name": ds.names[i],
            "total_risk_index": float(ds.index[i]),
            "top_probability": top,
            "gate_probabilities": {k: v for k, v in gates.items() if k not in events},
            "largest_branch": {"id": branch["id"], "label": branch["label"], "probability": gates[branch["id"]]},
            "importance": importance,
            "cut_sets": cuts,
            "best_mitigation": best_mit,
            "tree": self._annotate(t["top"], gates, p, scores, events, ds),
        }

    def _annotate(self, n, gates, p, scores, events, ds) -> dict:
        if "ref" in n or "column" in n:
            b = n.get("ref") or n["id"]
            e = events[b]
            return {"id": b, "label": n.get("label") or e["label"], "type": "basic", "column": e["column"],
                    "original": ds.original(e["column"]), "score": scores[b],
                    "level": index_model.level_of(scores[b], ds.bands), "probability": p[b],
                    "repeated": "ref" in n or None}
        return {"id": n["id"], "label": n["label"], "type": "gate", "gate": n["gate"], "k": n.get("k"),
                "probability": gates[n["id"]],
                "children": [self._annotate(c, gates, p, scores, events, ds) for c in n["children"]]}

    def run(self, ds: Dataset, ids: list[str], params: dict) -> Result:
        t = self._tree(params["tree"])
        missing = self._missing(ds, t)
        if missing:
            raise PluginError(f"Tree {t['name']} needs columns missing from this dataset: {', '.join(missing)}")
        results = [self.analyse(ds, sid, t, params) for sid in ids]
        ranked = sorted(results, key=lambda r: r["top_probability"])
        best, worst = ranked[0], ranked[-1]

        def pct(v, d=1):
            return f"{v * 100:.{d}f}%"

        summary = (
            f"Under these assumptions, {best['supplierID']} has the lowest probability that supply fails "
            f"({pct(best['top_probability'])} per year)"
            + (f" and {worst['supplierID']} the highest ({pct(worst['top_probability'])})" if len(ranked) > 1 else "")
            + f". For {best['supplierID']} the largest branch is “{best['largest_branch']['label']}”; the most effective "
            f"single mitigation is to reduce “{best['best_mitigation']['label']}” by {params['mitigation_points']:.0f} score "
            f"points, which lowers the top event to {pct(best['best_mitigation']['top_after_mitigation'])}."
        )
        compare_rows = [
            [k + 1, r["supplierID"], r["name"], pct(r["top_probability"]), f"{r['total_risk_index']:.0f}",
             f"{r['largest_branch']['label']} ({pct(r['largest_branch']['probability'])})",
             f"{r['importance'][0]['label']} (FV {r['importance'][0]['fussell_vesely']:.2f})",
             f"{r['best_mitigation']['label']} (−{pct(r['best_mitigation']['mitigation_gain'])})"]
            for k, r in enumerate(ranked)
        ]
        branches = [c for c in t["top"]["children"] if c.get("id")]
        bar = {
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
            "legend": {"bottom": 0},
            "grid": {"left": 90, "right": 20, "top": 10, "bottom": 64},
            "xAxis": {"type": "value", "name": "branch probability (%), branches can occur together so they do not add up",
                      "nameLocation": "middle", "nameGap": 24},
            "yAxis": {"type": "category", "inverse": True, "data": [r["supplierID"] for r in ranked]},
            "series": [
                {"type": "bar", "name": b["label"], "barMaxWidth": 10, "barGap": "15%",
                 "data": [round(r["gate_probabilities"].get(b["id"], 0.0) * 100, 2) for r in ranked],
                 "itemStyle": {"color": c}}
                for b, c in zip(branches, ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#4a3aa7"])
            ],
        }
        tabs = []
        for r in results:
            imp_rows = [
                [x["label"], x["original"], f"{x['score']:.0f} {x['level']}", pct(x["probability"], 2),
                 f"{x['fussell_vesely']:.3f}", f"{x['birnbaum']:.3f}",
                 f"{x['score']:.0f}→{x['mitigation_score']:.0f}: −{pct(x['mitigation_gain'], 2)}"]
                for x in r["importance"]
            ]
            cut_rows = [[k + 1, " AND ".join(c["labels"]), c["order"], pct(c["probability"], 3)]
                        for k, c in enumerate(r["cut_sets"][:12])]
            tabs.append({
                "label": r["supplierID"],
                "blocks": [
                    {"type": "metrics", "items": [
                        {"label": "Top event probability", "value": pct(r["top_probability"]), "sub": "per year, illustrative"},
                        {"label": "Largest branch", "value": pct(r["largest_branch"]["probability"]), "sub": r["largest_branch"]["label"]},
                        {"label": "Most important cause", "value": r["importance"][0]["label"],
                         "sub": f"Fussell-Vesely {r['importance'][0]['fussell_vesely']:.2f}"},
                        {"label": "Best mitigation", "value": f"−{pct(r['best_mitigation']['mitigation_gain'])}",
                         "sub": r["best_mitigation"]["label"]},
                    ]},
                    {"type": "fault_tree", "title": f"{t['name']}: {r['supplierID']}", "tree": r["tree"]},
                    {"type": "table", "title": "Importance of each cause", "columns":
                        ["Basic event", "Score column", "Score", "Probability", "Fussell-Vesely", "Birnbaum",
                         f"Mitigation (−{params['mitigation_points']:.0f} pts)"],
                     "rows": imp_rows,
                     "note": "Fussell-Vesely: share of the top-event probability that disappears if the cause is removed. "
                             "Birnbaum: how much the top event changes per unit change of the cause's probability."},
                    {"type": "table", "title": "Minimal cut sets (most likely first)",
                     "columns": ["#", "Causes that together cause the top event", "Order", "Probability"], "rows": cut_rows,
                     "note": f"{len(r['cut_sets'])} minimal cut sets in total."},
                ],
            })
        blocks = [
            {"type": "text", "markdown": summary},
            {"type": "table", "title": "Suppliers ranked by probability of supply failure",
             "columns": ["#", "Supplier", "Name", "P(top event)", "Official index", "Largest branch",
                         "Most important cause", "Best mitigation"],
             "rows": compare_rows},
            {"type": "chart", "title": "Probability by branch (%)", "option": bar, "height": max(220, 60 * len(ranked) + 100)},
            {"type": "tabs", "tabs": tabs},
        ]
        assumptions = [
            f"Basic-event probability = {'log-linear' if params['mapping'] == 'log' else 'linear'} in the risk score, from "
            f"{params['p_at_0']:g}% at score 0 to {params['p_at_100']:g}% at score 100 (per year). Risk scores are not "
            "calibrated probabilities, so read the results as relative, not absolute.",
            "Basic events are independent. Repeated events (e.g. operations appearing under the cyber AND gate) are "
            "handled exactly.",
            f"Tree: {t['name']}. {t.get('description', '')}",
        ]
        data = {"tree": t["id"], "suppliers": [
            {k: v for k, v in r.items() if k != "tree"} for r in ranked
        ], "chat": [
            {"supplierID": r["supplierID"], "top_probability": round(r["top_probability"], 4),
             "largest_branch": r["largest_branch"]["label"],
             "top_causes": [{"cause": x["label"], "score": x["score"], "fussell_vesely": round(x["fussell_vesely"], 3)}
                            for x in r["importance"][:3]],
             "best_mitigation": {"cause": r["best_mitigation"]["label"],
                                 "top_after": round(r["best_mitigation"]["top_after_mitigation"], 4)},
             "top_cut_sets": [{"causes": c["labels"], "probability": round(c["probability"], 4)} for c in r["cut_sets"][:3]]}
            for r in ranked
        ]}
        return Result(title=f"Fault tree analysis: {t['name']}", summary=summary, blocks=blocks,
                      assumptions=assumptions, data=data)
