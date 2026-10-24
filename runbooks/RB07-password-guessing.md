# RB07 · Password guessing on the login endpoint
**Service:** hoi-platform auth · **Severity:** SEV2 (security) · **Root cause:** someone is trying many passwords against `/auth/login` from one or a few IP addresses; the rate limiter is answering 429.

## Symptoms
- Burst of 401 on `/auth/login` for several usernames, then HTTP 429 `Too many attempts` on the same endpoint.
- Other endpoints are normal.

## Checks
```checks
[
  {"tool": "status_count", "args": {"status": 429, "path_prefix": "/auth/login"}, "field": "count", "op": ">=", "value": 3},
  {"tool": "distinct_clients_401", "args": {}, "field": "on_login", "op": ">=", "value": 5}
]
```

## Diagnosis
1. Group failed logins by source IP (X-Forwarded-For) and username.
2. Check whether any of the targeted accounts later logged in successfully from that IP.
3. Check the audit log for failed logins on admin accounts.

## Mitigation
- The limiter is already blocking; block the IP at the edge if it continues.
- Force a password reset for any account that was guessed; check failed-login counters.

## Escalation
Security contact if any login from the attacking IP succeeded.
