def test_explain_supp_00018(ds):
    e = ds.explain("SUPP_00018")
    assert e["total_risk_index"] == 80
    assert e["level"] == "Critical"
    assert round(e["percentile"]) == 98
    assert round(e["points_above_average_total"]) == 30
    assert not e["approximate"]
    top = [(d["column"], round(d["points_above_average"], 1)) for d in e["drivers"][:5]]
    assert top[:3] == [
        ("operational_resilience_score", 4.5),
        ("compliance_risk_score", 3.8),
        ("governance_risk_score", 2.4),
    ]
    assert dict(top)["quality_risk_score"] == 2.4
    assert dict(top)["safety_incident_score"] == 2.1
    # Contributions add up to the index before rounding.
    assert round(sum(c["contribution"] for c in e["contributions"])) == 80


def test_explain_endpoint(sample_client):
    r = sample_client.get("/api/suppliers/SUPP_00018")
    assert r.status_code == 200
    body = r.json()
    assert body["drivers"][0]["column"] == "operational_resilience_score"
    assert body["mismatch"]["label"] == "Delivery record doesn't match risk scores"


def test_exposure_list_and_mismatch(ds):
    assert int(ds.exposure_flag.sum()) == 44  # top 10 % spend and Critical, per DATA_PROFILE.md
    assert 0 < int(ds.mismatch.sum()) < ds.n * 0.1


def test_financial_ambiguity_in_compare(ds):
    from app.compare import field_comparison

    res = field_comparison(ds, ["SUPP_00012", "SUPP_00450", "SUPP_00731"], ["financial risk"])
    assert res["columns"] == ["financial_health_score", "credit_rating_score"]
    term = res["multi_column_terms"][0]
    assert term["columns_disagree"]
    assert term["best_per_column"]["financial_health_score"]["supplierID"] == "SUPP_00731"
    assert term["worst_per_column"]["credit_rating_score"]["supplierID"] == "SUPP_00731"
    assert term["combined"]["lowest"] == "SUPP_00012"
    assert [v["combined"] for v in term["combined"]["values"]] == [55.1, 61.6, 62.4]


def test_custom_weights_and_rank_change(sample_client, ds):
    presets = {p["key"]: p for p in sample_client.get("/api/presets").json()}
    assert set(presets) == {"official", "safety_critical", "long_term_partner", "commodity"}
    assert sum(presets["safety_critical"]["weights"].values()) == 100
    assert presets["safety_critical"]["weights"]["safety_incident_score"] > presets["official"]["weights"]["safety_incident_score"]
    r = sample_client.post("/api/custom-index", json={"weights": presets["safety_critical"]["weights"]}).json()
    assert not r["official"]
    assert len(r["custom_index"]) == ds.n
    assert any(x != 0 for x in r["rank_change"])
    off = sample_client.post("/api/custom-index", json={"weights": presets["official"]["weights"]}).json()
    assert off["official"] and all(x == 0 for x in off["rank_change"])
    # The official index is untouched.
    assert sample_client.get("/api/suppliers/SUPP_00018").json()["total_risk_index"] == 80


def test_why_a_over_b(sample_client):
    r = sample_client.post("/api/why", json={"a": "SUPP_00012", "b": "SUPP_00018"}).json()
    assert r["differences"]
    assert all(abs(d["difference"]) >= 10 for d in r["differences"])
    assert r["index_gap"] == r["index_b"] - r["index_a"]
