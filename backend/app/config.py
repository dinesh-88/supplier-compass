"""Runtime settings, read once from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("DATA_DIR") or "/tmp/data"))
    sample_dir: Path = field(default_factory=lambda: Path(os.environ.get("SAMPLE_DIR", ROOT / "data" / "sample")))
    sanctions_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("SANCTIONS_DIR", ROOT / "data" / "sanctions"))
    )
    static_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("STATIC_DIR", ROOT / "frontend" / "dist"))
    )
    app_users: str = field(default_factory=lambda: os.environ.get("APP_USERS", ""))
    session_secret: str = field(default_factory=lambda: os.environ.get("SESSION_SECRET", "").strip())
    cookie_secure: bool = field(default_factory=lambda: _flag("COOKIE_SECURE"))
    session_max_age: int = 60 * 60 * 12

    llm_base_url: str = field(
        default_factory=lambda: os.environ.get("LLM_BASE_URL", "https://api.tokenfactory.nebius.com/v1/")
    )
    llm_api_key: str = field(default_factory=lambda: os.environ.get("LLM_API_KEY", ""))
    llm_model: str = field(
        default_factory=lambda: os.environ.get("LLM_MODEL", "nvidia/nemotron-3-super-120b-a12b")
    )
    llm_fast_model: str = field(default_factory=lambda: os.environ.get("LLM_FAST_MODEL", ""))
    # Reasoning models (e.g. Nemotron 3) spend completion tokens on reasoning before the answer.
    llm_reasoning_tokens: int = field(default_factory=lambda: int(os.environ.get("LLM_REASONING_TOKENS", "3000")))
    tavily_api_key: str = field(default_factory=lambda: os.environ.get("TAVILY_API_KEY", ""))

    max_upload_bytes: int = 50 * 1024 * 1024
    load_timeout_s: float = 10.0
    sql_timeout_s: float = 2.0
    sql_row_limit: int = 200
    research_search_budget: int = 25

    @property
    def fast_model(self) -> str:
        return self.llm_fast_model or self.llm_model


    def problems(self) -> list[str]:
        """Settings the app cannot start without. Names only, never values."""
        out = []
        if len(self.session_secret) < 16:
            out.append("SESSION_SECRET is missing or shorter than 16 characters "
                       "(generate one with: python -c \"import secrets; print(secrets.token_hex(32))\")")
        if not self.app_users.strip():
            out.append("APP_USERS is empty")
        return out

    def summary(self) -> str:
        """One startup log line: which features are configured, without any secret values."""
        users = [u.split(":", 1)[0].strip() for u in self.app_users.split(",") if u.strip()]
        return (f"data_dir={self.data_dir} users={','.join(users)} llm={'on' if self.llm_api_key else 'off'} "
                f"model={self.llm_model} search={'on' if self.tavily_api_key else 'off'} "
                f"cookie_secure={self.cookie_secure}")


settings = Settings()
if _problems := settings.problems():
    raise SystemExit("Supplier Compass cannot start: " + "; ".join(_problems))
