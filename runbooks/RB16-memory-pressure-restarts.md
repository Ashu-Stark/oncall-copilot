# RB16 · Memory pressure: worker killed and restarted
**Service:** any HOI service · **Severity:** SEV2 · **Root cause:** the process exceeds the instance memory (large uploads, local speech-to-text model) and the host kills and restarts it.

## Symptoms
- Host events "out of memory" / "instance restarted"; startup log lines repeating mid-day.
- Requests in flight at the restart fail with 502 at the proxy.

## Checks
```checks
[
  {"tool": "search_logs", "args": {"pattern": "out of memory"}, "field": "count", "op": ">=", "value": 1},
  {"tool": "status_count", "args": {"status": 502}, "field": "count", "op": ">=", "value": 1}
]
```

## Diagnosis
1. Correlate restarts with large requests (photo uploads, audio transcription).
2. Check whether the local speech-to-text model is loaded on a small instance.

## Mitigation
- Use cloud speech-to-text on small instances; cap upload sizes; move to a larger instance.

## Escalation
SEV1 if restarts loop.
