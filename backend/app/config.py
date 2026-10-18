"""Runtime settings, read once from the environment."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("DATA_DIR", ROOT / "var")))
    sample_dir: Path = field(default_factory=lambda: Path(os.environ.get("SAMPLE_DIR", ROOT / "data" / "sample")))
    sanctions_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("SANCTIONS_DIR", ROOT / "data" / "sanctions"))
    )
    static_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("STATIC_DIR", ROOT / "frontend" / "dist"))
    )
    app_users: str = field(default_factory=lambda: os.environ.get("APP_USERS", "jury:jury"))
    secret_key: str = field(default_factory=lambda: os.environ.get("SECRET_KEY") or secrets.token_hex(32))
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


settings = Settings()
