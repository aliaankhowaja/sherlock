> **Working note (tier 3). Not authoritative.** A plan, not a result. Re-check it against the code before anyone builds it. Never cite this file in a submission.

# Plan: an automated replay corpus

Status: revision 4, 2026-11-17. Three grills. Round 3 found no fatal hole. The stop rules below include the non-fatal fixes from that round.

## What we are trying to do

Sherlock takes one failed run of a multi-agent team and one run of the same task that passed. It replays the recording offline, puts one agent's known-good behaviour back at a time, and reports the smallest set of agents that makes the task pass. If the replay would need a model call that was never recorded, it says it cannot tell, instead of calling the model or inventing a reply.

A test of that claim needs four things for each case:

- the passing run, which is what each agent wrote when the task succeeded
- the failed run
- the saved model reply, so the replay can run with the network off
- the task's own answer key, so "the task passed" is not a sentence we wrote

The 86 planted cases already have the first three, on seven demo teams we wrote, with an echo stub standing in for the model. They show the search matches its own restore rule. They do not show it on questions that came from outside the repo.

## The problem

We collected AEGIS and Who&When Pro from Hugging Face and converted them into Sherlock history: 5,032 traces, 4,112 in the ordering headline. They are failed transcripts from real agent frameworks, plus a published name for who was at fault. AEGIS also stores `correct_answer`, the worked solution. Who&When Pro stores `task.answer`, the benchmark's answer, on every text row (empty for ALFWorld and LiveCodeBench-Pro).

That answer key is not a known-good agent. It says whether the final answer is right. It does not say what an earlier agent wrote on a run that passed, and the files do not contain a second, successful trajectory or any saved model request. The spec already draws this line: a pasted final answer is a check, and it cannot restore an upstream node. The converter keeps AEGIS's short answer as `reference` and never reads Who&When's `task.answer`, so the converted rows are thinner than the snapshots.

The ordering numbers on those 4,112 rows stay valid as an ordering comparison against the published names. They do not say that putting those agents back would make the task pass. The draft paper says the same thing: the public corpus supports ordering claims only.

Editing the converted rows does not fix this. The reply a downstream agent would give after an upstream agent is restored was never produced, so there is nothing honest to cache. Writing that reply in by hand, or asking another model to write it while looking at the blame label, plants the answer the search is supposed to find. Re-running the original frameworks over the old logs is a new execution, not a cache of the old one: the logs do not contain the prompts, seeds, or tool state.

Sampling more fault pairs from the current harness does not fix it either. Each of the seven teams has one fixed input. More pairs are more bugs on the same seven questions, still graded by checks we wrote.

The papers that do intervene start from a successful run and then publish only the failure. AEGIS and Who&When Pro both keep a successful seed while they build the data, and the released row is the failed trace. Their label is the injection site. GCJR reruns live with paired clean messages and does not publish a dataset. None of them ship the failed log, the passing run, a model cache, and a rule that replay stops when the cache misses.

## What that led to

Leave the public logs as the ordering corpus. Record a new, smaller corpus with a script. Take the questions and answer keys from the pinned snapshots. Call the model once on a clean run and save that reply. Plant the bug in a later deterministic step, and record the failure by replaying the saved reply so the model text cannot change between the two runs. Gold is the smallest set of nodes whose restoration makes the answer key match, computed by the same fork the product uses. One separate case must abstain, because fixing only one of two prompt changes needs a reply that was never saved.

A person writes the team once and reads the 30 pilot transcripts. The script builds the cases. The design below is the version that survived three passes against the replay code. The first two passes removed a second live model call, a check that was not the product's `equals`, and an abstain case that could not abstain because a node is restored all at once.

## What this plan is for

This plan adds that second corpus. It does not edit `docs/eval/public_traces/cases.jsonl.gz`. The ordering study and the 86-case table stay as they are.

A headline case has:

1. One passing run of that question.
2. One failed run of that same question, whose `solve` text is the same as the passing run.
3. One recorded model reply, from the passing run only.
4. A check that is `equals` against the benchmark answer key.

The flags that were switched on are stored beside gold. They are not gold.

## Claim check, 2026-11-17

| Claim | Verdict | Where |
|---|---|---|
| The current eval is 86 cases on seven fixed inputs, with author-written checks and an echo stub | Holds | `catalog.py`, `vendor_brief.CHECK`, `run_eval.py` |
| More pairs on those seven inputs would close the gap | Does not hold | One `INPUT` per team |
| `Cassette.find` returns the earliest body for a hash | Holds | `cassette.py` `ORDER BY id LIMIT 1` |
| Restore edits a node's context patch, not one flag | Holds | `derive_known_good` assigns every item to a node; `apply_restore` applies that node's whole patch |
| A passing superset whose subset abstained is not a confirmed minimal set | Holds | `search.record` puts it in `unverified`; an empty `minimal` with a cassette miss abstains `unrecorded_call` |
| `equals` does not trim or casefold | Holds | `checks._equals` is `out == str(value)` |

## The team

`bench_solver`. The question is the input.

1. `read` copies the question into state.
2. `bias` is its own deterministic node, in an earlier step than `format`, joined by an ordinary edge. Not a parallel edge: ancestry pruning would drop it. Its flag is named `bias.flag`, so the context patch is owned by `bias` and is not empty. The fault changes a field `format` ignores, so `final_output` stays the key. The write differs from the clean run, so same-output pruning does not drop the node. It does not touch the `solve` request.
3. `steer` is its own deterministic node. It has no headline fault. On headline cases the flag is off and `steer` writes a constant prefix. The prefix must not echo the fault list. If it did, an `extract` flag would change the `solve` hash and the headline drop rule would reject a good case. `steer` exists so the abstain case has a node that can change the `solve` message.
4. `solve` makes one model call. The request body is the question plus whatever `steer` wrote. Headline cases do not change it.
5. `extract` pulls a short answer from the reply. Headline faults live here. Each one must change `final_output`.
6. `format` writes `final_output` as that short answer and nothing else. Headline faults live here too. A fault that only removes a `####` marker is not a fault, because `equals` never sees the marker.

The check is one `equals` assertion. The loader normalizes the key first (trim, text after the last `####` when present, casefold a one-letter answer). That string is the assertion value. `format` on the clean path writes that same string or the case fails. A `final_output` that merely contains the key fails `equals`. The fixture includes one.

## Where the questions come from

Pinned snapshots only: AEGIS `b936269a`, Who&When Pro text `0bd196c8`. Who&When `task` is parsed as JSON. `cases.jsonl` is not a source.

Eligible when the normalized key is non-empty and at most 32 characters, the key is not a substring of the question, and the benchmark is not `alfworld`, `livecodebench_pro`, HumanEval, or BigCodeBench. Those last two names are matched case-insensitively, including an AEGIS id prefix.

Before any model call, each Who&When `benchmark` and each AEGIS id prefix is capped at 50 eligible rows.

## How a headline case is recorded

`solve` is called live once, on `faults=[]`. That reply is the cassette. The model stops.

The failed run is recorded under replay, network down, with the headline flags on. Those flags sit on `extract`, `format`, or `bias`. They do not change the `solve` request, so the cassette hits and the failed checkpoint holds the same `solve` text. If the two `solve` writes differ, the case is dropped.

Gold is every inclusion-minimal set of nodes whose fork makes `equals` pass. The fork is `plan_fork` and `apply_restore`. The cassette serves `solve`. The network stays down. A proper subset that cannot be tested keeps the larger set out of gold.

The product search is run as a regression: it must report those sets. That match is not a finding. After same-output pruning, a headline case has a handful of candidates and `max_size` is 3, so a finished search and a finished brute-force pass over the same fork return the same sets whenever a larger restore cannot spoil a pass. The result that is reported is the fork's sets against the external key.

The pre-registered set is the answer-flipping nodes only (`extract`, `format`, or both). `bias` is stored beside that set and is not a member of it. Gold must equal the pre-registered set, every proper subset must fail, and `bias` must be in no gold set. One case that breaks any of those fails the pilot. A decoy flag on `extract` would be restored whenever `extract` is restored, so it could not be absent from gold.

## The abstain case

One case, not one of the 30.

Two nodes, `steer` and a second request node `preface`, both change the bytes inside the `solve` message. Same question, so `run_input` matches and the passing run is still a legal source. The failed run is recorded live, because its request hash is not on the clean tape and replay would refuse it. It is exempt from the "solve writes must match" drop. The single-flag requests are never recorded.

The live failed run must fail `equals` while the question at `__start__` is unchanged. A byte change the model ignores comes back `already_passes`, and the search never runs.

Diagnosis then restores nodes, not flags. Restoring only `steer` posts a message that is on neither tape. Restoring only `preface` does the same. Restoring both posts the clean message, which is on the tape, so that pair passes `equals`, but `search.record` will not confirm it: a passing set whose subset abstained is `unverified`, `minimal` stays empty, and the verdict is abstain `unrecorded_call`. The pilot fails unless all of these hold: `minimal_sets` is empty, `unverified_sets` is exactly `{steer, preface}`, the pair trial passed, and each singleton has `cassette_miss`. A total miss, with `unverified_sets` empty, is the same reason code and is not this result. There is no gold set.

A flag that changes the question is not this case. That is a different input, and the source is rejected before any cassette lookup.

## When to stop

At most 90 clean recordings. Keep a question when the clean run passes `equals` and the replayed faulty run fails it. The larger run starts only when 30 were kept and every rule below passed. Fewer than 30 kept at 90 attempts means the plan failed.

Also a failure:

- Any headline case abstains, or replay opens a non-loopback socket.
- Gold is not exactly the pre-registered set, or some proper subset also passes.
- `bias` appears in any gold set.
- The normalized key is a substring of the `solve` request messages. That drops the case. It does not fail the pilot. The reply is not scanned: a correct reply contains the key, and scanning it would reject every clean hit. The raw HTTP body is not scanned either: a digit in the model name would drop a short key the question filter had already allowed.
- A read of all 30 clean transcripts shows `final_output` matching the key while `solve` is answering something else.

If the pilot passes, continue to 200 kept headline cases or the end of the capped pool. Report the kept count. Two hundred is a cap.

## What a person does

Write `bench_solver` once. Read all 30 pilot transcripts for a reply that states a different answer and still extracts the key. Do not type a known-good line. Do not choose gold.

## What the result may say

On these questions, with this graph and one recorded reply, the forks name a minimal set that flips the benchmark key, the decoy is outside that set, and the two-node request case abstains because the cross-combination was never recorded.

It may not say that a public trajectory was diagnosed, that those logs now contain known-good answers, that the search beat exhaustive replay, or that an ordering model was shown to be necessary.

## Order of work

1. Loader, normalizer, fixture. One output contains the key and must fail `equals`. No model.
2. `bench_solver` on a reply the test supplies. No network. A headline fault that leaves `final_output` unchanged fails the test. `bias` alone leaves it unchanged.
3. Driver. One live clean call. Headline failures and gold under replay. One cassette per case. Socket trap on.
4. The one abstain case, recorded live, scored only as `unrecorded_call`.
5. Pilot of 30. Stop rules. Only then continue toward 200.

## Not in this plan

- Editing the converted public rows.
- A second live `solve` on a headline failure.
- Recording the single-flag requests so the abstain case becomes a hit.
- Putting both request flags on one node.
- Putting the decoy on `extract` or `format`.
- Calling a search-versus-exhaustive match a result.
- Diagnosing the AEGIS or Who&When injectors.
- Replacing the 86-case table.
