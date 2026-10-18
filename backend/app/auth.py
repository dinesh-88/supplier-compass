"""Login for the jury: users from APP_USERS, hashed at startup, signed HTTP-only session cookie."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets

from fastapi import HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import settings

COOKIE_NAME = "sc_session"
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)


class UserStore:
    def __init__(self, spec: str):
        self._users: dict[str, tuple[bytes, bytes]] = {}
        for item in spec.split(","):
            item = item.strip()
            if not item:
                continue
            name, sep, password = item.partition(":")
            name = name.strip()
            if not sep or not password or not USERNAME_RE.match(name):
                raise ValueError(f"APP_USERS entry for {name!r} is malformed; use name:password")
            salt = secrets.token_bytes(16)
            self._users[name] = (salt, _hash(password, salt))
        # The plain-text spec is not kept.

    def verify(self, name: str, password: str) -> bool:
        record = self._users.get(name)
        if record is None:
            _hash(password, b"0" * 16)  # same work either way
            return False
        salt, digest = record
        return hmac.compare_digest(digest, _hash(password, salt))

    @property
    def names(self) -> list[str]:
        return list(self._users)


users = UserStore(settings.app_users)
_serializer = URLSafeTimedSerializer(settings.secret_key, salt="supplier-compass-session")


def make_session(user: str) -> str:
    return _serializer.dumps({"u": user, "n": secrets.token_hex(8)})


def read_session(token: str | None) -> str | None:
    if not token:
        return None
    try:
        data = _serializer.loads(token, max_age=settings.session_max_age)
    except (BadSignature, SignatureExpired):
        return None
    user = data.get("u") if isinstance(data, dict) else None
    return user if user in users.names else None


def current_user(request: Request) -> str:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not logged in")
    return user
