from fastapi.testclient import TestClient

from app.dataset import registry
from app.main import app

from .conftest import client_for


def test_no_login_everyone_is_demo():
    c = TestClient(app)
    assert c.get("/api/me").json()["user"] == "demo"
    assert c.post("/api/login", json={"username": "x", "password": "y"}).status_code in (404, 405)


def test_workspace_cannot_be_chosen_over_http():
    c = TestClient(app)
    c.cookies.set("sc_session", "eyJ1Ijoib3RoZXIifQ.forged.sig")
    assert c.get("/api/me", headers={"x-user": "other"}).json()["user"] == "demo"


def test_empty_workspace_gets_the_sample():
    c = client_for("fresh")
    try:
        meta = c.get("/api/dataset").json()
        assert meta["loaded"] and meta["row_count"] == 10_000 and "challenge sample" in meta["file_name"]
    finally:
        registry.clear("fresh")
