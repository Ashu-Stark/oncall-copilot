# RB14 · Dispatch conflicts (many 409 on job accept)
**Service:** hoi-platform dispatch · **Severity:** SEV4 · **Root cause:** several staff try to accept the same job at once; the HOI version check lets exactly one win and answers 409 to the others. Expected behaviour unless it is constant.

## Symptoms
- HTTP 409 on `/dispatch/jobs/<id>/accept` or `/decline`.

## Checks
```checks
[
  {"tool": "status_count", "args": {"status": 409, "path_prefix": "/dispatch/jobs"}, "field": "count", "op": ">=", "value": 3}
]
```

## Diagnosis
1. Are offers being sent to too many people at once? Check the dispatch ranking settings.

## Mitigation
- Offer each job to fewer people at a time; the 409s are harmless.

## Escalation
None.
