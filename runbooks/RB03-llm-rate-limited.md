# RB03 · LLM provider rate limited (HTTP 429)
**Service:** hoi-platform guest concierge · **Severity:** SEV3 · **Root cause:** the LLM provider (Groq) is rejecting calls with HTTP 429 because the account request or token quota is used up.

## Symptoms
- `concierge fallback to rules: llm call failed (HTTP 429)` repeated in the logs.
- Guests still get answers (rule-based), but replies are simpler; no 5xx errors.
- The AI adapter logs `key #n failed` when backup keys also hit their limits.

## Checks
```checks
[
  {"tool": "search_logs", "args": {"pattern": "llm call failed (HTTP 429)"}, "field": "count", "op": ">=", "value": 2}
]
```

## Diagnosis
1. Confirm the failure reason is 429, not a missing key (RB04) or bad output (RB05).
2. Check the provider dashboard for the quota window (per minute vs per day).
3. Check whether traffic grew (more guests chatting) or a loop is calling the LLM repeatedly.

## Mitigation
- HOI already backs off (cooldown after 429) and answers from rules: no outage, degraded quality.
- Add a backup key (`LLM_API_KEYS_BACKUP`) or move to a paid tier; lower per-room chat limits if one room is flooding.

## Escalation
None needed unless it lasts more than a day.
