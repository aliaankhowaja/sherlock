> **Working note (tier 3). Not authoritative.** It may be stale or wrong. Facts come from the code and from docs/eval. Never cite this file in anything submitted to the university.

# Conversion plan: AEGIS and Who&When Pro into Sherlock history

**Status:** phases 1 and 2 are implemented (2026-11-09). The pinned counts below match a full `--check` run. Phase 3, the Laya run, has not been run.

## Overview

Build one offline converter and one scoring script. The converter turns two public failure corpora into the checkpoint history Sherlock already parses. The scoring script then asks whether Laya orders the labelled agents sooner than the orders we already have (random, path, history clues).

The study answers one question: **given only the failed transcript, which ordering reaches the published culprit names sooner?**

It leaves the live debugger alone. There is no graph to resume, no cassette of tool calls, and no passing twin to restore. A lower trial count means the order named the labelled agents earlier. It does not mean those agents are a minimal fix, and it does not mean restoring them would make the task pass.

v1 reads two files from AEGIS (the published test split and the training val split) and the text split of the Who&When Pro mirror. The AEGIS training split is the same shape and can be added later with the same script.

## Specification

There is no Notion page for this work. The sources are:

- AEGIS, Hugging Face `Fancylalala/AEGIS`, snapshot `b936269a5143e4450242d8628bff026bdc5bae18`. Files: `Aegis-Bench/test.jsonl` (600 rows), `Aegis-Training/val.jsonl` (1,787 rows).
- Who&When Pro text mirror, Hugging Face `Leoxx/whowhen_pro`, snapshot `0bd196c8a040841c4ae167ab33cc8151de246f1f`. File: `data/text.jsonl` (6,257 rows). The official `tmpxv7/who-when-pro` tarball is not required for v1.
- Sherlock’s reader: `crates/app-core/src/ingestion.rs` (`parse_run_logs`) and the history walkers in `python/sherlock/src/sherlock/` (`search.py`, `g1.py`, `clues.py`, `evaluation.py`, `eval/g1_eval.py`).

## What each corpus is

Both files are JSONL. One line is one failed multi-agent run plus a published label naming who was injected or who made the mistake.

**AEGIS.** Each row has `id`, `metadata` (framework, model, and a `num_agents` field that is not the speaker count), `input.conversation_history`, and `ground_truth`. Every turn is flat: `step`, `agent_name`, `content`, `phase`. The label is `ground_truth.injected_agents[]`, and each entry is an object whose `agent_name` is the node. `correct_answer` is the reference solution, often a GSM-style writeup ending in `#### 420`. Dylan and smoagents set `num_agents` to 1 while the transcript still has several speakers (Assistant1–4, or Manager and Searcher). The converter counts speakers itself and ignores `num_agents`.

**Who&When Pro text.** Each row has `id`, `framework`, `benchmark`, `task`, `trajectory`, and `ground_truth`. `trajectory` is a list, and the list is not one shape. A user turn opens the task. Agent turns carry the message in `output` while `content` is often null. Debate and DyLAN wrap the speakers inside `turns[]` on a round object. A closing object with `kind: "final_answer"` holds a short string such as `"D"` and has no speaker. The label is `ground_truth.agents` (a list) when that key is present, otherwise `ground_truth.agent` (one string). Single-agent families in this file (`smolagents`, `alfagent`) have `agent: null` and one speaker; the filter below drops them.

## What Sherlock reads

Sherlock’s history is a JSON array of checkpoints, **newest first**. The ingestion parser (`parse_run_logs`) keeps a checkpoint when it has `tasks[].name` and uses `tasks[].result` as what that node wrote. A checkpoint with an empty `tasks` array produces no event. Python then reverses the array, so the oldest turn is replayed first (`search._supersteps`).

Two different readers look at two different places:

| Reader | Where it looks | What we put there |
|---|---|---|
| The check, and the text G1 is told is the final output | `history[0].values.final_output` | The answer string |
| “Who wrote the answer?” (`evaluation._writer`, extractive clues) | the key `final_output` inside some `tasks[].result` | The same answer string, on the last agent only |
| A node’s own utterance on its card (`OUT_FAILED`) | `tasks[].result` | `text` holds the utterance |
| What the node could see (`IN_FAILED`) | `values` on the checkpoint that node started from | the question and earlier utterances |

`final_output` on an earlier turn makes Sherlock treat that earlier speaker as the writer of the answer. `final_output` missing from every task makes the extractive clue disappear, so the history-clue order has nothing to rank. The two copies of the answer string are the same string.

## The record we write

One JSON object per kept trace:

```json
{
  "id": "GSM8K_gpt-4o-mini_agentverse_1_2433222f",
  "source": "aegis",
  "framework": "agentverse",
  "gold": [["Evaluator", "RoleAssigner", "Solver"]],
  "reference": "420",
  "label_step": null,
  "tags": [],
  "history": []
}
```

`gold` is a list of lists. `g1_eval.Oracle` does `frozenset(p) for p in planted`. A flat list of names is iterated character by character. One inner list is one labelled set. The inner list is never empty.

`reference` is the short string the equals-check uses. For AEGIS, if `correct_answer` contains `####`, this is the text after the last `####`. Otherwise it is the whole `correct_answer`. Who&When’s text file has no reference solution, so `reference` is null and the row has no equals-check.

`label_step` copies `step`, `round`, or `position` from the source label and is stored for later. v1 never scores it. Who&When’s MacNet `position` is that agent’s own index, not the raw turn index, so a turn-index score would miss the labelled step.

`framework` stays the source’s own string. AEGIS `llm_debate` and Who&When `debate` stay different rows. The same for `magentic_one` and `magentic-one`.

`tags` includes `two_role` for Who&When mathchat. Those 920 rows stay in the file and stay out of every headline number.

### History, newest first

Illustration for two speakers, Solver then Evaluator, whose last utterance is the answer. This is the shape, not a real row.

```json
[
  {
    "checkpoint": {"checkpoint_id": "end"},
    "metadata": {"step": 2, "run_id": "<id>"},
    "values": {"query": "the question", "final_output": "420"},
    "next": [],
    "tasks": []
  },
  {
    "checkpoint": {"checkpoint_id": "s2"},
    "metadata": {"step": 2, "run_id": "<id>"},
    "values": {"query": "the question", "prior": ["Solver's utterance"]},
    "next": ["Evaluator"],
    "tasks": [
      {"name": "Evaluator", "result": {"text": "Evaluator's utterance", "final_output": "420"}}
    ]
  },
  {
    "checkpoint": {"checkpoint_id": "s1"},
    "metadata": {"step": 1, "run_id": "<id>"},
    "values": {"query": "the question", "prior": []},
    "next": ["Solver"],
    "tasks": [
      {"name": "Solver", "result": {"text": "Solver's utterance"}}
    ]
  }
]
```

Rules that hold for every record:

1. `history[0]` is the terminal snapshot. `tasks` is empty. `values.final_output` is the answer string. `metadata.step` is the number of agent turns that were kept.
2. Each older snapshot is one agent turn, still newest first. After reversing, the names run in conversation order.
3. Every agent result has `text` (the utterance). Exactly one result also has `final_output`, and it is the chronologically last agent. That string equals `history[0].values.final_output`.
4. When the source has a speakerless `final_answer` (Who&When: 1,859 of the kept rows, and on 1,517 of them that string differs from the last utterance), the answer string is the `final_answer`. The last agent’s utterance stays in `result.text` only.
5. When there is no speakerless final answer, the answer string is the last agent’s utterance, so `text` and `final_output` match on that one result.
6. `values` on an agent snapshot holds `query` and `prior` (utterances from earlier turns). It does not hold the reference answer.
7. An agent snapshot has `next: [name]`, the node that ran there. The terminal snapshot has `next: []`. `parse_run_logs` does not read `next`. The debugger's fork planner does, and without it every trial says the node did not run.
8. These keys never appear inside `result` or `values`: `is_injected`, `is_replayed`, `injection_via`, `phase`, `error_type`, `injection_strategy`, `malicious_action_description`, and any list of culprit names. They are labels. A node card prints `result` and `values`, so a leftover label would be visible to the ranker.

## How a source field becomes a Sherlock field

### AEGIS

| Source | Sherlock |
|---|---|
| `input.conversation_history[].agent_name` | `tasks[].name` |
| `content` | `result.text` |
| last kept utterance, or nothing else | `result.final_output` on that last turn, and `values.final_output` on the terminal snapshot |
| `ground_truth.injected_agents[].agent_name`, unique, in order | the single inner list of `gold` |
| text after `####`, else `correct_answer` | `reference` |
| `metadata.framework` | `framework` |
| `metadata.num_agents` | ignored |

Turns whose name is `User`, `System`, `user`, or `human` are not nodes. smoagents then keeps Manager and Searcher.

### Who&When Pro text

Walk `trajectory` from start to end. Skip `kind: "user"` (its text is `query`). On `kind: "final_answer"`, save the text as the answer string and do not create a node. On `kind: "round"`, or any object that has `turns`, emit the inner turns in order. Any other object with a speaker is one node.

| Framework | Node name | Message |
|---|---|---|
| `magentic-one` | `agent` (lowercase: `coder`, `orchestrator`). The display `role` (`Coder`) does not match the label. | `output` when `content` is null |
| `macnet`, `metagpt`, `mathchat` | `agent_id` | `output` when `content` is null |
| `debate`, `dylan` | `agent_id` inside `turns[]` | `output` when `content` is null |

MacNet’s label talks about `node_0` and `node_1`. In the transcript `node_1` is both the critic and the rewriter. The converter keeps one node called `node_1`, which is what the label means.

Gold is `ground_truth.agents` when that list is non-empty. Otherwise it is `[ground_truth.agent]` when that string is non-empty. Otherwise the row is dropped.

`label_step` stores `{step, round, position, stage}` from the ground truth, whichever keys exist.

mathchat’s nodes are `user_proxy` and `assistant`, and the label is `assistant` on every row. Tag `two_role`.

## Rows the converter drops

Drop a trace when any of these is true, after the name mapping above:

- fewer than two distinct node names remain
- `gold` is empty, or any gold name is not one of those nodes
- the answer string is empty
- `reference` is present and equals the answer string (the transcript already matches the check)

Measured on the pinned snapshots:

| Slice | Rows in file | Kept | Why the rest go |
|---|---:|---:|---|
| AEGIS test | 600 | 591 | 9 `magentic_one` rows left with one node after dropping User/System |
| AEGIS val | 1,787 | 1,773 | 9 `magentic_one` the same way, 4 `llm_debate` and 1 `macnet` with an empty last utterance |
| AEGIS together | 2,387 | **2,364** | test and val ids do not overlap |
| Who&When text | 6,257 | **2,668** | `smolagents` 3,276 and `alfagent` 311 have one speaker and a null culprit; 2 `magentic-one` rows have one speaker |
| of which mathchat (`two_role`) | | 920 | kept in the file, left out of headline numbers |
| Who&When in the headline | | **1,748** | magentic-one 809, debate 445, macnet 261, dylan 152, metagpt 81 |

AEGIS kept by framework: test macnet 156, agentverse 143, llm_debate 140, dylan 85, smoagents 48, magentic_one 19. Val agentverse 485, macnet 453, llm_debate 444, dylan 284, smoagents 73, magentic_one 34.

AEGIS gold-set sizes across the 2,364 kept rows: one name 432, two names 885, three names 855, four names 192. Who&When’s 2,668 kept rows: one name 2,462, two names 206.

Headline volume for the ordering study is 2,364 + 1,748 = **4,112** traces, plus 920 mathchat rows reported on their own page with no rank number.

## How the scoring script reads a record

`python/sherlock/eval/public_g1.py` (to be written) builds the case dict that `g1_eval` already understands: candidates, on-path order, cards, masked cards, clue weights. Cards come from `node_card(..., good_history=None)`, so `output_same_as_good` and `input_same_as_good` are `unknown` and there is no DIFF line. Clue weights come from `history_clues` on the failed history only. That is enough for the extractive clue, because the last agent’s result carries `final_output`.

It calls `g1_eval.first_fix` and `g1_eval.metrics`. It does not call `evaluation.score`. It does not print `minimal_sets`.

For each method it reports, per row and then as a mean:

- **rank** of the first labelled name in that order
- **reciprocal rank** (1 / that rank, or 0 when the name is absent)
- **recall@3** and **ndcg@3** over the set of labelled names
- **trials_to_label**: the trial number `first_fix` returns when the planted set is `gold`

`trials_to_label` uses `Oracle(gold)`. The search passes once the restored set contains every name in that inner list. On a three-name label the search must cover all three. The same row is scored the same way for every method, so methods can be compared with each other. The column name is `trials_to_label` in the written report.

Methods in the headline table: `random`, `path` (conversation order, one entry per node), `g0` (history-clue weights, then path order), `laya`, `laya_masked`. The `rule` order from `g1_eval` looks for `output_same_as_good=no`, which these cards never say, so it is not a column.

`two_role` rows are written to an appendix that lists how many there are and what the two node names are. That appendix has no rank, no reciprocal rank, no ndcg, and no trial count, and those rows are absent from every mean.

A second small table scores `g0_only`, which names one node:

- when the label has one name: the share of rows where that node is the label
- when the label has several names: the share of rows where the named node sits inside the label, and the mean Jaccard of the two sets

Words the report uses: rank, reciprocal rank, recall@3, ndcg@3, trials_to_label, name in label, Jaccard. The report’s opening paragraph says this is an ordering comparison against the published label.

## Technical approach

Two Python scripts under `python/sherlock/eval/`, plus one Python test. The parser is unchanged. `fetch_run_logs_reads_converted_public_traces` in `crates/app-core/src/ingestion.rs` reads the five converted histories through `parse_run_logs` and checks that each agent turn becomes one event. The scoring path uses the Python history walkers directly, because G1 cards are computed in Python from the history array.

The bulk JSONL stays out of git (it is hundreds of megabytes and is already in the Hugging Face cache). Git tracks a five-row fixture and the counts this plan records. The generated case file for a full run lives under `docs/eval/public_traces/` and is gitignored until a run is actually reviewed.

Suggested layout, created when implementation starts:

- `python/sherlock/eval/convert_public_traces.py` reads the three pinned JSONL files and writes `cases.jsonl`
- `python/sherlock/eval/public_g1.py` reads `cases.jsonl` and writes a markdown table
- `python/sherlock/tests/fixtures/public_traces/` five hand-checked rows: one AEGIS agentverse, one AEGIS smoagents (User/System dropped), one Who&When debate (nested turns plus a `final_answer` that differs from the last utterance), one MacNet (node_1 used twice), one mathchat tagged `two_role`
- `python/sherlock/tests/test_public_traces.py` locks the seven invariants below

Invariants the fixture test asserts on every converted row:

1. The history is a JSON array. Every agent snapshot has `tasks[].name` and a dict `tasks[].result`. The terminal snapshot has `tasks: []` and a string `values.final_output`.
2. Reversing the history and reading task names reproduces conversation order.
3. The key `final_output` occurs in exactly one task result, on the last agent, and that string equals `history[0].values.final_output`.
4. Result and values contain none of the label keys listed above.
5. `gold` is a list of one non-empty list, and every name in it occurs as a task name.
6. At least two distinct task names remain, and none of them is User, System, user, or human.
7. A mathchat row has tag `two_role`. A debate row’s gold names come from `agents`, not from a round object.

## Phases

### 1. Fixture and converter

- [x] Download nothing new if the pinned snapshots are already under the Hugging Face cache. Otherwise fetch those three files at those revisions. The three pinned files were already in the cache.
- [x] Commit the five-row fixture and `test_public_traces.py` first, with the converter reading the fixture.
- [x] Implement the AEGIS walk and the Who&When walk as two functions that return the record above.
- [x] Run the converter on the full pinned files and check the kept counts against the table in this plan. A mismatch stops the run. `--check` matched on 2026-11-09.

### 2. Scoring script

- [x] Build cards with `good_history=None` and clue weights from `history_clues`.
- [x] Call `first_fix` and `metrics`. Write `trials_to_label`, rank, reciprocal rank, recall@3, ndcg@3 for the five methods.
- [x] Split `two_role` into the appendix before any mean is computed.
- [x] Add the `g0_only` table with the one-name and many-name rows kept separate.
- [x] Open the markdown with the sentence that this compares orders against the published label.

### 3. A real run, later

- [ ] Run `public_g1.py` with the local Laya backend the existing G1 eval already uses (`LOCAL=true`).
- [ ] Write the table under `docs/eval/public_traces/` and read it as an ordering result beside the existing harness numbers in `docs/eval/g1`. The two numbers answer different questions and stay in different files.

## Dependencies

- The pinned JSONL files on disk.
- The current Python package: `node_card`, `history_clues`, `g1_eval.Oracle`, `first_fix`, `metrics`, `g0_only`. No change to their signatures.
- A Laya checkpoint only for phase 3. Phases 1 and 2 are testable with the fake backend `g1_eval` already has.
- No LangGraph server, no cassette, and no known-good run.

## Risks

| Risk | What we do |
|---|---|
| Putting `final_output` on every turn makes the last speaker the only writer, and makes every earlier speaker look like they wrote the answer too | The key sits on the last agent’s result and on the terminal `values`, and those two strings are equal. The fixture test counts the key. |
| A speakerless `final_answer` of `"D"` graded one way, and the long last utterance graded another | Both the check and the extractive clue read the same string: the `final_answer` when it exists. The utterance stays under `text`. 1,517 kept Who&When rows are in this situation. |
| `Oracle` on a flat list of names turns the names into characters | `gold` is always `[[...]]`. The test builds an `Oracle` from a fixture row and checks the planted set is the node names. |
| An empty gold set makes every restore look successful, because the empty set is a subset of everything | Empty gold is dropped before a record is written. |
| Scoring the oracle’s own `minimal_sets` with `evaluation.score` is true by construction | The script never calls `evaluation.score` and never prints those sets. |
| A trial budget that eventually covers every label makes a “solved” rate look like 100% | The report publishes relative order metrics and `trials_to_label`. It publishes no solved-rate column. |
| mathchat’s label is the generic name `assistant` | Those rows are tagged `two_role` and carry no rank in any aggregate. |
| `g0_only` names one node, while many AEGIS labels name two to four | One-name labels get a match rate. Multi-name labels get “name in label” and Jaccard. |
| MacNet `node_1` is critic and rewriter | One node, matching the label. The plan records the collapse so a later reader does not split them. |
| `metadata.num_agents == 1` on Dylan and smoagents | Ignored. Speakers are counted after the drop list. Both families stay in the kept set. |
| Cards include the short reference (`CHECK: equals 420`) | That is the same text a real equals-check puts on a card. The worked solution before `####`, and the culprit names, stay off the card. |
| Short answers such as `"D"` often contain no token that is missing upstream, so the history-clue order collapses to path order | Expected. The path column and the g0 column will match on those rows, and the table shows that. |
| Someone treats a good `trials_to_label` as evidence the debugger can replay these logs | The report’s first paragraph states the limit, and this plan’s overview states it. Phase 3 does not call `sherlock-rec diagnose`. |

## Review

The plan was attacked in three rounds before it was written down. Each round read the Sherlock code and, where the claim was about the files, the pinned JSONL.

1. Mapping, scoring, and the pipeline, in parallel. This closed `final_output` on every turn, empty `values`, folding a speakerless answer onto an agent node, dropping Dylan because `num_agents` is 1, a contains-check that passes rows the equals-check would keep, reading Who&When `content` when the text is in `output`, treating debate gold as a single `agent`, and calling `evaluation.score` on the oracle’s own sets.
2. The revised mapping and the revised scoring, in parallel. This closed a clue-starved history by putting `final_output` on the last task result as well as on `values`. Scoring was renamed to `trials_to_label`, multi-name `g0_only` was kept off a binary headline, empty gold was dropped, mathchat was pulled out of every mean, and solved-rate columns were removed.
3. The locked plan above. One remaining hole: when `final_answer` differs from the last utterance, the terminal `values.final_output` and the last task’s `result.final_output` were allowed to be different strings. They are now the same string. Prior texts live in `values.prior`; extractive clues read task results, so those priors do not hide the answer from the clue.

Residual, accepted: on a short multiple-choice `final_answer`, g0 often has no extractive token and follows path order. The table is supposed to show that.
