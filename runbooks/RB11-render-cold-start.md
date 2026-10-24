# RB11 · Cold start after idle (free hosting tier)
**Service:** any HOI service on the Render free tier · **Severity:** SEV4 · **Root cause:** the free tier puts the service to sleep after about 15 minutes idle; the first requests after waking take 20-60 seconds.

## Symptoms
- A few very slow requests right after a quiet period, then normal latency.
- No errors in the application; the host shows the instance starting.

## Checks
```checks
[
  {"tool": "latency", "args": {}, "field": "p95_ms", "op": ">=", "value": 400},
  {"tool": "latency_trend", "args": {}, "field": "slow_only_at_start", "op": "==", "value": true}
]
```

## Diagnosis
1. Is the slowness limited to the first requests after idle? Sustained slowness is not a cold start (see RB02).

## Mitigation
- Wake the service before demos (`scripts/wake_demo.py`) or move to a paid instance that does not sleep.

## Escalation
None.
