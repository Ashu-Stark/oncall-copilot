# RB13 · Inventory compensation step failed
**Service:** hoi-platform inventory · **Severity:** SEV2 · **Root cause:** a multi-step stock operation failed half way and the undo (compensation) also failed, so stock and the move ledger may disagree.

## Symptoms
- ERROR `inventory compensation step failed` with a traceback.
- Stock totals that no longer equal the sum of moves for an item.

## Checks
```checks
[
  {"tool": "search_logs", "args": {"pattern": "inventory compensation step failed"}, "field": "count", "op": ">=", "value": 1}
]
```

## Diagnosis
1. Find the request id in the traceback and the item/location involved.
2. Recompute stock from `inv_moves` for that item and compare with `inv_stock`.

## Mitigation
- Post a correcting count for the item; investigate why the first step failed (often a database timeout, see RB01).

## Escalation
Storekeeper and hotel owner if money values are affected.
