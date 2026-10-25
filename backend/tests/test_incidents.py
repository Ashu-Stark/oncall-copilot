"""Auth, alert deduplication, the incident workflow, MTTA/MTTR, investigations and the SSE stream."""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from conftest import INGEST, db_outage_logs

from backend.app.incidents import mtta_mttr


def alert(client, name="HighErrorRate", fingerprint=None, logs=None, health=None, **kw):
    body = {"service": "hoi-platform", "name": name, "summary": "15% of requests returned 5xx", "severity": "SEV1", **kw}
    if fingerprint:
        body["fingerprint"] = fingerprint
    if logs is not None:
        body["logs"] = logs
    if health is not None:
        body["health"] = health
    return client.post("/api/alerts", json=body, headers=INGEST)


# ---------------------------------------------------------------- auth
def test_login_rejects_bad_password_and_throttles(client):
    for _ in range(5):
        assert client.post("/api/auth/login", json={"username": "engineer.demo", "password": "nope"}).status_code == 401
    r = client.post("/api/auth/login", json={"username": "engineer.demo", "password": "test-password-123"})
    assert r.status_code == 429  # locked for a minute even with the right password


def test_every_route_needs_a_session(client):
    for path in ("/api/incidents", "/api/runbooks", "/api/dashboard", "/api/simulator"):
        assert client.get(path).status_code == 401
    assert client.get("/api/incidents", headers={"Authorization": "Bearer not-a-jwt"}).status_code == 401


def test_alert_ingestion_needs_the_right_key(client):
    r = client.post("/api/alerts", json={"service": "hoi-platform", "name": "X1", "summary": "s"}, headers={"X-Alert-Key": "wrong"})
    assert r.status_code == 401


def test_unknown_service_is_rejected(client):
    r = client.post("/api/alerts", json={"service": "nope", "name": "HighErrorRate", "summary": "s"}, headers=INGEST)
    assert r.status_code == 422


# ---------------------------------------------------------------- dedup
def test_same_alert_twice_is_one_incident_until_resolved(client, eng):
    a = alert(client).json()
    b = alert(client).json()
    assert a["created"] and not b["created"] and b["deduplicated"]
    assert a["incident_id"] == b["incident_id"]
    inc = client.get(f"/api/incidents/{a['incident_id']}", headers=eng).json()
    assert inc["alert_count"] == 2
    kinds = [e["kind"] for e in client.get(f"/api/incidents/{a['incident_id']}/timeline", headers=eng).json()]
    assert kinds == ["alert", "alert_repeated"]

    client.patch(f"/api/incidents/{a['incident_id']}/status", json={"status": "resolved", "resolution": "false alarm"}, headers=eng)
    c = alert(client).json()
    assert c["created"] and c["incident_id"] != a["incident_id"]


def test_parallel_identical_alerts_open_exactly_one_incident(client, eng):
    results, barrier = [], threading.Barrier(8)

    def fire():
        barrier.wait()
        results.append(alert(client, fingerprint="race-test-fp").json())

    threads = [threading.Thread(target=fire) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(r["created"] for r in results) == 1
    assert len({r["incident_id"] for r in results}) == 1
    inc = client.get(f"/api/incidents/{results[0]['incident_id']}", headers=eng).json()
    assert inc["alert_count"] == 8


# ---------------------------------------------------------------- workflow
def test_status_workflow_rejects_skips_and_reopening(client, eng):
    iid = alert(client).json()["incident_id"]
    url = f"/api/incidents/{iid}/status"
    assert client.patch(url, json={"status": "investigating"}, headers=eng).status_code == 409  # must acknowledge first
    r = client.patch(url, json={"status": "acknowledged"}, headers=eng)
    assert r.status_code == 200 and r.json()["acknowledged_at"]
    assert client.patch(url, json={"status": "investigating"}, headers=eng).status_code == 200
    assert client.patch(url, json={"status": "resolved"}, headers=eng).status_code == 422  # needs a resolution
    r = client.patch(url, json={"status": "resolved", "resolution": "restarted the pod"}, headers=eng)
    assert r.status_code == 200 and r.json()["resolved_at"]
    assert client.patch(url, json={"status": "acknowledged"}, headers=eng).status_code == 409  # resolved is final


def test_notes_and_assignment_land_on_the_timeline(client, eng):
    iid = alert(client).json()["incident_id"]
    users = client.get("/api/users", headers=eng).json()
    ravi = next(u for u in users if u["username"] == "engineer.demo")
    assert client.patch(f"/api/incidents/{iid}/assignee", json={"user_id": ravi["id"]}, headers=eng).json()["assignee"]["id"] == ravi["id"]
    client.post(f"/api/incidents/{iid}/notes", json={"text": "looking at Atlas"}, headers=eng)
    tl = client.get(f"/api/incidents/{iid}/timeline", headers=eng).json()
    assert [e["kind"] for e in tl] == ["alert", "assigned", "note"]
    assert tl[-1]["actor"] == "engineer.demo"


def test_mtta_mttr_are_computed_from_timestamps():
    t = datetime(2026, 1, 1, tzinfo=UTC)
    incs = [
        SimpleNamespace(created_at=t, acknowledged_at=t + timedelta(minutes=4), resolved_at=t + timedelta(minutes=30)),
        SimpleNamespace(created_at=t, acknowledged_at=t + timedelta(minutes=10), resolved_at=t + timedelta(minutes=90)),
        SimpleNamespace(created_at=t, acknowledged_at=None, resolved_at=None),  # still open: not counted
    ]
    m = mtta_mttr(incs)
    assert m["mtta_minutes"] == {"n": 2, "mean": 7.0, "median": 7.0}
    assert m["mttr_minutes"] == {"n": 2, "mean": 60.0, "median": 60.0}


def test_dashboard_counts_open_incidents_by_severity(client, eng):
    alert(client, name="HighErrorRate")
    alert(client, name="HighLatency", severity="SEV2")
    d = client.get("/api/dashboard", headers=eng).json()
    assert d["open_total"] == 2 and d["open_by_severity"] == {"SEV1": 1, "SEV2": 1}
    assert d["eval"]["scenarios"] == 55  # the offline evaluation's own numbers


# ---------------------------------------------------------------- investigations
def test_alert_with_logs_is_investigated_and_every_step_is_stored(client, eng):
    r = alert(client, name="HighErrorRate", logs=db_outage_logs(), health={"ready": False, "status_code": 503}).json()
    assert r["investigation_id"]
    inv = client.get(f"/api/investigations/{r['investigation_id']}", headers=eng).json()
    assert inv["status"] == "done" and inv["label"] == "RB01"
    kinds = [s["kind"] for s in inv["steps"]]
    assert kinds[:3] == ["alerts", "query", "retrieval"] and kinds[-1] == "verdict" and "check" in kinds
    # every cited log id is a real line of this incident
    ids = inv["diagnosis"]["evidence_ids"]
    lines = client.get(f"/api/incidents/{r['incident_id']}/logs", params={"ids": ",".join(map(str, ids))}, headers=eng).json()
    assert ids and [x["seq"] for x in lines] == ids
    # the confirmed check carries its evidence lines for the UI
    confirmed = next(s for s in inv["steps"] if s["kind"] == "check" and s["data"]["confirmed"])
    assert all(c["evidence_lines"] or not c["evidence"] for c in confirmed["data"]["results"])
    inc = client.get(f"/api/incidents/{r['incident_id']}", headers=eng).json()
    assert inc["verdict"]["label"] == "RB01"


def test_unexplained_errors_end_in_abstention_not_a_guess(client, eng):
    logs = [{"level": "INFO", "logger": "hoi.platform", "message": f"rid=r{i} GET /rooms -> 500 4ms"} for i in range(8)]
    r = alert(client, logs=logs, health={"ready": True}).json()
    inv = client.get(f"/api/investigations/{r['investigation_id']}", headers=eng).json()
    assert inv["label"] == "UNKNOWN"
    assert inv["steps"][-1]["title"].startswith("Abstained")


def test_investigation_without_logs_is_refused(client, eng):
    iid = alert(client).json()["incident_id"]
    assert client.post(f"/api/incidents/{iid}/investigations", headers=eng).status_code == 409


def test_sse_stream_sends_each_step_then_done_and_resumes(client, eng):
    r = alert(client, logs=db_outage_logs(), health={"ready": False}).json()
    url = f"/api/investigations/{r['investigation_id']}/stream"
    with client.stream("GET", url, headers=eng) as resp:
        assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/event-stream")
        body = "".join(resp.iter_text())
    steps = body.count("event: step")
    assert steps >= 5 and body.rstrip().endswith('data: {"status": "done"}')
    with client.stream("GET", url, headers={**eng, "Last-Event-ID": "3"}) as resp:
        resumed = "".join(resp.iter_text())
    assert resumed.count("event: step") == steps - 3 and "id: 3\n" not in resumed


def test_postmortem_draft_has_root_cause_timeline_and_actions(client, eng):
    r = alert(client, logs=db_outage_logs(), health={"ready": False}).json()
    iid = r["incident_id"]
    client.patch(f"/api/incidents/{iid}/status", json={"status": "acknowledged"}, headers=eng)
    client.patch(f"/api/incidents/{iid}/status", json={"status": "resolved", "resolution": "added egress IP to the Atlas access list"}, headers=eng)
    md = client.get(f"/api/incidents/{iid}/postmortem", headers=eng).json()["markdown"]
    for part in ("## Root cause", "RB01", "## Timeline", "acknowledged → resolved", "added egress IP", "## Action items", "- [ ]"):
        assert part in md, part


def test_requests_carry_a_request_id(client, eng):
    r = client.get("/api/incidents", headers={**eng, "X-Request-ID": "abc123"})
    assert r.headers["X-Request-ID"] == "abc123"
    assert client.get("/api/incidents", headers=eng).headers["X-Request-ID"]
