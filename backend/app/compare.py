"""Side-by-side comparison, "why A over B", and the multi-column ambiguity check."""

from __future__ import annotations

import numpy as np

from . import index_model, weights as wmod
from .dataset import Dataset, category_label

MAX_COMPARE = 20


def _ids(ds: Dataset, ids: list[str]) -> list[int]:
    out, seen = [], set()
    for sid in ids:
        i = ds.require(sid)
        if i not in seen:
            seen.add(i)
            out.append(i)
    if len(out) > MAX_COMPARE:
        raise ValueError(f"At most {MAX_COMPARE} suppliers can be compared.")
    return out


def compare(ds: Dataset, ids: list[str], weights: dict | None = None) -> dict:
    rows = _ids(ds, ids)
    custom = None if wmod.is_official(ds, weights) else wmod.custom_index(ds, weights)
    suppliers = []
    for i in rows:
        r = ds.row(i)
        r["scores"] = {
            c: {"score": float(ds.scores[i, k]), "level": index_model.level_of(ds.scores[i, k], ds.bands)}
            for k, c in enumerate(ds.score_cols)
        }
        if custom is not None:
            r["custom_index"] = float(custom["custom_index"][i])
            r["custom_rank"] = int(custom["custom_rank"][i])
            r["rank_change"] = int(custom["rank_change"][i])
        suppliers.append(r)

    sub = ds.scores[rows]
    spread = sub.std(axis=0) if len(rows) > 1 else np.zeros(len(ds.score_cols))
    rng = (sub.max(axis=0) - sub.min(axis=0)) if len(rows) else np.zeros(len(ds.score_cols))
    order = np.lexsort((-rng, -spread))
    most_different = [ds.score_cols[k] for k in order[:3]] if len(rows) > 1 else []
    return {
        "suppliers": suppliers,
        "categories": [
            {"column": c, "original": ds.original(c), "label": category_label(c), "weight_pct": int(ds.weights[k]),
             "spread_sd": round(float(spread[k]), 2), "range": float(rng[k])}
            for k, c in enumerate(ds.score_cols)
        ],
        "most_different": most_different,
        "custom_weights": custom["weights_pct"] if custom else None,
        "metrics": [{"column": c, "original": ds.original(c)} for c in ds.metrics],
        "bands": ds.bands,
        "formula": ds.formula["label"],
    }


def why(ds: Dataset, a: str, b: str, weights: dict | None = None, threshold: float = 10.0) -> dict:
    ia, ib = ds.require(a), ds.require(b)
    custom_w = None if wmod.is_official(ds, weights) else wmod.normalise(ds, weights)
    diffs = []
    for k, col in enumerate(ds.score_cols):
        sa, sb = float(ds.scores[ia, k]), float(ds.scores[ib, k])
        if abs(sa - sb) < threshold:
            continue
        item = {
            "column": col,
            "original": ds.original(col),
            "label": category_label(col),
            "score_a": sa,
            "score_b": sb,
            "difference": sb - sa,
            "better": a if sa < sb else b,
            "weight_pct": int(ds.weights[k]),
            "effect_official": round(ds.weights[k] / 100 * (sb - sa), 2),
        }
        if custom_w is not None:
            item["weight_custom_pct"] = round(float(custom_w[k]), 2)
            item["effect_custom"] = round(custom_w[k] / 100 * (sb - sa), 2)
        diffs.append(item)
    diffs.sort(key=lambda d: -abs(d["effect_official"]))
    out = {
        "a": a,
        "b": b,
        "threshold": threshold,
        "index_a": float(ds.index[ia]),
        "index_b": float(ds.index[ib]),
        "index_gap": float(ds.index[ib] - ds.index[ia]),
        "explained_by_listed": round(sum(d["effect_official"] for d in diffs), 2),
        "differences": diffs,
        "approximate": not ds.verified,
        "note": "Positive effect = B scores higher (riskier) than A in that category, adding that many index points.",
    }
    if custom_w is not None:
        out["custom_gap"] = round(float(ds.scores[ib] @ custom_w / 100 - ds.scores[ia] @ custom_w / 100), 2)
    return out


def field_comparison(ds: Dataset, ids: list[str], fields: list[str]) -> dict:
    """Values of the requested columns plus, for multi-column terms, where the columns disagree."""
    from .descriptions import define

    rows = _ids(ds, ids)
    columns: list[str] = []
    term_groups = []
    available = ds.score_cols + list(ds.metrics) + [c for c in ds.text] + ["total_risk_index"]
    for f in fields or []:
        d = define(f, ds.meta["descriptions"], available, ds.formula["weights"])
        cols = d["columns"]
        if not cols:
            continue
        columns.extend(c for c in cols if c not in columns)
        if len(cols) > 1:
            term_groups.append((f, cols))
    if not columns:
        columns = ["total_risk_index"]

    table = []
    for i in rows:
        r = {"supplierID": ds.ids[i], "name": ds.names[i]}
        for c in columns:
            r[c] = _value(ds, i, c)
        table.append(r)

    disagreements = []
    for term, cols in term_groups:
        numeric = [c for c in cols if c in ds.score_cols or c in ds.metrics or c == "total_risk_index"]
        if len(numeric) < 2:
            continue
        lower_is_better = {c: c not in ("supplier_delivery_rating", "order_confirmation_rate") for c in numeric}
        best = {}
        for c in numeric:
            vals = [(r[c], r["supplierID"]) for r in table if r[c] is not None]
            if not vals:
                continue
            pick = min(vals) if lower_is_better[c] else max(vals)
            best[c] = {"supplierID": pick[1], "value": pick[0], "direction": "lower is better" if lower_is_better[c] else "higher is better"}
        worst = {}
        for c in numeric:
            vals = [(r[c], r["supplierID"]) for r in table if r[c] is not None]
            if vals:
                pick = max(vals) if lower_is_better[c] else min(vals)
                worst[c] = {"supplierID": pick[1], "value": pick[0]}
        entry = {"term": term, "columns": numeric, "best_per_column": best, "worst_per_column": worst,
                 "columns_disagree": len({b["supplierID"] for b in best.values()}) > 1}
        score_only = [c for c in numeric if c in ds.score_cols]
        if len(score_only) >= 2:
            w = {c: ds.formula["weights"][c] for c in score_only}
            combined = []
            for r in table:
                val = sum(w[c] * r[c] for c in score_only) / sum(w.values())
                combined.append({"supplierID": r["supplierID"], "combined": round(val, 1)})
            combined.sort(key=lambda x: x["combined"])
            entry["combined"] = {
                "method": "weighted by the index weights " + ":".join(str(w[c]) for c in score_only)
                + " (" + ", ".join(f"`{c}`" for c in score_only) + ")",
                "values": combined,
                "lowest": combined[0]["supplierID"],
            }
        disagreements.append(entry)
    return {"columns": columns, "rows": table, "multi_column_terms": disagreements}


def _value(ds: Dataset, i: int, col: str):
    if col == "total_risk_index":
        return float(ds.index[i])
    if col in ds.score_cols:
        return float(ds.scores[i, ds.score_cols.index(col)])
    if col in ds.metrics:
        v = ds.metrics[col][i]
        return None if np.isnan(v) else float(v)
    if col in ds.text:
        return ds.text[col][i]
    return None
