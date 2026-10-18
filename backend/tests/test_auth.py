import re

from fastapi.testclient import TestClient
from starlette.routing import Route

from app.main import app


def _api_routes():
    for route in app.routes:
        if isinstance(route, Route) and route.path.startswith("/api"):
            for method in route.methods - {"HEAD", "OPTIONS"}:
                yield method, re.sub(r"\{[^}]+\}", "SUPP_00001", route.path)


def test_every_api_route_requires_a_session():
    client = TestClient(app)
    routes = list(_api_routes())
    assert len(routes) > 10
    for method, path in routes:
        if path == "/api/login":
            continue
        r = client.request(method, path)
        assert r.status_code == 401, f"{method} {path} returned {r.status_code}"


def test_forged_cookie_is_rejected():
    client = TestClient(app)
    client.cookies.set("sc_session", "eyJ1IjoianVyeSJ9.forged.sig")
    assert client.get("/api/me").status_code == 401


def test_wrong_password():
    client = TestClient(app)
    assert client.post("/api/login", json={"username": "jury", "password": "nope"}).status_code == 401
    assert client.post("/api/login", json={"username": "ghost", "password": "nope"}).status_code == 401


def test_login_sets_http_only_cookie():
    client = TestClient(app)
    r = client.post("/api/login", json={"username": "jury", "password": "jury-pass"})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert client.get("/api/me").json()["user"] == "jury"
