# Evaluation results

55 scenarios on the real HOI platform API (in-process, synthetic demo data): 45 injected incidents, 10 with no incident.

> Optimistic by construction: faults, alert rules and runbook checks were written by the same author.

| Metric | Value |
|---|---|
| Detection rate (an alert fired for an incident) | 91% |
| False-alarm rate (alert fired with no incident) | 0% |
| Retrieval recall@1 (hybrid, detected incidents) | 93% |
| Retrieval recall@3 (hybrid, detected incidents) | 98% |

| Mode | Accuracy (all) | Accuracy (detected incidents) | Wrong root cause | Abstained | Median ms |
|---|---|---|---|---|---|
| full | 93% | 100% | 0 | 0 | 3.0 |
| hybrid-top1 | 87% | 93% | 3 | 0 | 2.2 |
| bm25-top1 | 87% | 93% | 3 | 0 | 1.4 |
| dense-top1 | 87% | 93% | 3 | 0 | 1.8 |
| bm25+checks | 93% | 100% | 0 | 0 | 1.5 |

## Full copilot by scenario type

| Scenario | Correct |
|---|---|
| db_down | 5/5 |
| db_slow | 5/5 |
| llm_rate_limited | 5/5 |
| llm_key_missing | 5/5 |
| llm_schema_drift | 5/5 |
| jwt_secret_rotated | 5/5 |
| password_guessing | 3/5 |
| unsafe_prod_config | 5/5 |
| rate_limit_misconfigured | 3/5 |
| portal_down | 5/5 |
| healthy | 5/5 |

## Misses (full copilot)

- `password_guessing-0` truth RB07, predicted NONE, alerts none, params {'attempts': 8}, noise 0.03. no alert fired
- `password_guessing-1` truth RB07, predicted NONE, alerts none, params {'attempts': 12}, noise 0.05. no alert fired
- `rate_limit_misconfigured-3` truth RB10, predicted NONE, alerts none, params {'per_minute': 5}, noise 0.12. no alert fired
- `rate_limit_misconfigured-4` truth RB10, predicted NONE, alerts none, params {'per_minute': 8}, noise 0.15. no alert fired
