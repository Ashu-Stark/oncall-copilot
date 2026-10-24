# RB09 · Service refuses to start: unsafe production configuration
**Service:** hoi-platform · **Severity:** SEV1 · **Root cause:** the service was deployed with `HOI_ENV=production` but without the required production settings (JWT secret, admin password, real MongoDB URI, explicit CORS origins), and the HOI startup check refuses to boot.

## Symptoms
- The process exits during boot; the host shows the deploy as failed or crash-looping.
- Startup log: `RuntimeError: Unsafe production configuration:` followed by a list of missing settings.
- No request logs at all; health checks fail with connection errors.

## Checks
```checks
[
  {"tool": "search_logs", "args": {"pattern": "Unsafe production configuration"}, "field": "count", "op": ">=", "value": 1},
  {"tool": "status_summary", "args": {}, "field": "requests", "op": "==", "value": 0}
]
```

## Diagnosis
1. Read the startup traceback: it lists every missing setting by name.
2. Compare the environment of the failed revision with the last good one.

## Mitigation
- Set the listed variables in the host secret store (never in the repo) and redeploy, or roll back to the previous revision.

## Escalation
SEV1 until the service is serving again.
