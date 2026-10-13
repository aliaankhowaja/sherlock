# Evaluation (Phase 6)

Tables: [`results.md`](results.md). Raw data (every case, every method's prediction, gold, trial counts): [`results.json`](results.json).

## Limitations, first

1. **Sherlock diagnoses deterministic nodes exactly and abstains honestly on stochastic ones** (spec 9.1). Plant faults in routers, parsers, retrievers, tool calls and validators and no model call sits on the counterfactual path, so every trial resolves. On a team whose faults are purely prompt-level, Sherlock abstains: when a bad node is a prompt variant of an LLM call, every cross-combination of "this node fixed, that node still bad" is a request that was never recorded, and a trial that needs an unrecorded call is reported as "cannot say", never guessed. The case `support_bot:prep.truncate+ask.terse_instruction` shows this: abstain, reason `unrecorded_call`, no culprit named. Single faults on the same team resolve, because the passing run's tape supplies the restored request.
2. **The teams are ours and the faults are planted by us.** Four small teams (3 to 5 nodes), each fault a clean context flag. 30 of 31 cases exact is a statement about this setup, not about real agent failures. The claim that most real bugs live in deterministic nodes (spec 1.2, 9.1) is still unmeasured on real failures (STATUS open item).
3. **The "hidden" set is hidden from tuning, not from us.** It is a seeded sample (seed 20261014, 4 per team) of fault combinations that are not in the visible list, drawn from the same hand-written fault catalogue. It guards against tuning the engine on the visible cases; it is not an independent benchmark.
4. **Gold and Sherlock share a definition of "restore a node"**: remove that node's fault flags. Gold is derived in-process by restoring subsets and re-running the whole graph (FR-E3, never the planted names). Sherlock gets there through the fork, replay and search path over HTTP. Agreement shows the pipeline matches the oracle; it does not show the oracle is the right notion of cause for arbitrary code.
5. **Attribution needs a node map for flags not named after their node** (`--node-map`). Team 2 (`order_desk`) uses flags like `stale_inventory`; without the map `diagnose` abstains `cannot_attribute`. Teams 1, 3 and 4 use the `node.flag` naming convention and need none (the runner passes the map to all four). A restore goes only through run context (spec 4.4); a node whose behaviour is not configurable through context cannot be restored.
6. **We recover ancestry, not read-dependencies** (spec 9.2). Pruning is conservative.
7. **One known-good run per team, and one failing check Z per team.** Multi-source disagreement is tested elsewhere (Phase 4), not here.
8. Small numbers: 31 cases. No confidence intervals; counts are given, not rates to be compared across papers. Do not compare these figures with AgentRx, AgentTrace or Who&When numbers (spec 9.3).

## Method

- Cases: 15 visible (hand-picked) plus 16 hidden (seeded sample), over 4 teams. Defined in `harness/sherlock_harness/catalog.py`, including the hard-slice tags, before any method ran: `two_cause`, `or_fix` (two gold sets), `silent_decoy` (a harmless fault planted beside the real one), `abstain_by_design` (LLM prompt cross-combination). Hard slice = any of those (21 of 31 cases). `last_step_ok` (the node writing the output is not a culprit) is reported as its own slice.
- Pipeline per team group (`python/sherlock/eval/run_eval.py`): `sherlock-rec run langgraph dev` records one passing run per team and one failing run per case against a local echo stub; the stub goes away; the server restarts under `sherlock-rec run --replay` inside a socket trap that forbids every non-loopback connection; `diagnose` runs on each failing run with the team's passing run as the known-good source. The LLM team's cases each get their own lab and cassette holding only that case's own two tapes. (A shared cassette let other cases' requests turn the never-recorded combination into a hit; the first run did exactly that and showed no abstain. It was fixed before the results here.)
- Same tapes, same check Z, same cause definition for all methods (spec 9.3). A prediction is a collection of node sets. **exact** = the collection equals the gold collection; **wrong claim** = it names sets that differ; **abstain** = no claim. Abstains are reported beside accuracy and never counted as correct or wrong. Jaccard is over the union of nodes named.
- Baselines (`python/sherlock/src/sherlock/evaluation.py`): `last_node` (blame the node writing the output), `random_node` (seeded), `g0_only` (sum the G0 clue weights per node, blame the earliest top node, abstain with no clue), `paste_and_play` (restore by pasting the passing run's recorded output and keep every other recorded output; apply Z; pins FR-E8).

## Results (full tables in `results.md`)

All 31 cases:

| method | exact | wrong claim | abstain |
|---|---|---|---|
| sherlock | 30 | 0 | 1 |
| g0_only | 10 | 21 | 0 |
| last_node | 5 | 26 | 0 |
| paste_and_play | 5 | 26 | 0 |
| random_node | 4 | 27 | 0 |

Hidden set (16): Sherlock 16 exact. Hard slice (21): Sherlock 20 exact, 1 abstain (the by-design LLM case); best baseline 4 exact. Two-node gold (11): Sherlock 10 exact and 1 abstain; every baseline 0 exact, since each names a single node. Sherlock used 68 trials where exhaustive enumeration over the same recorded paths would use 538 (87.4% fewer; NFR-8 asks at least 40%).

The baselines are deliberately cheap. They show that the cases are not solvable by blaming the last node or reading error clues (most faults are silent), not that Sherlock beats a strong learned method.

## CI invariants

`./scripts/test.sh` stage "evaluation" regenerates the whole table (about 5 minutes: it records and replays real `langgraph dev` servers) and diffs it with the committed `results.json`, so:

- **Reproducible and freeze-stable (FR-E7)**: new processes, ports and thread ids, identical minimal sets, trial counts and baselines. The runner exits 1 on any difference.
- **Replay made zero network calls (NFR-3)**: the replay server runs in a socket trap; any attempt is recorded and fails the run.
- **Original thread unchanged after forks**: each failing run's checkpoint history is compared before and after its diagnosis.
- **Verdicts never claim culprits on abstain; every abstain has a reason (NFR-4)**: checked on every artifact; the offline test `tests/test_eval_results.py` re-checks the committed file, plus Sherlock >= every baseline, exact on deterministic cases, abstain on the by-design case, and paste-and-play failing every two-cause case (FR-E8).

## What we did not do

- **FR-E9** (live time-travel without call blocking must fail the two-cause case): no live-fallback baseline was built.
- Baselines from FR-E4 not built: plain LLM guess (needs a model and a key), plain retry, random-node averaged over many seeds, and G0+G2 as separate rows (`g0_only` uses clues only; the path check needs a suspect list).
- No real provider, no real agent failures, no human-labelled failures, no stochastic-node measurement beyond the one prompt-variant case. The LLM team talks to a deterministic echo stub, so "the model call differs" is modelled by a request-body change, not by sampling noise.
- No loop or tool-using demo team; teams are DAGs of plain functions plus one httpx call.
- No cross-method statistics, confidence intervals, or ablation of pruning and ordering.
- Mid-evaluation date and required demo: still an open item for the team.
