# G1 zero-shot evaluation (laya, g1_questions_v1)

## Methods

| method | cases | multi_candidate | mrr | recall3 | ndcg3 | fix_mean | fix_median | no_fix | exhausted_default | exhausted_tight |
|---|---|---|---|---|---|---|---|---|---|---|
| random | 84 | 43 | 0.97 | 1.0 | 0.978 | 1.238 | 1.0 | 0 | 0 | 33 |
| g0 | 84 | 43 | 0.982 | 1.0 | 0.987 | 1.214 | 1.0 | 0 | 0 | 31 |
| rule | 84 | 43 | 0.976 | 1.0 | 0.982 | 1.226 | 1.0 | 0 | 0 | 32 |
| hint | 84 | 43 | 0.97 | 1.0 | 0.978 | 1.238 | 1.0 | 0 | 0 | 33 |
| laya | 84 | 43 | 0.976 | 1.0 | 0.982 | 1.226 | 1.0 | 0 | 0 | 32 |
| laya_masked | 84 | 43 | 0.964 | 1.0 | 0.974 | 1.25 | 1.0 | 0 | 0 | 34 |

## Analysis columns (not methods)

| column | cases | multi_candidate | mrr | recall3 | ndcg3 | fix_mean | fix_median | no_fix | exhausted_default | exhausted_tight |
|---|---|---|---|---|---|---|---|---|---|---|
| laya_alone | 84 | 43 | 0.976 | 1.0 | 0.982 | 1.226 | 1.0 | 0 | 0 | 32 |
| q2 | 84 | 43 | 0.976 | 1.0 | 0.982 | 1.226 | 1.0 | 0 | 0 | 32 |
| optimal | 84 | 43 | 1.0 | 1.0 | 1.0 | 1.179 | 1.0 | 0 | 0 | 28 |

## Per team (mean trials to first fix)

| team | cases | g0 | rule | laya | optimal |
|---|---|---|---|---|---|
| invoice_pipeline | 7 | 1.571 | 1.714 | 1.429 | 1.429 |
| loan_underwriting | 18 | 1.222 | 1.222 | 1.222 | 1.222 |
| order_desk | 7 | 1 | 1 | 1 | 1 |
| revenue_report | 19 | 1.158 | 1.158 | 1.158 | 1.105 |
| support_bot | 7 | 1.286 | 1.286 | 1.571 | 1.286 |
| support_desk | 17 | 1.118 | 1.118 | 1.176 | 1.118 |
| vendor_brief | 9 | 1.333 | 1.333 | 1.222 | 1.222 |

## Gate
min(g0, rule) matches optimal in 0.964 of cases; gate_fires=True (true: planted data cannot show a gain)

## Cost
| method | calls | cache hits | ms | statuses |
|---|---|---|---|---|
| laya | 0 | 87 | 97 | {'skipped': 41, 'ok': 40, 'partial': 3} |
| laya_masked | 0 | 87 | 17 | {'skipped': 41, 'ok': 34, 'partial': 9} |

## Stability
laya order identical in 3 passes: 1.0 of 43 cases with 2+ candidates
