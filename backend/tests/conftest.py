import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="sc-test-")
os.environ.update(
    DATA_DIR=_TMP,
    LLM_API_KEY="",
    TAVILY_API_KEY="",
    STATIC_DIR=str(Path(_TMP) / "no-static"),
    SANCTIONS_DIR=str(Path(__file__).parent / "fixtures" / "sanctions"),
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.dataset import registry  # noqa: E402
from app.main import app  # noqa: E402

SAMPLE = settings.sample_dir / "supplier_risk_dataset.csv"


def client_for(user: str = "demo") -> TestClient:
    """A client working in `user`'s workspace. The app has no login (everyone is `demo`); tests set the
    workspace in the ASGI scope, which an HTTP request cannot do."""
    if user == "demo":
        return TestClient(app)

    async def as_user(scope, receive, send):
        if scope["type"] == "http":
            scope = {**scope, "state": {**scope.get("state", {}), "user": user}}
        await app(scope, receive, send)

    return TestClient(as_user)


@pytest.fixture(scope="session")
def sample_client():
    """A logged-in client with the challenge sample loaded (shared, read-only use)."""
    client = client_for()
    r = client.post("/api/dataset/sample", json={"replace": True})
    assert r.status_code == 200, r.text
    return client


@pytest.fixture(scope="session")
def ds(sample_client):
    return registry.get("demo")


@pytest.fixture
def other_client():
    return client_for("other")
