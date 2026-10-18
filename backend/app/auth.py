"""No login: every visitor works in the one shared `demo` workspace."""

from __future__ import annotations

from fastapi import Request

DEMO_USER = "demo"


def current_user(request: Request) -> str:
    # Set by the middleware in main.py. Tests may pre-set scope["state"]["user"] to get their own workspace;
    # nothing an HTTP client sends can change it.
    return getattr(request.state, "user", None) or DEMO_USER
