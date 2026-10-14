# Evaluation (Phase 6)

Tables: [`results.md`](results.md). Raw data (every case, every method's prediction, gold, trial counts): [`results.json`](results.json).

## Limitations, first

1. **Sherlock diagnoses deterministic nodes exactly and abstains honestly on stochastic ones** (spec 9.1). Plant faults in routers, parsers, retrievers, tool calls and validators and no model call sits on the counterfactual path, so every trial resolves. On a team whose faults are purely prompt-level, Sherlock abstains: when a bad node is a prompt variant of an LLM call, every cross-combination of "this node fixed, that node still bad" is a request that was never recorded, and a trial that needs an unrecorded call is reported as "cannot say", never guessed. The case `support_bot:prep.truncate+ask.terse_instruction` shows this: abstain, reason `unrecorded_call`, no culprit named. Single faults on the same team resolve, because the passing run's tape supplies the restored request.
2. **The teams are ours and the faults are planted by us.** Seven teams: four small (3 to 5 nodes) and three large (32 to 33 nodes: customer support, loan underwriting, revenue report), each fault a clean context flag. 84 of 86 cases exact is a statement about this setup, not about real agent failures. The claim that most real bugs live in deterministic nodes (spec 1.2, 9.1) is still unmeasured on real failures (STATUS open item).
3. **The "hidden" set is hidden from tuning, not from us.** It is a seeded sample (seed 20261014, 4 per team) of fault combinations that are not in the visible list, drawn from the same hand-written fault catalogue. It guards against tuning the engine on the visible cases; it is not an independent benchmark.
4. **Gold and Sherlock share a definition of "restore a node"**: remove that node's fault flags. Gold is derived in-process by restoring subsets and re-running the whole graph (FR-E3, never the planted names). Sherlock gets there through the fork, replay and search path over HTTP. Agreement shows the pipeline matches the oracle; it does not show the oracle is the right notion of cause for arbitrary code.
5. **Attribution needs a node map for flags not named after their node** (`--node-map`). Team 2 (`order_desk`) uses flags like `stale_inventory`; without the map `diagnose` abstains `cannot_attribute`. Teams 1, 3 and 4 use the `node.flag` naming convention and need none (the runner passes the map to all four). A restore goes only through run context (spec 4.4); a node whose behaviour is not configurable through context cannot be restored.
6. **We recover ancestry, not read-dependencies** (spec 9.2). Pruning is conservative.
7. **One known-good run per team, and one failing check Z per team.** Multi-source disagreement is tested elsewhere (Phase 4), not here.
8. Small numbers: 86 cases. No confidence intervals; counts are given, not rates to be compared across papers. Do not compare these figures with AgentRx, AgentTrace or Who&When numbers (spec 9.3).

9. **The "plain LLM guess" baseline is a stub, not a model.** `llm_guess_stub` (`python/sherlock/eval/baselines.py`) is a fixed local heuristic that stands in for "ask an LLM which node is wrong": it blames the node whose recorded output looks most anomalous (empty values, alarming words) from the failed run alone. It is deterministic and needs no provider. It shows what skimming the trace yields (6 of 86 exact, same as `last_node`); it says nothing about what GPT/Claude-class models would score. Do not quote it as an LLM result.
10. **Live time-travel (FR-E9) is a check on one two-cause case, not a scored row.** See "CI invariants".

## Method

- Cases: 52 visible (hand-picked) plus 34 hidden (seeded sample: 4 per small team, 6 per large team), over 7 teams. Defined in `harness/sherlock_harness/catalog.py`, including the hard-slice tags, before any method ran: `two_cause`, `or_fix` (two gold sets), `silent_decoy` (a harmless fault planted beside the real one), `abstain_by_design` (LLM prompt cross-combination). Hard slice = any of those (51 of 86 cases). `last_step_ok` (the node writing the output is not a culprit) is reported as its own slice.
- Pipeline per team group (`python/sherlock/eval/run_eval.py`): `sherlock-rec run langgraph dev` records one passing run per team and one failing run per case against a local echo stub; the stub goes away; the server restarts under `sherlock-rec run --replay` inside a socket trap that forbids every non-loopback connection; `diagnose` runs on each failing run with the team's passing run as the known-good source. The LLM team's cases each get their own lab and cassette holding only that case's own two tapes. (A shared cassette let other cases' requests turn the never-recorded combination into a hit; the first run did exactly that and showed no abstain. It was fixed before the results here.)
- Same tapes, same check Z, same cause definition for all methods (spec 9.3). A prediction is a collection of node sets. **exact** = the collection equals the gold collection; **wrong claim** = it names sets that differ; **abstain** = no claim. Abstains are reported beside accuracy and never counted as correct or wrong. Jaccard is over the union of nodes named.
- Added baselines (FR-E4, `python/sherlock/eval/baselines.py`, same cases, same Z, same scoring): `llm_guess_stub` (above; one node), `g0_g2` (G0 clue weights over the nodes G2's pruning leaves as candidates, top node, no G3 trial), `plain_retry` (re-run the failed run's own input and context 3 times on new threads and apply Z; a retry names no node, so it is always scored abstain `no_diagnosis`; it passed 0 of 258 retries).
- Baselines (`python/sherlock/src/sherlock/evaluation.py`): `last_node` (blame the node writing the output), `random_node` (seeded), `g0_only` (sum the G0 clue weights per node, blame the earliest top node, abstain with no clue), `paste_and_play` (restore by pasting the passing run's recorded output and keep every other recorded output; apply Z; pins FR-E8).

## Results (full tables in `results.md`)

All 86 cases:

| method | exact | wrong claim | abstain |
|---|---|---|---|
| sherlock | 84 | 0 | 2 |
| g0_only | 38 | 48 | 0 |
| random_node | 7 | 79 | 0 |
| last_node | 6 | 80 | 0 |
| paste_and_play | 5 | 79 | 2 |
| g0_g2 (clues + pruning, no G3) | 49 | 37 | 0 |
| llm_guess_stub (STUB) | 6 | 80 | 0 |
| plain_retry | 0 | 0 | 86 (no diagnosis) |

Hidden set (34): Sherlock 34 exact. Hard slice (51): Sherlock 49 exact, 2 abstain (the by-design LLM cases); best baseline 13 exact. Two-node gold (30): Sherlock 28 exact and 2 abstain; every baseline 0 exact. Sherlock used 174 trials where exhaustive enumeration over the same recorded paths (2^n - 1 subsets of the nodes on the path) would use 158,913,790,468 (100.0% fewer; NFR-8 asks at least 40%).

### At scale (the three large teams, 55 cases)

Pipelines of 32-33 nodes, up to 32 on a path: Sherlock used 1 trial on 27 cases, 3 on 27 and 7 on one, against up to 2^32 - 1 = 4,294,967,295 exhaustive subsets, and returned exactly the gold sets (single, two-cause, AND across parallel branches, two gold sets for a redundant repair). What removed the nodes: the passing run's outputs (a node that wrote the same thing is not tested) and no-op restores (491 / 503 / 578 removals on the three teams); ancestry pruning removed none, since every node here feeds the output. Per-team numbers are in the `Scale` table of `results.md`, and `Gate probes` there show each gate on one run per large team: G1 naming a wrong node first (still exact, it only reorders), G2 cutting a shortlist node that never ran, G2 with only such nodes (abstain), no known-good run (abstain), and a planted-but-harmless run (`already_passes`). The 30+ node teams are the same kind of synthetic as the small ones: a search that stays this small on them says the context-flag setup prunes well, not that real hundred-agent failures are this easy.

The baselines are deliberately cheap. They show that the cases are not solvable by blaming the last node or reading error clues (most faults are silent), not that Sherlock beats a strong learned method.

## CI invariants

`./scripts/test.sh` stage "evaluation" regenerates the whole table (about 5 minutes: it records and replays real `langgraph dev` servers) and diffs it with the committed `results.json`, so:

- **FR-E9, live time-travel must fail the two-cause case**: `invariants.live_time_travel` in `results.json`. The baseline forks the failed run before each node on its path, restores that ONE node, resumes with no cassette (`cassette_path=None`: no replay-session requirement, a cassette miss is not turned into "cannot say", a call nobody recorded would run live) and applies Z. On `vendor_brief:retriever.drop_latest+extractor.legacy_pattern` all five single restores fail Z, so it names nothing (outcome abstain), while Sherlock returns `{retriever, extractor}` exactly. Control `vendor_brief:router.wrong_source`: the same baseline passes on `router`, so it is not a straw man. The run fails (`failures`) if live time-travel ever solves the two-cause case or cannot solve the control. What this proves: one-point time-travel cannot localize two independent causes, each sufficient to break Z. What it does not prove: that cassette blocking matters here. vendor_brief makes no model call, so live and replayed re-runs are identical; a live resume could only pass this case by restoring both nodes at once, which is the set search Sherlock does. Blocking matters on LLM nodes (a live call would return something other than the recorded tape), and that is covered by the `support_bot` abstain case, not by this invariant.
- **Reproducible and freeze-stable (FR-E7)**: new processes, ports and thread ids, identical minimal sets, trial counts and baselines. The runner exits 1 on any difference.
- **Replay made zero network calls (NFR-3)**: the replay server runs in a socket trap; any attempt is recorded and fails the run.
- **Original thread unchanged after forks**: each failing run's checkpoint history is compared before and after its diagnosis.
- **Verdicts never claim culprits on abstain; every abstain has a reason (NFR-4)**: checked on every artifact; the offline test `tests/test_eval_results.py` re-checks the committed file, plus Sherlock >= every baseline, exact on deterministic cases, abstain on the by-design case, and paste-and-play failing every two-cause case (FR-E8).

## What we did not do

- Baselines from FR-E4 not built as specified: a real-model LLM guess (only the stub exists), random-node averaged over many seeds. `g0_g2` uses G2's pruning, not the suspect path check (that needs G1 suspects, which are off in this eval).
- No real provider, no real agent failures, no human-labelled failures, no stochastic-node measurement beyond the one prompt-variant case. The LLM team talks to a deterministic echo stub, so "the model call differs" is modelled by a request-body change, not by sampling noise.
- No loop or tool-using demo team; teams are DAGs of plain functions plus one httpx call.
- No cross-method statistics, confidence intervals, or ablation of pruning and ordering.
- Non-functional claims, honestly: **NFR-11** (install to first diagnosis in 15 minutes): NOT measured end to end; a clean `make setup` was not timed. What was measured: `tests/seed_demo.py` (start `langgraph dev` under `sherlock-rec run`, record 4 runs, restart under replay, run 3 diagnoses on `vendor_brief`) took 24 s wall clock, with an evaluation running concurrently, so that is an upper bound for the run-to-first-diagnosis part on this laptop (Windows, warm uv cache). It excludes toolchain install, `uv sync`, `npm ci` and the cargo build, which dominate a clean install and were not timed. **NFR-14** (a stranger understands the seeded failure in 10 minutes): needs a user test, not measured.
- Mid-evaluation date and required demo: still an open item for the team.
