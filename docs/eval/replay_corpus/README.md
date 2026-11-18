# Replay corpus: how it was generated

A test set for Sherlock's restore claim on questions from outside this repository. Each case is one benchmark
question run through a small LangGraph team twice, a passing run and a failed run, with the one model reply both
runs share saved on tape and the benchmark's own answer key as the check. Design: [`../../notes/replay-corpus-plan.md`](../../notes/replay-corpus-plan.md).
Code: branch `replay-corpus`, files listed under [Code](#code).

**Status: not yet for use.** The plan requires a person to read the 30 pilot transcripts before the corpus is used
or published. That read has not happened (`more.json` says `"transcripts_read": false`).

## Why a new corpus

Sherlock takes a failed run and a passing run of the same task, restores one node's known-good behaviour at a time
offline, and reports the smallest set of nodes whose restore makes the task pass, or abstains when a replay would
need a model call that was never recorded. Testing that needs, per case: a failed run, a passing run, the saved
model reply, and an external answer key. The public AEGIS and Who&When Pro traces have the failed transcript and a
blame label but no passing run and no saved replies, so they support ordering claims only. The 86 planted cases
have all four parts but run on our own teams with an echo stub. This corpus takes only the questions and answer
keys from the public datasets and produces the passing run, the failed run and the saved reply itself.

## Questions and answer keys

- **Sources (pinned):** AEGIS `Fancylalala/AEGIS` revision `b936269a5143e4450242d8628bff026bdc5bae18`
  (`Aegis-Bench/test.jsonl`, `Aegis-Training/val.jsonl`; key = `ground_truth.correct_answer`), and Who&When Pro
  `Leoxx/whowhen_pro` revision `0bd196c8a040841c4ae167ab33cc8151de246f1f` (`data/text.jsonl`; `task` parsed as JSON,
  key = `task.answer`). Licences: MIT and CC-BY-4.0.
- **Benchmarks kept:** those one model call can answer from the question text alone: AEGIS `GSM8K`, `MATH`,
  `SciBench`; Who&When Pro `math`, `scibench`, `simpleqa_verified`. Excluded: benchmarks that need files, tools or
  the web (GAIA, tablebench, dsqa, databench, dabench, dacode, kramabench), code benchmarks, ALFWorld, and
  multiple-choice benchmarks (their option letter always appears in the question, which the key-in-question rule
  forbids).
- **Answer normalisation** (`tidy()`, one rule for the key and for the model's answer): text after the last `####`;
  trimmed; a `, the unit is …` suffix, dollar signs, markdown stars and a `\boxed{}` wrapper removed; one trailing
  full stop and digit-grouping commas dropped; a single letter casefolded.
- **Eligibility:** normalised key non-empty, at most 32 characters, not a substring of the question (ignoring case); each question
  text used once.
- **Pool:** at most 50 eligible questions per benchmark (file order), then shuffled with seed `20261117`: 300 questions.

## The team (`bench_solver`)

`read → bias → preface → steer → solve → extract → format`, one plain edge each. Only `solve` calls the model; every
other node is plain code. The request is the instruction below followed by the question:

> Solve the problem below. End your reply with one line of the form '#### <answer>', where <answer> is only the final
> short answer, with no units, no thousands separators and no extra words.

Faults are switched on per run through the run context and named `<node>.<flag>`:

| Fault | Node | Effect | Role |
|---|---|---|---|
| `extract.drop_last` | extract | drops the last character of the answer | headline (always flips the output) |
| `format.prefix` | format | writes `Answer: ` before the answer | headline (always flips the output) |
| `bias.flag` | bias | changes a field no node reads | decoy, on in every headline case |
| `steer.flag`, `preface.flag` | steer, preface | change the model request | the abstain case only |

Headline cases cycle by attempt number through `{extract}`, `{format}`, `{extract, format}`, always with the decoy.

## Model

Qwen3.8 27B, GGUF Q8_0 (Ollama tag `qwen3.8:27b-mtp-q8_0`, sha256
`2bb22714289826d7b9e0ba376c3ce47d08bce39abe598745857c44d88c09bdbf`, Apache-2.0), served by the llama.cpp server
(build `b1-161755f29`) through its OpenAI-compatible `/v1/chat/completions`, with an Ollama-equivalent chat template
(sha256 `1f7e35d72a13485b907f2a603c837fc324fa9dd268639e7163c73054f89bc226`).

| Setting | Value |
|---|---|
| Reasoning effort | `xhigh` (`chat_template_kwargs.reasoning_effort`; the model's maximum) |
| Output cap | `max_tokens` 120000, inside the server's 131072-token per-request context |
| Sampling | server defaults: temperature 1.0, top_k 20, top_p 0.95, min_p 0.05, random seed |
| Decoding | speculative decoding with the model's MTP draft head (speed only) |
| Hardware | 2 × NVIDIA RTX PRO 4000 Blackwell (24 GB), model split across both |

Each headline question was sent to the model once; the abstain case records its own passing and failed runs live.
Because sampling is random, re-sending a question would give a different reply; the recorded reply, not the model,
is the artifact. The exact settings are also saved beside the
data in `model_manifest.json`.

## Procedure per question

1. **Passing run (live).** `sherlock-rec run langgraph dev` records the team with no faults. `solve` is the only
   network call; its full request and reply (including the model's reasoning) are saved to the case's cassette. The
   question is kept only if `final_output` passes an `equals` check against the normalised key.
2. **Failed run (replayed).** The server restarts in replay mode inside a socket trap that refuses every
   non-loopback connection and the model's port. The failed run (headline faults plus the decoy) is recorded there,
   so its `solve` reply is served from the cassette and is byte-identical to the passing run's.
3. **Drop rules.** A case is dropped if the key appears in the model request, or if the two runs' `solve` writes
   differ. It is not kept if the failed run still passes `equals`.
4. **Gold.** Every non-empty set of the nodes the passing run gives a context patch to is forked once with the
   product's own fork (`plan_fork` + `apply_restore`, via `run_g3`), served from the cassette. Gold is every
   inclusion-minimal passing set with no untestable proper subset.
5. **Rules (a failure stops the run).** Gold must equal the pre-registered set (the nodes of the headline faults);
   every proper subset of it must fail; the decoy must be in no gold set; no fork may abstain; replay may open no
   non-loopback socket; and the product search (`diagnose`, budget max size 3) must report exactly the gold sets.
   That last match is a regression check, not a finding.

**Abstain case (one, separate from the headline cases).** On the first kept question with a numeric key, both
request faults are switched on and the failed run is recorded live, so its request is on tape but neither
single-fault request is. It passes only if the product search ends `unrecorded_call` with no minimal set, exactly
`{preface, steer}` unverified, the pair trial passing, and each single restore a cassette miss.

**Stages.** Pilot: attempts in pool order until 30 are kept (at most 90 attempts), then the abstain case; every rule
must hold. Full run: on to 200 kept or the end of the pool.

## Results (run of 2026-11-17/18)

Pilot: 30 kept in 47 attempts, every rule held. Full run: the whole pool.

| Benchmark | Attempted | Kept |
|---|---|---|
| AEGIS GSM8K | 50 | 50 |
| AEGIS MATH | 50 | 44 |
| AEGIS SciBench | 50 | 30 |
| Who&When Pro math | 50 | 36 |
| Who&When Pro scibench | 50 | 21 |
| Who&When Pro simpleqa_verified | 50 | 4 |
| **Total** | **300** | **185** |

- Every kept case met every rule: gold equalled the pre-registered set, the decoy was never in gold, and the product
  search reported the same sets. 0 dropped, 0 rule failures.
- The abstain case (`math_debate_0039`) ended `unrecorded_call` with `{preface, steer}` unverified, as required.
- All 115 unkept questions failed the passing-run `equals` check; none stopped at the output cap. Some are wrong
  answers (most simpleqa); some are right but differently rounded or written (key `6.6`, reply `6.594`; key `x=5`,
  reply `5`). Both kinds are left out, never kept with a wrong label.
- Wall time on the hardware above: about 9 hours for the 300 questions (median under 2 minutes per question; the
  hardest maths questions about 15 minutes, up to 35k output tokens).

**What the result may say** (from the plan): on these questions, with this graph and one recorded reply, the forks
name a minimal set that flips the benchmark key, the decoy is outside that set, and the two-node request case
abstains because the cross-combination was never recorded. It may not say that a public trajectory was diagnosed,
that the public logs now contain known-good answers, that the search beat exhaustive replay, or that an ordering
model was shown to be necessary.

## Changes from the plan

1. One shared answer rule (`tidy()`) instead of trim/`####`/casefold only; the plan's rule rejected correct answers
   whose keys carry a unit suffix or a dollar sign.
2. An allowlist of self-contained benchmarks instead of the plan's four-name blocklist, which kept benchmarks that
   need files or the web.
3. The model ran at its full reasoning effort with an output cap near its context limit; at a lower effort and an
   8k cap, hard maths questions stopped mid-reasoning with no answer.
4. The full run was allowed to start before the transcript read; the read now gates any use of the data instead.

Open: whether to drop `simpleqa_verified`, and whether to accept numbers equal to the key's precision. Every
recording is kept, unkept ones included, so a looser check can be applied later offline without new model calls.

## Reproduce

Needs: the pinned snapshots in the Hugging Face hub cache (`HF_HUB_CACHE` may point elsewhere), `uv`, and an
OpenAI-compatible endpoint serving the model.

```sh
cd python/sherlock
export BENCH_URL=http://<host>:<port>/v1 BENCH_MODEL=qwen
export BENCH_EXTRA='{"max_tokens": 120000, "chat_template_kwargs": {"reasoning_effort": "xhigh"}}'
uv run python eval/replay_corpus.py pilot && uv run python eval/replay_corpus.py more
```

`pilot` exits 0 only when every rule held, so `more` starts only after a passing pilot. Both stages resume from
`attempts.jsonl` after an interruption. Once a person has read the pilot transcripts, `more --transcripts-read`
records that. A new run produces new replies (random sampling), so its kept set will differ; the recorded corpus is
the reference.

## Output

Written to `python/sherlock/eval/.replay_corpus/` (not in git; about 320 MB):

| File | Contents |
|---|---|
| `attempts.jsonl` | one record per question: ids, question, key, faults, outcome and reason, passing-run reply and output, forks, gold, product result |
| `labs/NNN/` | per question: `.sherlock/cassette.db` (the recorded request and full reply), the team file it ran with, the server's run history |
| `abstain.json` | the abstain case's record |
| `pilot.json`, `more.json` | rule results per stage; `transcripts_read` |
| `summary.md` | counts, rules, a table of every attempt |
| `transcripts.md` | question and reply of every kept case (the first 30 are the pilot) |
| `model_manifest.json` | model hash, server build and arguments, chat template hash, sampling, request settings |

## Code

| File | What it does |
|---|---|
| `harness/sherlock_harness/teams/bench_solver.py` | the team: nodes, faults, the model call (`ask`), the answer rule (`tidy`, `short_answer`) |
| `python/sherlock/eval/replay_corpus.py` | the driver: question pool (`questions`, `ineligible`, `pool`), one case (`run_case`), gold (`fork_sets`, `gold_of`), rules (`headline_problems`, `abstain_problems`), stages (`record`, `abstain_case`, `main`) |
| `python/sherlock/src/sherlock/g3.py` | `plan_fork`, `apply_restore`, `run_g3`: one restore-and-rerun trial |
| `python/sherlock/src/sherlock/sources.py` | `derive_known_good`, `assess`: known-good patches from the passing run |
| `python/sherlock/src/sherlock/diagnose.py` | `diagnose`: the product search, run as a regression |
| `python/sherlock/src/sherlock/cassette.py` | the recorded calls and their replay |
| `python/sherlock/eval/convert_public_traces.py` | the pinned snapshot revisions and the readers reused by the driver |
| `harness/tests/test_bench_solver.py`, `python/sherlock/tests/test_replay_corpus.py` | tests, including one full record-and-replay lab against a loopback stub |
