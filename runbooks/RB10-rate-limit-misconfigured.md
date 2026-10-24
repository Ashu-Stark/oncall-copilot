# RB10 · Rate limit set too low (legitimate users throttled)
**Service:** hoi-platform guest concierge · **Severity:** SEV2 · **Root cause:** a configuration change set a rate limit (e.g. `HOI_GUEST_CHAT_RATE_PER_MINUTE`) far too low, or many guests share one proxy IP, so normal guests get HTTP 429.

## Symptoms
- HTTP 429 on guest endpoints (`/public/guest/<token>/chat`) across many rooms, during normal traffic.
- No failed-login burst; 401s are normal.
- Started at a configuration change or deploy.

## Checks
```checks
[
  {"tool": "status_count", "args": {"status": 429, "path_prefix": "/public/guest"}, "field": "count", "op": ">=", "value": 3},
  {"tool": "status_count", "args": {"status": 429, "path_prefix": "/auth/login"}, "field": "count", "op": "<", "value": 3}
]
```

## Diagnosis
1. Which endpoints get 429? Guest chat across many rooms means a limit problem, not an attack on login (RB07).
2. Compare the `HOI_*_RATE_PER_MINUTE` values on the current revision with the defaults (guest chat: 10 per room per minute; the per-IP limit is 3x that).
3. Behind a proxy, check that `X-Forwarded-For` is passed, otherwise every guest shares one IP bucket.

## Mitigation
- Restore the previous limit values and restart; fix proxy headers if all clients appear as one IP.

## Escalation
None once limits are restored.
