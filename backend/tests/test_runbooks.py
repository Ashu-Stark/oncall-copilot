"""Runbook library: DSL validation with line numbers, roles, versions, optimistic locking, and that the copilot uses
whatever the library holds."""

from __future__ import annotations

from conftest import INGEST

from backend.app.runbook_store import validate

GOOD = """# RB17 · Queue consumer stuck
**Service:** hoi-platform · **Severity:** SEV2 · **Root cause:** the dispatch queue consumer stopped acknowledging jobs.

## Symptoms
- Log lines `dispatch consumer heartbeat missed`.

## Checks
```checks
[
  {"tool": "search_logs", "args": {"pattern": "dispatch consumer heartbeat missed"}, "field": "count", "op": ">=", "value": 3}
]
```

## Diagnosis
1. Check the consumer process.

## Mitigation
- Restart the consumer.
"""


def test_good_runbook_validates():
    errors, rb = validate(GOOD)
    assert errors == [] and rb.id == "RB17" and rb.checks[0]["tool"] == "search_logs"


def test_invalid_json_reports_the_line():
    bad = GOOD.replace('"value": 3}', '"value": 3,}')
    errors, _ = validate(bad)
    assert len(errors) == 1 and "not valid JSON" in errors[0]["message"]
    assert bad.splitlines()[errors[0]["line"] - 1].strip().startswith('{"tool"')


def test_unknown_tool_bad_args_and_bad_op_are_reported():
    bad = GOOD.replace(
        '{"tool": "search_logs", "args": {"pattern": "dispatch consumer heartbeat missed"}, "field": "count", "op": ">=", "value": 3}',
        '{"tool": "restart_service", "op": ">=", "value": 1}, {"tool": "status_count", "args": {"code": 500}, "op": "~", "value": 1}',
    )
    msgs = " | ".join(e["message"] for e in validate(bad)[0])
    assert "unknown tool 'restart_service'" in msgs  # tools are read-only by design: there is no restart tool
    assert "bad args for status_count" in msgs
    assert "op must be one of" in msgs


def test_missing_sections_and_title_are_reported():
    assert validate("hello world")[0][0]["line"] == 1
    no_mitigation = GOOD.split("## Mitigation")[0]
    assert any("Mitigation" in e["message"] for e in validate(no_mitigation)[0])


def test_engineers_cannot_edit_runbooks_leads_can(client, eng, lead):
    assert client.post("/api/runbooks", json={"markdown": GOOD}, headers=eng).status_code == 403
    r = client.post("/api/runbooks", json={"markdown": GOOD, "comment": "new failure mode"}, headers=lead)
    assert r.status_code == 201 and r.json()["version"] == 1
    assert client.post("/api/runbooks", json={"markdown": GOOD}, headers=lead).status_code == 409  # id taken


def test_invalid_runbook_is_rejected_with_errors(client, lead):
    r = client.put("/api/runbooks/RB01", json={"markdown": "# RB01 · Broken\nno checks"}, headers=lead)
    assert r.status_code == 422 and r.json()["detail"]["errors"]


def test_edits_create_versions_and_stale_edits_conflict(client, lead):
    rb = client.get("/api/runbooks/RB02", headers=lead).json()
    edited = rb["markdown"].replace("## Escalation", "## Escalation\nPage the DBA after 15 minutes.\n", 1)
    r = client.put("/api/runbooks/RB02", json={"markdown": edited, "comment": "escalation time", "base_version": 1}, headers=lead)
    assert r.status_code == 200 and r.json()["version"] == 2
    stale = client.put("/api/runbooks/RB02", json={"markdown": edited + "\n", "base_version": 1}, headers=lead)
    assert stale.status_code == 409
    versions = client.get("/api/runbooks/RB02", headers=lead).json()["versions"]
    assert [v["version"] for v in versions] == [2, 1]
    assert client.get("/api/runbooks/RB02/versions/1", headers=lead).json()["markdown"] == rb["markdown"]


def test_title_id_cannot_change_on_edit(client, lead):
    md = client.get("/api/runbooks/RB03", headers=lead).json()["markdown"].replace("# RB03", "# RB99", 1)
    r = client.post("/api/runbooks/validate", json={"markdown": md, "id": "RB03"}, headers=lead).json()
    assert not r["valid"] and "ids cannot be changed" in r["errors"][0]["message"]


def test_a_new_runbook_is_used_by_the_next_investigation(client, lead, eng):
    logs = [{"level": "WARNING", "logger": "hoi.dispatch", "message": "dispatch consumer heartbeat missed"} for _ in range(4)]
    logs += [{"level": "INFO", "logger": "hoi.platform", "message": f"rid=r{i} GET /dispatch/jobs -> 503 9ms"} for i in range(6)]
    logs += [{"level": "INFO", "logger": "hoi.platform", "message": f"rid=s{i} GET /rooms -> 200 9ms"} for i in range(30)]

    def investigate_new_incident(fp: str) -> str:
        r = client.post(
            "/api/alerts",
            json={"service": "hoi-platform", "name": "HighErrorRate", "summary": "dispatch 503s", "fingerprint": fp, "logs": logs, "health": {"ready": True}},
            headers=INGEST,
        ).json()
        return client.get(f"/api/investigations/{r['investigation_id']}", headers=eng).json()["label"]

    assert investigate_new_incident("before-rb17") == "UNKNOWN"  # no runbook describes this yet
    client.post("/api/runbooks", json={"markdown": GOOD}, headers=lead)
    assert investigate_new_incident("after-rb17") == "RB17"
