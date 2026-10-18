"""Buyer weights: presets, custom index and rank changes. The official index is never modified."""

from __future__ import annotations

import numpy as np

from . import index_model
from .dataset import Dataset, competition_rank

# Each preset multiplies the official weights of matching categories, then renormalises to 100 %.
PRESETS = {
    "official": {
        "label": "Official index",
        "why": "The weights reconstructed from the dataset's Total_Risk_Index.",
        "boost": {},
    },
    "safety_critical": {
        "label": "Safety-critical component",
        "why": "Brakes, bogies, couplers: a failure endangers passengers, so safety, quality, operations and "
        "compliance count more.",
        "boost": {"safety_incident": 2.5, "quality_risk": 2.0, "operational_resilience": 1.6, "compliance_risk": 2.0},
    },
    "long_term_partner": {
        "label": "Long-term partner",
        "why": "A multi-year framework agreement depends on the supplier staying solvent and well run, so "
        "financial, credit, governance and ESG scores count more.",
        "boost": {"financial_health": 2.0, "credit_rating": 2.5, "governance_risk": 2.5, "esg_performance": 2.5},
    },
    "commodity": {
        "label": "Commodity part",
        "why": "Fasteners, cables, consumables: alternatives exist, so what matters is reliable, uninterrupted "
        "delivery.",
        "boost": {
            "operational_resilience": 2.5,
            "sub_tier_visibility": 2.0,
            "labor_stability": 2.0,
            "environmental_exposure": 1.8,
            "geopolitical_risk": 1.5,
        },
    },
}


def preset_weights(ds: Dataset, preset: str) -> dict[str, int]:
    spec = PRESETS[preset]
    raw = []
    for col, w in zip(ds.score_cols, ds.weights):
        raw.append(w * spec["boost"].get(col.removesuffix("_score"), 1.0))
    snapped = index_model.snap_to_percent(np.array(raw, dtype=float))
    return {c: int(w) for c, w in zip(ds.score_cols, snapped)}


def presets_for(ds: Dataset) -> list[dict]:
    out = []
    for key, spec in PRESETS.items():
        boosted = [c for c in ds.score_cols if c.removesuffix("_score") in spec["boost"]]
        if key != "official" and not boosted:
            continue
        out.append(
            {"key": key, "label": spec["label"], "why": spec["why"], "weights": preset_weights(ds, key),
             "raised": boosted}
        )
    return out


def normalise(ds: Dataset, weights: dict[str, float]) -> np.ndarray:
    """Buyer weights in the dataset's column order, as percentages summing to 100."""
    w = np.array([max(0.0, float(weights.get(c, 0.0))) for c in ds.score_cols], dtype=float)
    if w.sum() <= 0:
        raise ValueError("At least one weight must be above zero.")
    return w / w.sum() * 100.0


def custom_index(ds: Dataset, weights: dict[str, float]) -> dict:
    w = normalise(ds, weights)
    if np.allclose(w, ds.weights, atol=0.01):
        # Official weights reproduce the official index and ranks exactly.
        return {
            "weights_pct": {c: float(x) for c, x in zip(ds.score_cols, ds.weights)},
            "custom_index": ds.index.copy(),
            "custom_rank": ds.official_rank.copy(),
            "rank_change": np.zeros(ds.n, dtype=np.int64),
        }
    raw = ds.scores @ w / 100.0
    value = np.round(raw, 1)
    rank = competition_rank(np.round(raw, 6))
    return {
        "weights_pct": {c: round(float(x), 2) for c, x in zip(ds.score_cols, w)},
        "custom_index": value,
        "custom_rank": rank,
        "rank_change": ds.official_rank - rank,  # positive = moves up (less risky relative to others)
    }


def is_official(ds: Dataset, weights: dict[str, float] | None) -> bool:
    if not weights:
        return True
    w = normalise(ds, weights)
    return bool(np.allclose(w, ds.weights, atol=0.01))
