# RB06 · Token signing secret changed (all sessions invalid)
**Service:** hoi-platform · **Severity:** SEV2 · **Root cause:** the JWT signing secret (`HOI_JWT_SECRET`) changed (redeploy without the secret, so a random one was generated, or a manual rotation), so every token issued before the change fails verification.

## Symptoms
- Sudden spike of HTTP 401 on many different authenticated endpoints, for many users at once.
- Logins themselves succeed; the 401s are on normal API calls, not on `/auth/login`.
- Starts at a deploy or restart.

## Checks
```checks
[
  {"tool": "status_count", "args": {"status": 401}, "field": "count", "op": ">=", "value": 8},
  {"tool": "distinct_clients_401", "args": {}, "field": "elsewhere", "op": ">=", "value": 8},
  {"tool": "status_count", "args": {"status": 429, "path_prefix": "/auth/login"}, "field": "count", "op": "<", "value": 3}
]
```

## Diagnosis
1. Are the 401s spread across endpoints and users (secret changed) or concentrated on `/auth/login` (see RB07)?
2. Did they start together, right after a deploy? Gradual 401s over time are normal token expiry (RB12).
3. Check that `HOI_JWT_SECRET` is set on the current revision. Without it HOI uses a random per-process secret, which also breaks when there is more than one instance.

## Mitigation
- Restore the previous secret if the change was accidental; otherwise users must sign in again (the apps refresh or show the login screen).

## Escalation
Tell support that users will be signed out once.
