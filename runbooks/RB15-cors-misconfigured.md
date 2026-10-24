# RB15 · CORS misconfigured (browser blocks the dashboard)
**Service:** hoi-platform · **Severity:** SEV2 · **Root cause:** `HOI_CORS_ORIGINS` does not include the dashboard origin, so browsers block the responses even though the API answers 200.

## Symptoms
- Users see "failed to fetch" in the browser; server logs show normal 200 responses or OPTIONS preflights answered 400.
- Server-side tools (curl, the Streamlit dashboard server) still work.

## Checks
```checks
[
  {"tool": "status_count", "args": {"status": 400}, "field": "count", "op": ">=", "value": 3},
  {"tool": "search_logs", "args": {"pattern": "OPTIONS"}, "field": "count", "op": ">=", "value": 3}
]
```

## Diagnosis
1. Open the browser console: a CORS error names the blocked origin.
2. Compare it with `HOI_CORS_ORIGINS` on the current revision.

## Mitigation
- Add the exact origin (scheme + host + port) and redeploy.

## Escalation
None.
