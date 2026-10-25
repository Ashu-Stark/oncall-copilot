"""Fault simulator: boots the real HOI platform API in-process, injects one of the eval's faults, captures the log
window and a readiness probe, runs the alert rules, and files whatever fires as an alert.

If no rule fires (a weak fault, or a fault with no user impact) no incident is opened, exactly as in production.
The harness changes process-wide state (environment variables, the root logger), so only one simulation runs at a time.
"""

from __future__ import annotations

import threading
import uuid

from fastapi import HTTPException

from .config import settings

SEVERITY = {
    "ServiceDown": "SEV1",
    "HighErrorRate": "SEV1",
    "ReadinessFailing": "SEV1",
    "AuthFailureSpike": "SEV2",
    "HighLatency": "SEV2",
    "RateLimitSpike": "SEV2",
    "AiFallbackSpike": "SEV3",
    "DependencyErrors": "SEV3",
}
DESCRIPTIONS = {
    "db_down": "MongoDB becomes unreachable",
    "db_slow": "Every database call gets slower",
    "llm_rate_limited": "The LLM provider answers 429",
    "llm_key_missing": "The LLM API key disappears from the environment",
    "llm_schema_drift": "The model starts replying in a different format",
    "jwt_secret_rotated": "A redeploy changes the JWT signing secret",
    "password_guessing": "Someone guesses passwords on /auth/login",
    "unsafe_prod_config": "Deployed as production without production secrets",
    "rate_limit_misconfigured": "Guest chat rate limit set far too low",
    "portal_down": "Tourism portal down (HOI degrades gracefully: should NOT page)",
    "healthy": "Normal traffic, no fault (should NOT page)",
}
_lock = threading.Lock()


def available() -> bool:
    if not settings.simulator_enabled:
        return False
    try:
        from harness import hoi_env  # noqa: F401  (imports HOI's platform_api)
    except Exception:  # noqa: BLE001 - HOI not installed next to this repo
        return False
    return True


def faults() -> list[dict]:
    from harness.faults import FAULTS

    out = [{"name": f.name, "description": DESCRIPTIONS.get(f.name, ""), "expected": f.label} for f in FAULTS.values()]
    return out + [{"name": "healthy", "description": DESCRIPTIONS["healthy"], "expected": "NONE"}]


def run(fault: str, seed: int, intensity: dict) -> dict:
    """Returns {"alerts": [...], "logs": [...], "health": {...}, "expected": "RBnn" | "NONE"}."""
    if not available():
        raise HTTPException(503, "the fault simulator needs the HOI platform code next to this repo (see README)")
    from copilot.alerts import evaluate
    from copilot.tools import Tools
    from harness.faults import FAULTS, run_scenario

    if fault != "healthy" and fault not in FAULTS:
        raise HTTPException(422, f"unknown fault '{fault}'")
    if not _lock.acquire(timeout=60):
        raise HTTPException(409, "another simulation is running; try again shortly")
    try:

        def capture(env):
            t = Tools(env.store)
            alerts = evaluate(t)
            rows = env.store.rows("1=1", limit=1_000_000)
            logs = [{"ts": r.ts, "level": r.level, "logger": r.logger, "message": r.message, "exc": r.exc} for r in rows]
            try:  # after copying the logs, so the probe's own access line is not part of the window
                health = env.health()
            except Exception as e:  # noqa: BLE001 - service not running is a finding
                health = {"error": type(e).__name__}
            return alerts, logs, health

        _, (alerts, logs, health) = run_scenario(None if fault == "healthy" else fault, seed, intensity, investigate=capture)
    finally:
        _lock.release()
    expected = "NONE" if fault == "healthy" else FAULTS[fault].label
    return {
        "alerts": [{"name": a.name, "summary": a.summary} for a in alerts],
        "logs": logs,
        "health": health,
        "expected": expected,
        "run_id": uuid.uuid4().hex[:12],
    }


def severity(alert_names: list[str]) -> str:
    return min((SEVERITY.get(n, "SEV3") for n in alert_names), default="SEV3")


