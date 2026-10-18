from app import llm, memo
from app import weights as wmod

IDS = ["SUPP_00012", "SUPP_00450", "SUPP_00731", "SUPP_00018"]


def test_number_guard_removes_invented_numbers(ds):
    f = memo.build_facts(ds, IDS, None, "Official index", [])
    text = ("Prefer SUPP_00012 with index 60. SUPP_00012 is 99 times safer. "
            "Against SUPP_00450 the gap is 2 points. Over 42 suppliers were reviewed.")
    kept, removed = memo.check_numbers(text, f)
    assert "index 60" in kept and "gap is 2" in kept
    assert removed == ["SUPP_00012 is 99 times safer.", "Over 42 suppliers were reviewed."]


def test_llm_prose_is_number_checked(ds, monkeypatch):
    monkeypatch.setattr(llm, "is_mock", lambda: False)
    monkeypatch.setattr(llm, "chat", lambda *a, **k: {"content": "Prefer SUPP_00012 (index 60). It saves 1234 EUR.", "tool_calls": []})
    f = memo.build_facts(ds, IDS, None, "Official index", [])
    p = memo.write_prose(f, "")
    assert p["text"] == "Prefer SUPP_00012 (index 60)."
    assert p["removed"] == ["It saves 1234 EUR."]


def test_memo_endpoint_with_custom_weights(sample_client, ds):
    w = wmod.preset_weights(ds, "safety_critical")
    r = sample_client.post("/api/memo", json={"ids": IDS, "weights": w, "preset_label": "Safety-critical component",
                                              "rationale": "Brake pads are safety-critical."})
    assert r.status_code == 200, r.text
    md = r.json()["markdown"]
    for section in ("## Recommendation", "## Weights used and why", "## Ranked shortlist", "## Key differences", "## Risks to mitigate"):
        assert section in md
    assert "Safety-critical component" in md and "Brake pads are safety-critical." in md
    assert "| 1 | SUPP_00731 |" in md  # lowest custom index first
    assert "80 Critical" in md  # official index shown next to custom
    assert "Operational Resilience score 95 (Critical, +4.5" in md


def test_memo_attaches_research_and_exports_pdf(sample_client):
    with sample_client.stream("GET", "/api/research/stream", params={"company": "Memo Test Rail"}) as r:
        "".join(r.iter_text())
    rid = next(x["id"] for x in sample_client.get("/api/research").json() if x["company"] == "Memo Test Rail")
    md = sample_client.post("/api/memo", json={"ids": IDS[:2], "research_ids": [rid]}).json()["markdown"]
    assert "## Attached research reports" in md and "Memo Test Rail" in md
    pdf = sample_client.post("/api/memo/pdf", json={"markdown": md, "filename": "x"})
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")
