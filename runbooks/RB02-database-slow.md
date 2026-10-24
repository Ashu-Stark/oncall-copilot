# RB02 · Database slow (high query latency)
**Service:** hoi-platform · **Severity:** SEV2 · **Root cause:** MongoDB queries are slow (overloaded cluster, missing index, or a noisy neighbour), so every data-backed request is slow but still succeeds.

## Symptoms
- p95 latency jumps from tens of milliseconds to seconds on most endpoints, and stays high.
- Requests still return 200; few or no 5xx errors.
- `/ready` stays 200 (the ping succeeds, just slowly).

## Checks
```checks
[
  {"tool": "latency", "args": {}, "field": "p95_ms", "op": ">=", "value": 400},
  {"tool": "latency_trend", "args": {}, "field": "slow_only_at_start", "op": "==", "value": false},
  {"tool": "status_count", "args": {"status": "5xx"}, "field": "share", "op": "<", "value": 0.05}
]
```

## Diagnosis
1. Is the slowness sustained (not only the first requests after idle)? If only the first requests were slow, see RB11 (cold start).
2. Is it on every endpoint that touches MongoDB, or one route? One route usually means one slow query or a missing index.
3. Open the Atlas Query Profiler for collection scans on hot collections (`jobs`, `inv_stock`, `rooms`).
4. Check cluster CPU and connection count; the shared tier throttles under load.

## Mitigation
- Add the missing index (HOI creates its indexes idempotently at startup: check `ensure_indexes` ran).
- Scale the cluster tier or reduce load (pause batch jobs, reports).

## Escalation
SEV1 if p95 stays above 5 s for 15 minutes or requests start timing out.
