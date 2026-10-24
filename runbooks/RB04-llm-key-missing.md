# RB04 · LLM API key missing or not configured
**Service:** hoi-platform guest concierge · **Severity:** SEV3 · **Root cause:** the deployment has no LLM API key (`LLM_API_KEY` / `GROQ_API_KEY` not set), usually after a redeploy or an environment change.

## Symptoms
- Every concierge chat logs `concierge fallback to rules: set LLM_API_KEY or GROQ_API_KEY`.
- No calls reach the provider at all; no 429s, no provider errors.
- Starts exactly at a deploy or an environment variable change.

## Checks
```checks
[
  {"tool": "search_logs", "args": {"pattern": "set LLM_API_KEY or GROQ_API_KEY"}, "field": "count", "op": ">=", "value": 2}
]
```

## Diagnosis
1. Check the hosting provider environment settings for the service: is the key present on the current revision?
2. Check the last deploy: a new service or a blueprint sync can drop secrets that were set by hand.

## Mitigation
- Set the key in the host secret store (never in the repo) and restart the service.

## Escalation
None; quality is degraded, not down.
