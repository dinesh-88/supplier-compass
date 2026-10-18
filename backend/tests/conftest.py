import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="sc-test-")
os.environ.update(
    DATA_DIR=_TMP,
    APP_USERS="jury:jury-pass,other:other-pass",
    LLM_API_KEY="",
    TAVILY_API_KEY="",
    STATIC_DIR=str(Path(_TMP) / "no-static"),
    SANCTIONS_DIR=str(Path(__file__).parent / "fixtures" / "sanctions"),
    SESSION_SECRET="test-session-secret-0123456789",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.dataset import registry  # noqa: E402
from app.main import app  # noqa: E402

SAMPLE = settings.sample_dir / "supplier_risk_dataset.csv"


def login(client: TestClient, user="jury", password="jury-pass"):
    r = client.post("/api/login", json={"username": user, "password": password})
    assert r.status_code == 200, r.text
    return client


@pytest.fixture(scope="session")
def sample_client():
    """A logged-in client with the challenge sample loaded (shared, read-only use)."""
    client = login(TestClient(app))
    r = client.post("/api/dataset/sample", json={"replace": True})
    assert r.status_code == 200, r.text
    return client


@pytest.fixture(scope="session")
def ds(sample_client):
    return registry.get("jury")


@pytest.fixture
def other_client():
    return login(TestClient(app), "other", "other-pass")
