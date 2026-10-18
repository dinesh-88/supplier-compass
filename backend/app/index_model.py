"""Infer the Total Risk Index formula and the level bands from the data itself."""

from __future__ import annotations

import numpy as np
from scipy.optimize import nnls

DEFAULT_BANDS = [
    {"level": "Low", "min": 0, "max": 24},
    {"level": "Medium", "min": 25, "max": 49},
    {"level": "High", "min": 50, "max": 74},
    {"level": "Critical", "min": 75, "max": 100},
]
LEVEL_ORDER = ["Low", "Medium", "High", "Critical"]
VERIFIED_THRESHOLD = 0.99


def round_half_even_div100(total: np.ndarray) -> np.ndarray:
    """Exact integer division by 100 with banker's rounding (Python's round)."""
    total = total.astype(np.int64)
    q, r = np.divmod(total, 100)
    up = (r > 50) | ((r == 50) & (q % 2 == 1))
    return q + up.astype(np.int64)


def snap_to_percent(raw: np.ndarray) -> np.ndarray:
    """Whole-percent weights summing to exactly 100 (largest-remainder rounding)."""
    raw = np.clip(raw, 0, None)
    if raw.sum() <= 0:
        return np.full(len(raw), 100 // len(raw), dtype=np.int64)
    share = raw / raw.sum() * 100
    base = np.floor(share).astype(np.int64)
    remainder = 100 - int(base.sum())
    order = np.argsort(-(share - base), kind="stable")
    base[order[:remainder]] += 1
    return base


def index_from_weights(scores: np.ndarray, weights_pct: np.ndarray) -> np.ndarray:
    """Index as the dataset computes it: Σ(weight% × score) / 100, rounded half to even."""
    if np.all(np.equal(np.mod(scores, 1), 0)):
        return round_half_even_div100(scores.astype(np.int64) @ weights_pct.astype(np.int64))
    return np.round(scores @ weights_pct / 100.0)


def infer_formula(scores: np.ndarray, index: np.ndarray, names: list[str]) -> dict:
    """Fit NNLS without intercept, snap to whole percent, verify exactly."""
    raw, _ = nnls(scores.astype(float), index.astype(float))
    pred_raw = scores @ raw
    ss_res = float(((index - pred_raw) ** 2).sum())
    ss_tot = float(((index - index.mean()) ** 2).sum()) or 1.0
    r2_fit = 1 - ss_res / ss_tot

    weights = snap_to_percent(raw)
    recomputed = index_from_weights(scores, weights)
    matches = recomputed == index.astype(np.int64)
    match_share = float(matches.mean()) if len(matches) else 0.0
    pred = scores @ weights / 100.0
    r2 = 1 - float(((index - pred) ** 2).sum()) / ss_tot
    verified = match_share >= VERIFIED_THRESHOLD
    return {
        "weights": {n: int(w) for n, w in zip(names, weights)},
        "raw_weights": {n: round(float(w) * 100, 3) for n, w in zip(names, raw)},
        "match_share": round(match_share, 6),
        "rows_matched": int(matches.sum()),
        "rows_total": int(len(matches)),
        "r2": round(r2, 6),
        "r2_fit": round(r2_fit, 6),
        "status": "verified" if verified else "approximate",
        "label": "verified" if verified else f"approximate (R² = {r2:.3f})",
        "rounding": "round half to even",
    }


def infer_bands(pairs: list[tuple[np.ndarray, np.ndarray]]) -> tuple[list[dict], str]:
    """Min/max score per level label across all score/_Level column pairs."""
    lo: dict[str, float] = {}
    hi: dict[str, float] = {}
    for score, level in pairs:
        for lab in np.unique(level):
            if lab is None or str(lab).strip() == "":
                continue
            vals = score[level == lab]
            vals = vals[~np.isnan(vals)]
            if not len(vals):
                continue
            key = str(lab).strip()
            lo[key] = min(lo.get(key, np.inf), float(vals.min()))
            hi[key] = max(hi.get(key, -np.inf), float(vals.max()))
    if not lo:
        return DEFAULT_BANDS, "default"
    bands = sorted(
        ({"level": k, "min": int(lo[k]), "max": int(hi[k])} for k in lo), key=lambda b: b["min"]
    )
    return bands, "derived from _Level columns"


def level_of(value: float, bands: list[dict]) -> str:
    """Highest band whose minimum the value reaches (bands sorted by min)."""
    label = bands[0]["level"]
    for band in bands:
        if value >= band["min"]:
            label = band["level"]
    return label
