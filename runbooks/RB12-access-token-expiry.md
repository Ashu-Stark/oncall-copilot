# RB12 · Access tokens expiring (normal 401s)
**Service:** hoi-platform auth · **Severity:** SEV4 · **Root cause:** access tokens expire after `HOI_ACCESS_TTL_MINUTES` (30 by default); clients that do not refresh get 401 until they sign in again.

## Symptoms
- A trickle of 401s spread over time, one user at a time, each followed by a refresh or a login.
- No deploy at the start; no burst.

## Checks
```checks
[
  {"tool": "status_count", "args": {"status": 401}, "field": "count", "op": ">=", "value": 1},
  {"tool": "status_count", "args": {"status": 401}, "field": "share", "op": "<", "value": 0.1}
]
```

## Diagnosis
1. Do the 401s come in a burst across users (RB06) or one by one over time (this runbook)?
2. Check that the client calls `/auth/refresh` on 401.

## Mitigation
- Fix the client refresh handling; nothing to do on the server.

## Escalation
None.
