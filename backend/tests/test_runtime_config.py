import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

BACKEND = Path(__file__).resolve().parents[1]


def test_health_needs_no_login():
    r = TestClient(app).get("/health")
    assert r.status_code == 200 and r.json() == {"ok": True}


def _start(env: dict) -> subprocess.CompletedProcess:
    base = {k: v for k, v in os.environ.items() if k not in {"SESSION_SECRET", "APP_USERS", "LLM_API_KEY"}}
    return subprocess.run([sys.executable, "-c", "import app.main"], cwd=BACKEND, env={**base, **env},
                          capture_output=True, text=True, timeout=60)


def test_refuses_to_start_without_session_secret():
    r = _start({"APP_USERS": "jury:pw"})
    assert r.returncode != 0 and "SESSION_SECRET" in r.stderr


def test_refuses_to_start_without_users():
    r = _start({"SESSION_SECRET": "x" * 32})
    assert r.returncode != 0 and "APP_USERS" in r.stderr


def test_startup_log_has_no_secret_values():
    secret, password, key = "s3cr3t-session-value-123456", "hunter2-password", "llm-key-abcdef"
    r = _start({"SESSION_SECRET": secret, "APP_USERS": f"jury:{password}", "LLM_API_KEY": key})
    assert r.returncode == 0, r.stderr
    from app.config import Settings

    os.environ.update(SESSION_SECRET=secret, APP_USERS=f"jury:{password}", LLM_API_KEY=key)
    try:
        line = Settings().summary()
    finally:
        os.environ.update(SESSION_SECRET="test-session-secret-0123456789", APP_USERS="jury:jury-pass,other:other-pass",
                          LLM_API_KEY="")
    assert "users=jury" in line and "llm=on" in line
    assert all(s not in line + r.stdout + r.stderr for s in (secret, password, key))
