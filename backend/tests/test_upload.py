import io

from fastapi.testclient import TestClient

from app.main import app

from .conftest import login

HEADER = "supplierID,Supplier Name,Total_Risk_Index,Alpha_Score,Beta_Score,Comment\n"


def _csv(rows: list[str], header: str = HEADER) -> bytes:
    return (header + "\n".join(rows) + "\n").encode()


def _upload(client, data: bytes, md: bytes | None = None, replace=True):
    files = {"csv": ("test.csv", io.BytesIO(data), "text/csv")}
    if md is not None:
        files["descriptions_md"] = ("desc.md", io.BytesIO(md), "text/markdown")
    return client.post("/api/dataset/upload", files=files, data={"replace": str(replace).lower()})


def _client(user="other", pw="other-pass"):
    return login(TestClient(app), user, pw)


def test_validation_report_drops_bad_rows():
    c = _client()
    rows = [f"S{i},Name {i},{50 + i % 3},{40 + i % 7},{60 - i % 5},note" for i in range(40)]
    rows += [
        "S1,Duplicate,50,50,50,x",  # duplicate id
        ",No id,50,50,50,x",  # missing id
        "S900,Bad,50,abc,50,x",  # non-numeric score
        "S901,Range,50,150,50,x",  # out of range
        "S902,Missing,50,,50,x",  # missing score
    ]
    r = _upload(c, _csv(rows))
    assert r.status_code == 200, r.text
    rep = r.json()["meta"]["report"]
    assert rep["rows_loaded"] == 40
    assert rep["rows_dropped"] == 5
    reasons = {d["reason"]: d["count"] for d in rep["dropped"]}
    assert reasons["duplicate supplierID (first occurrence kept)"] == 1
    assert reasons["missing supplierID"] == 1
    assert reasons["Alpha_Score: not a number"] == 1
    assert reasons["Alpha_Score: outside 0–100"] == 1
    assert reasons["Alpha_Score: missing"] == 1
    assert rep["missing"]["Alpha_Score"] == 1
    assert rep["extra_columns"] == ["Comment"]
    # Optional columns missing → features off with a notice, but the upload is accepted.
    feats = r.json()["meta"]["features"]
    assert not feats["spend"]["enabled"] and not feats["mismatch"]["enabled"]
    assert any("Exposure" in n for n in rep["notices"])
    # No _Level columns → default bands.
    assert r.json()["meta"]["band_source"] == "default"
    # Approximate formula is labelled.
    assert r.json()["meta"]["formula"]["status"] in {"verified", "approximate"}
    c.delete("/api/dataset")


def test_missing_required_columns_rejected():
    c = _client()
    r = _upload(c, _csv(["S1,x,50"], header="supplierID,Name,Other\n"))
    assert r.status_code == 422
    assert "Total_Risk_Index" in r.json()["error"]
    assert c.get("/api/dataset").json() == {"loaded": False}


def test_replace_requires_confirmation_and_users_are_isolated(sample_client):
    c = _client()
    rows = [f"S{i},N,{50},{50},{50},x" for i in range(5)]
    assert _upload(c, _csv(rows)).status_code == 200
    r = _upload(c, _csv(rows), replace=False)
    assert r.status_code == 409
    # The jury user's sample is untouched by the other user's upload.
    assert sample_client.get("/api/dataset").json()["row_count"] == 10_000
    assert c.get("/api/dataset").json()["row_count"] == 5
    assert c.get("/api/suppliers/SUPP_00018").status_code == 404
    c.delete("/api/dataset")


def test_markdown_upload_and_fallback():
    c = _client()
    rows = [f"S{i},N,{50},{50},{50},x" for i in range(5)]
    md = b"# D\n- **Alpha_Score:** Alpha <script>alert(1)</script> risk.\n"
    meta = _upload(c, _csv(rows), md=md).json()["meta"]
    assert meta["descriptions"]["source"] == "uploaded file desc.md"
    text = c.get("/api/dataset/descriptions").json()["text"]
    assert "<script>" in text  # stored verbatim; the UI renders it as text, never HTML
    meta = _upload(c, _csv(rows)).json()["meta"]
    assert meta["descriptions"]["builtin"] is True
    c.delete("/api/dataset")


def test_upload_size_limit(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "max_upload_bytes", 100)
    c = _client()
    r = _upload(c, _csv([f"S{i},N,50,50,50,x" for i in range(20)]))
    assert r.status_code == 413
