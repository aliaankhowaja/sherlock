# G1 zero-shot evaluation (laya, g1_questions_v1)

## Methods

| method | cases | multi_candidate | mrr | recall3 | ndcg3 | fix_mean | fix_median | no_fix | exhausted_default | exhausted_tight |
|---|---|---|---|---|---|---|---|---|---|---|
| random | 100 | 98 | 0.576 | 0.675 | 0.543 | 7.88 | 6.5 | 0 | 0 | 27 |
| g0 | 100 | 98 | 0.607 | 0.73 | 0.581 | 8.18 | 6.0 | 0 | 0 | 22 |
| rule | 100 | 98 | 0.607 | 0.73 | 0.581 | 8.18 | 6.0 | 0 | 0 | 22 |
| hint | 100 | 98 | 0.607 | 0.73 | 0.581 | 8.18 | 6.0 | 0 | 0 | 22 |
| laya | 100 | 98 | 0.47 | 0.505 | 0.396 | 10.83 | 8.5 | 0 | 0 | 36 |
| laya_masked | 100 | 98 | 0.434 | 0.505 | 0.376 | 11.03 | 7.0 | 0 | 0 | 36 |

## Analysis columns (not methods)

| column | cases | multi_candidate | mrr | recall3 | ndcg3 | fix_mean | fix_median | no_fix | exhausted_default | exhausted_tight |
|---|---|---|---|---|---|---|---|---|---|---|
| laya_alone | 100 | 98 | 0.47 | 0.505 | 0.396 | 10.83 | 8.5 | 0 | 0 | 36 |
| q2 | 100 | 98 | 0.72 | 0.76 | 0.67 | 7.21 | 6.0 | 0 | 0 | 18 |
| optimal | 100 | 98 | 1.0 | 1.0 | 1.0 | 3.28 | 4.0 | 0 | 0 | 0 |

## Per team (mean trials to first fix)

| team | cases | g0 | rule | laya | optimal |
|---|---|---|---|---|---|
| gen_n10 | 3 | 6.667 | 6.667 | 8.333 | 3.667 |
| gen_n11 | 2 | 6.5 | 6.5 | 7 | 3 |
| gen_n12 | 3 | 11.333 | 11.333 | 14.667 | 4 |
| gen_n13 | 3 | 6.333 | 6.333 | 6.667 | 4.333 |
| gen_n14 | 1 | 28 | 28 | 28 | 4 |
| gen_n15 | 4 | 4.5 | 4.5 | 7.5 | 2.25 |
| gen_n16 | 6 | 4.5 | 4.5 | 11.833 | 3 |
| gen_n17 | 6 | 6 | 6 | 6.333 | 2.667 |
| gen_n18 | 1 | 6 | 6 | 20 | 4 |
| gen_n19 | 1 | 10 | 10 | 10 | 3 |
| gen_n20 | 1 | 7 | 7 | 12 | 4 |
| gen_n21 | 3 | 7.667 | 7.667 | 8.333 | 4 |
| gen_n22 | 4 | 12.25 | 12.25 | 13.25 | 4.5 |
| gen_n23 | 1 | 3 | 3 | 3 | 2 |
| gen_n24 | 6 | 7.5 | 7.5 | 10.5 | 2.667 |
| gen_n25 | 4 | 10.75 | 10.75 | 12 | 3 |
| gen_n26 | 2 | 15 | 15 | 16 | 4 |
| gen_n27 | 3 | 11.667 | 11.667 | 11.667 | 2.333 |
| gen_n28 | 6 | 10.333 | 10.333 | 9.5 | 3.333 |
| gen_n29 | 2 | 3.5 | 3.5 | 4.5 | 3 |
| gen_n30 | 3 | 6 | 6 | 13 | 3.333 |
| gen_n31 | 2 | 9.5 | 9.5 | 9.5 | 4 |
| gen_n32 | 5 | 12.6 | 12.6 | 15.6 | 3.6 |
| gen_n33 | 3 | 3 | 3 | 6.667 | 1.667 |
| gen_n34 | 3 | 8.333 | 8.333 | 10 | 3.667 |
| gen_n35 | 1 | 2 | 2 | 16 | 2 |
| gen_n36 | 3 | 6.333 | 6.333 | 12 | 3.667 |
| gen_n37 | 3 | 3.333 | 3.333 | 13 | 2.667 |
| gen_n38 | 3 | 6 | 6 | 5.667 | 3.333 |
| gen_n39 | 5 | 11.4 | 11.4 | 12.2 | 3.6 |
| gen_n40 | 4 | 12.25 | 12.25 | 15 | 4.5 |
| gen_n8 | 2 | 4.5 | 4.5 | 11 | 3 |
| gen_n9 | 1 | 5 | 5 | 9 | 2 |

## Gate
min(g0, rule) matches optimal in 0.22 of cases; gate_fires=False (true: planted data cannot show a gain)

## Cost
| method | calls | cache hits | ms | statuses |
|---|---|---|---|---|
| laya | 473 | 0 | 205578 | {'ok': 98, 'skipped': 2} |
| laya_masked | 473 | 0 | 209662 | {'ok': 98, 'skipped': 2} |
