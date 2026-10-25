"""Passwords (bcrypt), sessions (JWT), roles, alert-ingestion key, and a small login throttle."""

from __future__ import annotations

import hmac
import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .config import settings
from .db import get_session
from .models import User

ALGO = "HS256"


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode()[:72], bcrypt.gensalt(rounds=12)).decode()


def check_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode()[:72], hashed.encode())
    except ValueError:
        return False


# a real hash, so a login for an unknown user costs the same time as one with a wrong password
_DUMMY_HASH = bcrypt.hashpw(b"timing-equaliser", bcrypt.gensalt(rounds=12)).decode()


def issue_token(user: User) -> str:
    exp = datetime.now(UTC) + timedelta(minutes=settings.jwt_minutes)
    return jwt.encode({"sub": str(user.id), "role": user.role, "exp": exp}, settings.jwt_secret, algorithm=ALGO)


class LoginThrottle:
    """At most `limit` failed logins per username per `window` seconds (in-process; one instance is enough here)."""

    def __init__(self, limit: int = 5, window: float = 60.0):
        self.limit, self.window = limit, window
        self._fails: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def blocked(self, key: str) -> bool:
        with self._lock:
            q = self._fails[key]
            while q and q[0] < time.monotonic() - self.window:
                q.popleft()
            return len(q) >= self.limit

    def fail(self, key: str) -> None:
        with self._lock:
            self._fails[key].append(time.monotonic())

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._fails.clear()
            else:
                self._fails.pop(key, None)


throttle = LoginThrottle()


def authenticate(s: Session, username: str, password: str) -> User:
    key = username.lower()
    if throttle.blocked(key):
        raise HTTPException(429, "too many failed logins for this user; try again in a minute")
    user = s.query(User).filter(User.username == key).one_or_none()
    ok = check_password(password, user.password_hash if user else _DUMMY_HASH)
    if not (user and ok and user.active):
        throttle.fail(key)
        raise HTTPException(401, "wrong username or password")
    throttle.reset(key)
    return user


def current_user(authorization: str | None = Header(default=None), s: Session = Depends(get_session)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "sign in first", headers={"WWW-Authenticate": "Bearer"})
    try:
        claims = jwt.decode(authorization[7:], settings.jwt_secret, algorithms=[ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "session expired; sign in again") from None
    except jwt.PyJWTError:
        raise HTTPException(401, "invalid session") from None
    user = s.get(User, int(claims["sub"]))
    if user is None or not user.active:
        raise HTTPException(401, "invalid session")
    return user


def require_lead(user: User = Depends(current_user)) -> User:
    if user.role != "lead":
        raise HTTPException(403, "only an on-call lead can do this")
    return user


def alert_source(
    x_alert_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    s: Session = Depends(get_session),
) -> str:
    """Monitoring systems send X-Alert-Key; a signed-in engineer may also post an alert by hand."""
    if x_alert_key is not None:
        if settings.alert_ingest_key and hmac.compare_digest(x_alert_key, settings.alert_ingest_key):
            return "monitoring"
        raise HTTPException(401, "invalid alert key")
    user = current_user(authorization, s)
    return user.username
