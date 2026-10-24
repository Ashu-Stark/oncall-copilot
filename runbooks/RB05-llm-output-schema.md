# RB05 · LLM output no longer matches the schema
**Service:** hoi-platform guest concierge · **Severity:** SEV3 · **Root cause:** the model or provider changed (new model id, provider update, JSON mode off) and replies are not valid JSON for the HOI reply schema, so every reply is rejected.

## Symptoms
- `concierge fallback to rules: llm reply rejected: invalid JSON for the schema` on most chats.
- Calls do reach the provider (no 429, no missing key), they just come back in the wrong shape.

## Checks
```checks
[
  {"tool": "search_logs", "args": {"pattern": "invalid JSON for the schema"}, "field": "count", "op": ">=", "value": 2}
]
```

## Diagnosis
1. Check `LLM_MODEL`, `LLM_BASE_URL` and `LLM_JSON_MODE` on the current revision; compare with the last known good.
2. Check the provider changelog for model deprecations.
3. Replay one prompt against the provider and inspect the raw reply shape.

## Mitigation
- Pin the previous model id or turn JSON mode back on; HOI keeps answering from rules meanwhile.

## Escalation
None.
