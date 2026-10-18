import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app

BACKEND = Path(__file__).resolve().parents[1]


def test_health():
    r = TestClient(app).get("/health")
    assert r.status_code == 200 and r.json() == {"ok": True}


def test_starts_with_no_settings_and_logs_no_secrets(monkeypatch):
    key, tavily = "llm-key-abcdef", "tvly-secret-123"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("LLM_", "TAVILY_"))}
    r = subprocess.run([sys.executable, "-c", "import app.main"], cwd=BACKEND, env={**env, "LLM_API_KEY": key,
                       "TAVILY_API_KEY": tavily}, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    monkeypatch.setenv("LLM_API_KEY", key)
    monkeypatch.setenv("TAVILY_API_KEY", tavily)
    line = Settings().summary()
    assert "llm=on" in line and "search=on" in line and "workspace=demo" in line
    assert all(s not in line + r.stdout + r.stderr for s in (key, tavily))
