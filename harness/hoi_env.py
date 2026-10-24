"""Runs the real HOI platform API in-process (mongomock, no network) and drives traffic at it.

Nothing in HOI is modified. Faults are injected from outside (harness/faults.py) by swapping the dependencies HOI
already isolates: the MongoDB accessors, the LLM adapter (ai.use), the portal HTTP client (places.set_http) and settings.
All data is HOI's SYNTHETIC demo hotel.
"""

from __future__ import annotations

import json
import logging
import os
import random
import sys
import uuid
from pathlib import Path

HOI_PLATFORM = Path(os.getenv("HOI_PLATFORM_PATH", Path(__file__).resolve().parents[2] / "INNOV8" / "platform_api"))
sys.path.insert(0, str(HOI_PLATFORM))

os.environ.update(
    {
        "MONGODB_URI": "mongomock://",
        "HOI_PLATFORM_DB": f"hoi_oncall_{uuid.uuid4().hex[:8]}",
        "HOI_DEMO_LOGIN": "true",
        "HOI_ADMIN_PASSWORD": "admin-test-pw",
        "HOI_LOGIN_RATE_PER_MINUTE": "10",
        "HOI_ENV": "development",
    }
)
for k in ("GROQ_API_KEY", "LLM_API_KEY", "STT_API_KEY", "PORTAL_API_URL"):
    os.environ.pop(k, None)  # never reach real services from the harness

from fastapi.testclient import TestClient  # noqa: E402

from hoi_platform import config, ratelimit  # noqa: E402
from hoi_platform.services import ai, places  # noqa: E402

from copilot.logstore import LogStore  # noqa: E402

STAFF = ["demo.owner", "demo.hr", "demo.housekeeping", "demo.store"]
GUEST_MESSAGES = [
    "Can I get two extra towels please?",
    "What time is breakfast?",
    "The hot water is not working in the bathroom",
    "Is there wifi in the room?",
    "Kya mujhe ek aur kambal mil sakta hai?",
    "What are some nice places to visit nearby?",
    "Any offbeat quiet places near the hotel?",
    "Can I get late checkout tomorrow?",
]
STAFF_GETS = ["/auth/me", "/rooms", "/dispatch/jobs", "/inventory/items", "/inventory/stock", "/workspace", "/hotel/profile", "/guest-services/summary"]


class HealthyChat:
    """Stands in for the cloud LLM when it works: a short, valid, grounded reply (no numbers, no claims)."""

    name = "healthy-llm"

    def available(self):
        return True, "ok"

    def complete_json(self, system, messages):
        return json.dumps({"reply": "Thank you for asking. Please tell me if there is anything else you need.", "lang": "en", "action": None})


class _Resp:
    def __init__(self, status: int, body: dict):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


def healthy_portal(url, params, timeout=None):
    return _Resp(200, {"items": [], "results": [], "destinations": [], "experiences": [], "stays": []})


class HoiEnv:
    """One fresh HOI instance (own database) with a log store attached to its loggers."""

    def __init__(self, seed: int = 0):
        self.rng = random.Random(seed)
        self.store = LogStore()
        self._handler = self.store.handler()
        logging.getLogger().addHandler(self._handler)
        logging.getLogger().setLevel(logging.INFO)
        for noisy in ("httpx", "urllib3", "multipart"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
        os.environ["HOI_PLATFORM_DB"] = f"hoi_oncall_{uuid.uuid4().hex[:8]}"
        config.reload()
        ratelimit.reset()
        ai.use(chat=HealthyChat())
        places.set_http(healthy_portal)
        self.app = None
        self.client: TestClient | None = None
        self.tokens: dict[str, dict] = {}
        self.guest_tokens: list[str] = []

    # -- lifecycle
    def start(self) -> bool:
        """Boot HOI. A startup failure is logged the way a process supervisor would record it, and returns False."""
        from hoi_platform.main import create_app

        try:
            self.app = create_app()
        except Exception:
            logging.getLogger("supervisor").critical("startup failed: hoi-platform exited during boot", exc_info=True)
            return False
        self.client = TestClient(self.app, raise_server_exceptions=False)
        return True

    def warm_up(self) -> None:
        """Sign staff in and find occupied rooms, then forget those setup log lines (the incident window starts after)."""
        for u in STAFF:
            r = self.client.post(f"/auth/demo/{u}")
            if r.status_code == 200:
                self.tokens[u] = {"Authorization": f"Bearer {r.json()['token']}"}
        owner = self.tokens.get("demo.owner")
        if owner:
            rooms = self.client.get("/rooms", headers=owner).json().get("rooms", [])
            self.guest_tokens = [r["guest_token"] for r in rooms if r.get("status") == "occupied" and r.get("guest_token")][:6]
        ratelimit.reset()
        self.store.clear()

    def close(self) -> None:
        logging.getLogger().removeHandler(self._handler)
        ai.use()
        places.set_http(None)

    # -- traffic
    def health(self) -> dict:
        if self.client is None:
            raise ConnectionError("service not running")
        r = self.client.get("/ready")
        return {"ready": r.status_code == 200, "status_code": r.status_code}

    def normal_traffic(self, n: int = 50, noise: float = 0.05) -> None:
        """Staff browsing, guests chatting, readiness probes, plus a little everyday noise (typos at login, 404s)."""
        if self.client is None:
            return
        for i in range(n):
            x = self.rng.random()
            if i % 10 == 0:
                self.client.get("/ready")
            elif x < noise:
                if self.rng.random() < 0.5:
                    self.client.post("/auth/login", json={"username": "demo.owner", "password": "typo-" + str(i)})
                else:
                    self.client.get(f"/rooms/does-not-exist-{i}/qr.svg", headers=self.tokens.get("demo.owner", {}))
            elif x < 0.6 and self.tokens:
                u = self.rng.choice(list(self.tokens))
                self.client.get(self.rng.choice(STAFF_GETS), headers=self.tokens[u])
            elif self.guest_tokens:
                tok = self.rng.choice(self.guest_tokens)
                if self.rng.random() < 0.3:
                    self.client.get(f"/public/guest/{tok}")
                else:
                    self.client.post(f"/public/guest/{tok}/chat", json={"message": self.rng.choice(GUEST_MESSAGES), "history": []})

    def password_guessing(self, attempts: int, ip: str = "203.0.113.7") -> None:
        if self.client is None:
            return
        for i in range(attempts):
            user = self.rng.choice(["demo.owner", "admin", "platform", "demo.hr"])
            self.client.post("/auth/login", json={"username": user, "password": f"guess{i}"}, headers={"X-Forwarded-For": ip})
