"""Fault injectors for HOI. Each fault swaps one dependency HOI already isolates; every change is undone afterwards.

`label` is the ground-truth runbook id: the eval checks whether the copilot names it.
"""

from __future__ import annotations

import os
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass

from .hoi_env import HoiEnv, healthy_portal  # first: puts HOI's platform_api on sys.path  # isort: skip

from hoi_platform import config, mongo  # noqa: E402
from hoi_platform.services import ai, places  # noqa: E402
from pymongo.errors import ServerSelectionTimeoutError  # noqa: E402


class Patcher:
    """Minimal monkeypatch with undo (so one scenario cannot leak into the next)."""

    def __init__(self):
        self._undo: list[Callable[[], None]] = []

    def setattr(self, obj, name: str, value) -> None:
        old = getattr(obj, name)
        setattr(obj, name, value)
        self._undo.append(lambda: setattr(obj, name, old))

    def setenv(self, key: str, value: str | None) -> None:
        old = os.environ.get(key)
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
        self._undo.append(lambda: os.environ.__setitem__(key, old) if old is not None else os.environ.pop(key, None))

    def undo(self) -> None:
        while self._undo:
            self._undo.pop()()
        config.reload()
        ai.use()
        places.set_http(None)


@dataclass
class Fault:
    name: str
    label: str  # runbook id that describes the true root cause
    phase: str  # "pre_start" (before boot) or "runtime" (after normal traffic has started)
    apply: Callable[[HoiEnv, Patcher, dict], None]


# ---------------------------------------------------------------- database
def _db_down(env: HoiEnv, p: Patcher, kw: dict) -> None:
    host = kw.get("host", "hoi-cluster-shard-00-01.example.mongodb.net:27017")

    def boom(*_a, **_k):
        raise ServerSelectionTimeoutError(f"{host}: timed out (configured timeouts: socketTimeoutMS: 20000.0ms, connectTimeoutMS: 20000.0ms)")

    for fn in ("col", "find", "find_one", "ping", "db", "next_id"):
        p.setattr(mongo, fn, boom)


class _SlowCollection:
    def __init__(self, inner, delay_s: float):
        self._inner, self._delay = inner, delay_s

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if not callable(attr):
            return attr

        def slow(*a, **k):
            time.sleep(self._delay)
            return attr(*a, **k)

        return slow


def _db_slow(env: HoiEnv, p: Patcher, kw: dict) -> None:
    delay = kw.get("delay_ms", 150) / 1000
    real_col = mongo.col
    p.setattr(mongo, "col", lambda name: _SlowCollection(real_col(name), delay))


# ---------------------------------------------------------------- LLM provider
class _Chat429:
    name = "groq"

    def available(self):
        return True, "ok"

    def complete_json(self, system, messages):
        raise ai.AiUnavailable("HTTP 429")


class _ChatDrifted:
    """Provider/model change: replies are prose or a different JSON shape, not the schema HOI validates."""

    name = "groq"

    def __init__(self, style: str):
        self.style = style

    def available(self):
        return True, "ok"

    def complete_json(self, system, messages):
        if self.style == "prose":
            return "Sure! I can help with that. Let me know what you need."
        return '{"message": "Sure, I can help", "language": "en"}'


def _llm_rate_limited(env: HoiEnv, p: Patcher, kw: dict) -> None:
    ai.use(chat=_Chat429())


def _llm_key_missing(env: HoiEnv, p: Patcher, kw: dict) -> None:
    for k in ("GROQ_API_KEY", "LLM_API_KEY"):
        p.setenv(k, None)
    ai.use()  # the real adapter: with no key it reports "set LLM_API_KEY or GROQ_API_KEY"


def _llm_schema_drift(env: HoiEnv, p: Patcher, kw: dict) -> None:
    ai.use(chat=_ChatDrifted(kw.get("style", "prose")))


# ---------------------------------------------------------------- auth
def _jwt_secret_rotated(env: HoiEnv, p: Patcher, kw: dict) -> None:
    # a redeploy came up with a different signing secret: every token issued before it no longer verifies
    p.setenv("HOI_JWT_SECRET", secrets.token_urlsafe(48))
    config.reload()


def _password_guessing(env: HoiEnv, p: Patcher, kw: dict) -> None:
    env.password_guessing(kw.get("attempts", 25))


def _rate_limit_misconfigured(env: HoiEnv, p: Patcher, kw: dict) -> None:
    # a config change set the guest chat limit far too low; every guest behind the same proxy IP shares the per-IP bucket
    p.setenv("HOI_GUEST_CHAT_RATE_PER_MINUTE", str(kw.get("per_minute", 2)))
    config.reload()


# ---------------------------------------------------------------- dependency
def _portal_down(env: HoiEnv, p: Patcher, kw: dict) -> None:
    mode = kw.get("mode", "timeout")

    def down(url, params, timeout=None):
        if mode == "timeout":
            raise TimeoutError("timed out")
        if mode == "refused":
            raise ConnectionRefusedError("connection refused")
        from .hoi_env import _Resp

        return _Resp(503, {"detail": "service unavailable"})

    places.set_http(down)


# ---------------------------------------------------------------- deploy
def _unsafe_prod_config(env: HoiEnv, p: Patcher, kw: dict) -> None:
    # deployed with HOI_ENV=production but without the production secrets: HOI refuses to boot (by design)
    p.setenv("HOI_ENV", "production")
    p.setenv("HOI_JWT_SECRET", None)
    p.setenv("HOI_DEMO_LOGIN", "false")
    config.reload()


FAULTS = {
    f.name: f
    for f in [
        Fault("db_down", "RB01", "runtime", _db_down),
        Fault("db_slow", "RB02", "runtime", _db_slow),
        Fault("llm_rate_limited", "RB03", "runtime", _llm_rate_limited),
        Fault("llm_key_missing", "RB04", "runtime", _llm_key_missing),
        Fault("llm_schema_drift", "RB05", "runtime", _llm_schema_drift),
        Fault("jwt_secret_rotated", "RB06", "runtime", _jwt_secret_rotated),
        Fault("password_guessing", "RB07", "runtime", _password_guessing),
        Fault("unsafe_prod_config", "RB09", "pre_start", _unsafe_prod_config),
        Fault("rate_limit_misconfigured", "RB10", "runtime", _rate_limit_misconfigured),
        # HOI degrades gracefully here (own place cards + cache): no user impact, so the right answer is "no incident"
        Fault("portal_down", "NONE", "runtime", _portal_down),
    ]
}


def run_scenario(
    fault: str | None,
    seed: int,
    kw: dict | None = None,
    before: int = 20,
    after: int = 40,
    noise: float = 0.05,
    investigate: Callable[[HoiEnv], object] | None = None,
) -> tuple[HoiEnv, object]:
    """Boot HOI, send normal traffic, inject the fault, keep the traffic going, then investigate WHILE the fault is
    still active (health probes see the broken system, as on a real on-call). Returns (env, investigation result)."""
    kw = kw or {}
    env = HoiEnv(seed=seed)
    p = Patcher()
    f = FAULTS.get(fault) if fault else None
    result = None
    try:
        if f and f.phase == "pre_start":
            f.apply(env, p, kw)
        if env.start():
            env.warm_up()
            env.normal_traffic(before, noise)
            if f and f.phase == "runtime":
                f.apply(env, p, kw)
            env.normal_traffic(after, noise)
        if investigate:
            result = investigate(env)
    finally:
        p.undo()
        places.set_http(healthy_portal)
        env.close()
    return env, result
