import numpy as np

from app import index_model

EXPECTED_WEIGHTS = {
    "operational_resilience_score": 10, "financial_health_score": 10, "quality_risk_score": 10,
    "compliance_risk_score": 8,
    "credit_rating_score": 6, "safety_incident_score": 6, "sub_tier_visibility_score": 6,
    "geopolitical_risk_score": 5, "governance_risk_score": 5, "esg_performance_score": 5,
    "labor_stability_score": 4, "environmental_exposure_score": 4, "digital_security_score": 4,
    "industry_benchmark_score": 4, "political_stability_score": 4,
    "market_sentiment_score": 3, "media_sentiment_score": 3, "external_intelligence_score": 3,
}


def test_sample_formula_is_verified_with_exact_weights(ds):
    f = ds.formula
    assert f["status"] == "verified"
    assert f["weights"] == EXPECTED_WEIGHTS
    assert sum(f["weights"].values()) == 100
    assert f["rows_matched"] == f["rows_total"] == 10_000


def test_index_reconstructed_for_every_row(ds):
    recomputed = index_model.index_from_weights(ds.scores, ds.weights)
    assert np.array_equal(recomputed, ds.index.astype(np.int64))


def test_half_up_rounding_would_fail_on_tie_rows(ds):
    total = ds.scores.astype(np.int64) @ ds.weights.astype(np.int64)
    ties = total % 100 == 50
    assert ties.sum() > 0
    half_up = (total + 50) // 100
    assert (half_up != ds.index).sum() == 47  # per DATA_PROFILE.md: half-up fails on 47 rows


def test_round_half_even_matches_python_round():
    totals = np.array([4950, 5050, 5150, 5049, 5051, 0, 10000])
    assert index_model.round_half_even_div100(totals).tolist() == [round(t / 100) for t in totals]


def test_level_bands_derived_from_data(ds):
    assert ds.bands == index_model.DEFAULT_BANDS
    assert ds.meta["band_source"] == "derived from _Level columns"


def test_level_bands_fall_back_without_level_columns():
    bands, source = index_model.infer_bands([])
    assert bands == index_model.DEFAULT_BANDS and source == "default"


def test_level_of_boundaries():
    b = index_model.DEFAULT_BANDS
    assert [index_model.level_of(v, b) for v in (0, 24, 25, 49, 50, 74, 75, 100)] == [
        "Low", "Low", "Medium", "Medium", "High", "High", "Critical", "Critical"]


def test_approximate_when_index_is_not_a_clean_weighted_sum():
    rng = np.random.default_rng(0)
    scores = rng.integers(0, 101, size=(2000, 4)).astype(float)
    index = np.round(scores @ np.array([0.4, 0.3, 0.2, 0.1]) + rng.normal(0, 4, 2000)).clip(0, 100)
    f = index_model.infer_formula(scores, index, ["a", "b", "c", "d"])
    assert f["status"] == "approximate"
    assert f["label"].startswith("approximate (R² = ")
    assert sum(f["weights"].values()) == 100


def test_snap_to_percent_sums_to_100():
    w = index_model.snap_to_percent(np.array([0.333, 0.333, 0.334]))
    assert w.sum() == 100 and set(w.tolist()) <= {33, 34}
