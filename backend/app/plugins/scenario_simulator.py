"""Scenario simulator: what a disruption described in plain language does to the portfolio.

The simulation itself lives in `app/scenarios.py` (mapping, score shocks, index recompute, alternatives);
this module only turns a `Simulation` into blocks.
"""

from __future__ import annotations

import numpy as np

from .. import scenarios
from ..dataset import Dataset
from . import register
from .base import Param, PluginError, Result, RiskAnalysisPlugin

MAX_LIST = 15


@register
class ScenarioSimulatorPlugin(RiskAnalysisPlugin):
    id = "scenario"
    name = "Scenario simulator"
    description = (
        "Describe a disruption in plain language (for example “flooding in Central Europe”). It is mapped to the "
        "risk scores it worsens; each supplier's scores rise in proportion to its exposure score, and the Total Risk "
        "Index and levels are recomputed. Shows who moves into a higher level, the purchase order volume affected, "
        "before/after for the selected suppliers and alternatives that stay low-risk."
    )
    version = "1.0"
    min_suppliers = 0
    max_suppliers = 20

    def available(self, ds: Dataset) -> tuple[bool, str]:
        if len(ds.score_cols) < 1:
            return False, "needs risk score columns"
        return True, ""

    def params(self, ds: Dataset) -> list[Param]:
        first = next(iter(scenarios.presets(ds)), None)
        return [
            Param("scenario", "Disruption", "text", first.text if first else "", widget="textarea",
                  max_length=scenarios.MAX_TEXT, placeholder="e.g. port strike in Rotterdam, rare-earth export ban",
                  help="Presets run without the LLM; your own text is mapped to risk scores by the LLM."),
            Param("severity", "Severity (%)", "number", 0, min=0, max=100, step=5, widget="slider",
                  zero_label="suggested",
                  help="At 100% an impacted score rises by the supplier's full exposure score. 0 uses the "
                       "scenario's suggested severity."),
        ]

    def presets(self, ds: Dataset) -> list[dict]:
        return [{"label": p.title, "params": {"scenario": p.text, "severity": p.severity}, "help": p.rationale}
                for p in scenarios.presets(ds)]

    def run(self, ds: Dataset, ids: list[str], params: dict) -> Result:
        try:
            sc = scenarios.resolve(ds, params["scenario"])
        except scenarios.ScenarioError as exc:
            raise PluginError(str(exc)) from exc
        sev = params["severity"] or sc.severity
        sim = scenarios.simulate(ds, sc, sev)
        return build_result(ds, sim, ids)


def _eur(v) -> str:
    if v is None or np.isnan(v):
        return "–"
    for div, unit in ((1e9, "bn"), (1e6, "M"), (1e3, "k")):
        if abs(v) >= div:
            return f"€{v / div:.{2 if div == 1e9 else 1 if div == 1e6 else 0}f}{unit}"
    return f"€{v:.0f}"


def _pct(v: float) -> str:
    return f"{v:.0%}" if v >= 0.01 or v == 0 else "<1%"


def build_result(ds: Dataset, sim: scenarios.Simulation, ids: list[str]) -> Result:
    sc = sim.scenario
    lv = sim.levels
    top = lv[-1]
    spend = ds.metrics.get("purchase_order_volume_eur")
    spend = np.nan_to_num(spend) if spend is not None else None
    total_spend = float(spend.sum()) if spend is not None else 0.0
    up = sim.moved_up
    new_top = up & (sim.level_after == top)
    top_before, top_after = int((sim.level_before == top).sum()), int((sim.level_after == top).sum())
    up_spend = float(spend[up].sum()) if spend is not None else None
    top_spend_before = float(spend[sim.level_before == top].sum()) if spend is not None else None
    top_spend_after = float(spend[sim.level_after == top].sum()) if spend is not None else None
    avg_before, avg_after = float(sim.index_before.mean()), float(sim.index_after.mean())

    def name(i):
        return ds.names[i] or ""

    def driver(i) -> str:
        j = int(np.argmax(sim.delta[i]))
        d = sim.delta[i, j]
        return f"{ds.original(ds.score_cols[j])} +{d:.0f}" if d > 0 else "–"

    impacts = ", ".join(f"{ds.original(i.column)} (×{i.weight:g})" for i in sc.impacts)
    summary = (
        f"**{sc.title}** at severity {sim.severity:.0f}%: {int(up.sum()):,} of {ds.n:,} suppliers move into a "
        f"higher risk level, {int(new_top.sum()):,} of them into {top} ({top_before:,} → {top_after:,} {top} "
        f"suppliers)."
        + (f" They carry {_eur(up_spend)} of purchase order volume ({_pct(up_spend / total_spend if total_spend else 0)} "
           f"of the total); {top} volume goes from {_eur(top_spend_before)} to {_eur(top_spend_after)}."
           if spend is not None else "")
        + f" The average Total Risk Index rises from {avg_before:.1f} to {avg_after:.1f}."
    )

    metrics = [
        {"label": "Move to a higher level", "value": f"{int(up.sum()):,}", "sub": f"of {ds.n:,} suppliers"},
        {"label": f"Newly {top}", "value": f"{int(new_top.sum()):,}", "sub": f"{top}: {top_before:,} → {top_after:,}"},
    ]
    if spend is not None:
        metrics += [
            {"label": "PO volume affected", "value": _eur(up_spend),
             "sub": f"{_pct(up_spend / total_spend if total_spend else 0)} of total, suppliers moving up"},
            {"label": f"{top} PO volume", "value": _eur(top_spend_after), "sub": f"before {_eur(top_spend_before)}"},
        ]
    else:
        metrics.append({"label": "Average index", "value": f"{avg_after:.1f}", "sub": f"before {avg_before:.1f}"})

    mapping_rows = [[ds.original(i.column), f"{i.weight:g}", i.why,
                     f"+{sim.severity / 100 * i.weight * 100:.0f}% of exposure"] for i in sc.impacts]

    blocks: list[dict] = [
        {"type": "text", "markdown": summary},
        {"type": "metrics", "items": metrics},
        {"type": "table", "title": "How the scenario was mapped",
         "columns": ["Score column", "Weight", "Why", "Increase"],
         "rows": mapping_rows,
         "note": f"Exposure measured by {ds.original(sc.exposure_column)}. "
                 + ("Preset scenario." if sc.source == "preset" else "Mapped by the LLM from your text.")
                 + (f" {sc.rationale}" if sc.rationale else "")},
    ]

    # level distribution before / after
    counts_b = [int((sim.level_before == x).sum()) for x in lv]
    counts_a = [int((sim.level_after == x).sum()) for x in lv]
    blocks.append({"type": "chart", "title": "Suppliers per risk level", "height": 260, "option": {
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "legend": {"bottom": 0},
        "grid": {"left": 60, "right": 20, "top": 16, "bottom": 48},
        "xAxis": {"type": "category", "data": lv},
        "yAxis": {"type": "value", "name": "suppliers"},
        "series": [
            {"type": "bar", "name": "Before", "data": counts_b, "barMaxWidth": 28, "itemStyle": {"color": "#a7b0b6"},
             "label": {"show": True, "position": "top", "color": "#4a5560"}},
            {"type": "bar", "name": "After", "data": counts_a, "barMaxWidth": 28, "itemStyle": {"color": "#00727f"},
             "label": {"show": True, "position": "top", "color": "#16191d"}},
        ],
    }})

    matrix = [[f"{a} before"] + [f"{int(((sim.level_before == a) & (sim.level_after == b)).sum()):,}" for b in lv]
              for a in lv]
    blocks.append({"type": "table", "title": "Level migration (rows: before, columns: after)",
                   "columns": [""] + lv, "rows": matrix})

    # suppliers moving into the top level, by spend
    rows = np.where(new_top)[0]
    if spend is not None:
        rows = rows[np.argsort(-spend[rows], kind="stable")]
    crit_rows = [[ds.ids[i], name(i), f"{sim.index_before[i]:.0f} → {sim.index_after[i]:.0f}",
                  f"{sim.level_before[i]} → {sim.level_after[i]}",
                  _eur(spend[i]) if spend is not None else "–", driver(i)] for i in rows[:MAX_LIST]]
    blocks.append({"type": "table", "title": f"Suppliers moving into {top}" + (" (largest PO volume first)" if spend is not None else ""),
                   "columns": ["Supplier", "Name", "Index", "Level", "PO volume", "Largest score increase"],
                   "rows": crit_rows or [["–", f"No supplier moves into {top} at this severity.", "", "", "", ""]],
                   "note": f"{len(rows):,} in total" + (f"; showing the first {MAX_LIST}." if len(rows) > MAX_LIST else ".")})

    # selected suppliers
    sel = [ds.pos[s] for s in ids]
    if sel:
        sel_rows = [[ds.ids[i], name(i), f"{sim.index_before[i]:.0f}", f"{sim.index_after[i]:.0f}",
                     f"+{sim.index_after[i] - sim.index_before[i]:.0f}",
                     f"{sim.level_before[i]} → {sim.level_after[i]}" if sim.level_after[i] != sim.level_before[i]
                     else f"{sim.level_after[i]} (unchanged)", driver(i)] for i in sel]
        mins = [b["min"] for b in ds.bands][1:]
        blocks.append({"type": "chart", "title": "Selected suppliers: Total Risk Index before and after",
                       "height": max(220, 44 * len(sel) + 120), "option": {
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
            "legend": {"bottom": 0},
            "grid": {"left": 90, "right": 40, "top": 28, "bottom": 70},
            "xAxis": {"type": "value", "min": 0, "max": 100, "name": "Total Risk Index", "nameLocation": "middle", "nameGap": 26},
            "yAxis": {"type": "category", "inverse": True, "data": [ds.ids[i] for i in sel]},
            "series": [
                {"type": "bar", "name": "Before", "barMaxWidth": 10, "itemStyle": {"color": "#a7b0b6"},
                 "data": [float(sim.index_before[i]) for i in sel],
                 "markLine": {"symbol": "none", "silent": True, "lineStyle": {"color": "#c3c8ce", "type": "dashed"},
                              "label": {"formatter": "{b}", "color": "#737a82", "position": "start"},
                              "data": [{"xAxis": m, "name": b["level"]} for m, b in zip(mins, ds.bands[1:])]}},
                {"type": "bar", "name": "After", "barMaxWidth": 10, "itemStyle": {"color": "#00727f"},
                 "label": {"show": True, "position": "right", "color": "#16191d"},
                 "data": [float(sim.index_after[i]) for i in sel]},
            ],
        }})
        blocks.append({"type": "table", "title": "Selected suppliers before and after",
                       "columns": ["Supplier", "Name", "Index before", "Index after", "Change", "Level", "Largest score increase"],
                       "rows": sel_rows})
    else:
        blocks.append({"type": "text", "markdown": "Add suppliers to the compare set to see their before/after risk here."})

    # alternatives
    alt = scenarios.alternatives(ds, sim, exclude=ids)
    exp_j = ds.score_cols.index(sc.exposure_column)
    rating = ds.metrics.get("supplier_delivery_rating")
    alt_rows = [[ds.ids[i], name(i), f"{sim.index_before[i]:.0f} → {sim.index_after[i]:.0f}", sim.level_after[i],
                 f"{ds.scores[i, exp_j]:.0f}", _eur(spend[i]) if spend is not None else "–",
                 f"{rating[i]:.1f}" if rating is not None and not np.isnan(rating[i]) else "–"] for i in alt]
    blocks.append({"type": "table", "title": "Alternatives that stay low-risk under this scenario",
                   "columns": ["Supplier", "Name", "Index", "Level after", ds.original(sc.exposure_column),
                               "PO volume", "Delivery rating"],
                   "rows": alt_rows or [["–", "No supplier keeps its level under this scenario.", "", "", "", "", ""]],
                   "note": f"Suppliers whose level does not change and stays {alt and sim.level_after[alt[0]] or lv[0]}: "
                           "lowest index after the scenario first, then smallest increase, then best delivery rating. "
                           "Check that they make the part you need."})

    assumptions = [
        "The data has no supplier locations, so the exposure score stands in for how hard each supplier is hit: "
        f"an impacted score rises by severity × weight × {ds.original(sc.exposure_column)}, capped at 100.",
        "The Total Risk Index is recomputed with the dataset's own weights and rounding; levels use its bands. "
        "Scores that the scenario does not touch are unchanged.",
        "This is a what-if on the scores, not a forecast. "
        + ("The mapping is a preset." if sc.source == "preset" else "The LLM chose the columns and weights shown in the mapping table; check them."),
    ]
    data = {
        "scenario": sc.as_dict(),
        "severity": sim.severity,
        "moved_up": int(up.sum()),
        "new_top_level": int(new_top.sum()),
        "top_level": top,
        "level_counts": {"before": dict(zip(lv, counts_b)), "after": dict(zip(lv, counts_a))},
        "po_volume_affected": up_spend,
        "po_volume_total": total_spend if spend is not None else None,
        "top_level_volume": {"before": top_spend_before, "after": top_spend_after},
        "selected": [{"supplierID": ds.ids[i], "index_before": float(sim.index_before[i]),
                      "index_after": float(sim.index_after[i]), "level_before": sim.level_before[i],
                      "level_after": sim.level_after[i]} for i in sel],
        "alternatives": [ds.ids[i] for i in alt],
        "into_top_level": [ds.ids[i] for i in rows[:MAX_LIST]],
    }
    data["chat"] = {k: data[k] for k in ("severity", "moved_up", "new_top_level", "top_level", "level_counts",
                                         "po_volume_affected", "po_volume_total", "top_level_volume", "selected",
                                         "alternatives")}
    data["chat"]["scenario"] = {"title": sc.title, "exposure_column": sc.exposure_column,
                                "impacts": {i.column: i.weight for i in sc.impacts}, "source": sc.source}
    data["chat"]["into_top_level_largest_volume"] = data["into_top_level"][:5]
    return Result(title=f"Scenario: {sc.title}", summary=summary.replace("**", ""), blocks=blocks,
                  assumptions=assumptions, data=data)
