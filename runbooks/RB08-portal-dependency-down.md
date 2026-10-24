# RB08 · Tourism portal (places) dependency down
**Service:** hoi-platform guest concierge · **Severity:** SEV3/SEV4 · **Root cause:** the Uttarakhand tourism portal API that supplies nearby places is down or timing out.

## Symptoms
- Warnings `portal places ... failed: TimeoutError` / `HTTP 503`, or `places lookup failed`.
- Guests asking for places get only the hotel list or cached cards.
- Often no user-visible impact: HOI serves cached and hotel-provided places first.

## Checks
```checks
[
  {"tool": "search_logs", "args": {"pattern": "portal places"}, "field": "count", "op": ">=", "value": 3}
]
```

## Diagnosis
1. Check the portal `/health` and its own logs.
2. Count affected chats: if there are no warnings, the cache and hotel list covered every question and nothing is wrong for guests.

## Mitigation
- Nothing on the HOI side; the portal owner restores the service. Stale cards keep being served meanwhile.

## Escalation
Only if guests report missing places for more than a day.
