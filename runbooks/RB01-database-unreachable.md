# RB01 · Database unreachable (MongoDB)
**Service:** hoi-platform · **Severity:** SEV1 · **Root cause:** the API cannot reach the MongoDB cluster, so every request that reads or writes data fails.

## Symptoms
- Sudden burst of HTTP 500 responses across many unrelated endpoints (rooms, inventory, guest pages, chat).
- Log lines `unhandled error rid=...` with `pymongo.errors.ServerSelectionTimeoutError ... timed out`.
- Readiness probe fails: `readiness check failed: database ping did not succeed`, `/ready` returns 503.
- `/health` still answers 200 (it does not touch the database), so uptime checks on `/health` look green.

## Checks
```checks
[
  {"tool": "search_logs", "args": {"pattern": "ServerSelectionTimeoutError"}, "field": "count", "op": ">=", "value": 1},
  {"tool": "status_count", "args": {"status": "5xx"}, "field": "share", "op": ">=", "value": 0.1},
  {"tool": "health", "args": {}, "field": "ready", "op": "==", "value": false}
]
```

## Diagnosis
1. Confirm the 500s share one cause: group errors by message template; they should all end in `ServerSelectionTimeoutError`.
2. Check Atlas status and the cluster metrics (connections, primary elections) for the same time window.
3. Check the Atlas network access list: outbound IPs of the host can change; a missing entry gives exactly this timeout.
4. Check that `MONGODB_URI` was not changed in the last deploy (wrong host or credentials). Never print the URI.

## Mitigation
- If Atlas is down or electing a primary: wait for recovery; the driver reconnects on its own (serverSelectionTimeoutMS=8000).
- If the access list is wrong: add the service egress IPs, then watch `/ready` turn 200.
- If the URI changed: roll back the environment variable to the previous value and redeploy.

## Escalation
Page the database owner if the cluster itself is unhealthy for more than 10 minutes.
