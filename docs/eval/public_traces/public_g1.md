# Public-trace ordering (laya)

This compares orders against the published label. A lower trial count means the order named the labelled agents earlier. It does not mean those agents are a minimal fix, and it does not mean restoring them would make the task pass.

mathchat rows tagged `two_role` are not in these means.

## Methods

| method | rows | rank | reciprocal rank | recall@3 | ndcg@3 | trials_to_label | no trial |
|---|---|---|---|---|---|---|---|
| random | 4112 | 1.679 | 0.732 | 0.866 | 0.731 | 6.518 | 0 |
| path | 4112 | 1.627 | 0.747 | 0.855 | 0.747 | 6.098 | 0 |
| g0 | 4112 | 1.656 | 0.745 | 0.854 | 0.745 | 6.328 | 0 |
| laya | 4112 | 1.634 | 0.759 | 0.85 | 0.745 | 6.745 | 0 |
| laya_masked | 4112 | 1.638 | 0.757 | 0.848 | 0.743 | 6.787 | 0 |

## aegis

| method | rows | rank | reciprocal rank | recall@3 | ndcg@3 | trials_to_label | no trial |
|---|---|---|---|---|---|---|---|
| random | 2364 | 1.55 | 0.784 | 0.789 | 0.729 | 8.703 | 0 |
| path | 2364 | 1.67 | 0.724 | 0.768 | 0.692 | 8.228 | 0 |
| g0 | 2364 | 1.707 | 0.726 | 0.766 | 0.692 | 8.614 | 0 |
| laya | 2364 | 1.637 | 0.76 | 0.761 | 0.699 | 9.327 | 0 |
| laya_masked | 2364 | 1.651 | 0.753 | 0.756 | 0.694 | 9.417 | 0 |

## whowhen

| method | rows | rank | reciprocal rank | recall@3 | ndcg@3 | trials_to_label | no trial |
|---|---|---|---|---|---|---|---|
| random | 1748 | 1.854 | 0.662 | 0.972 | 0.735 | 3.564 | 0 |
| path | 1748 | 1.57 | 0.778 | 0.973 | 0.822 | 3.217 | 0 |
| g0 | 1748 | 1.588 | 0.771 | 0.973 | 0.817 | 3.237 | 0 |
| laya | 1748 | 1.63 | 0.758 | 0.971 | 0.806 | 3.252 | 0 |
| laya_masked | 1748 | 1.619 | 0.762 | 0.971 | 0.809 | 3.23 | 0 |

## g0_only

g0_only names one node. One-name labels are a match rate. Several names report whether that node sits in the label, and the Jaccard of the two sets.

| labels | rows | name in label | Jaccard |
|---|---|---|---|
| one name | 1974 | 0.141 | - |
| several names | 2138 | 0.234 | 0.247 |

## Appendix: two_role

920 rows. Node names: assistant, user_proxy.
These rows have no rank, no reciprocal rank, no recall@3, no ndcg@3, and no trials_to_label.
