> **Working note (tier 3). Not authoritative.** It may be stale or wrong. Facts come from the code and from docs/eval. Never cite this file in anything submitted to the university.

# Sherlock — build specification

**Status:** internal build document. Derived from the signed proposal
(`../../causal-debugger/causal-agent-debugger.md`, the committee source of truth) plus
decisions and research dated 12 October 2026.

**Audience:** the three of us, building the platform. Not a committee submission.

**What this document does:** turns the problem statement into functional and
non-functional requirements, with enough implementation detail to start work and no
more. Where a detail is not yet settled, it says so rather than inventing one.

**Relationship to other documents**

| Document | Role |
|---|---|
| `causal-debugger/causal-agent-debugger.md` | Committee source of truth. Method, CCP, evaluation, FAST mapping. **Governs.** |
| `causal-debugger/product-experience.md` | Product/UX source of truth. Screens, must-have vs noise. |
| `causal-debugger/debugger-review.md` | Review log. Its "AFTER IDEA APPROVAL" items are now due and are folded in below. |
| `docs/history/Sherlock-Brief.pdf` (9 Oct) | Literature update. Superseded on method. See §3.3. |
| This document | Build plan. FRs, NFRs, architecture. |

---

## 1. Problem statement

In a multi-agent LLM system, several nodes hand work to each other — one plans, one
retrieves, one writes, one checks. When the final answer is wrong, the mistake usually
happened several steps upstream, and every step in between still reports `status: ok`.

Reading the trace does not solve this. On the standard benchmark, the best published
log-reading method identifies the exact failing step **14.2%** of the time. Last-step
blame — the obvious heuristic — scores **12.7%**. Accuracy collapses further on traces
beyond ~90 steps, which is where real agent runs live.

Existing tools record runs. LangSmith, Langfuse, Phoenix, Braintrust, Datadog, and
AgentOps all sell a camera: a tree of spans you click through and interpret yourself.
Some add an LLM that guesses a cause. None of them run the team again to find out.

**The engineer's actual question is not "what happened?" It is "what do I have to
change?"** Those are different questions, and the second one has a mechanical answer
that nobody ships.

### 1.1 What makes this hard

Three constraints pull against each other, and most of the design follows from the
tension between them.

**The test must be faithful.** If you restore one node and then replay everyone
downstream from the recording, you have tested nothing — their recorded output was a
response to a different input. Downstream nodes must genuinely run again.

**The test must be deterministic.** If downstream nodes make live model calls, the
diagnosis is a coin flip: a node that failed last time may succeed this time by
sampling luck, and the engine will blame the wrong node. A non-deterministic diagnosis
is not a diagnosis.

**Faithful and deterministic are in direct conflict** — running again means new inputs,
and new inputs mean calls that were never recorded. Sherlock resolves this by
**abstaining**: when a trial would need a call that is not in the recording, the trial
reports "cannot say" rather than going live or faking it.

Abstention is therefore not a failure mode to minimise. It is the mechanism that makes
every non-abstained answer trustworthy.

### 1.2 Scope of blame

Blame lands on a **checkpoint instance** — one node execution, identified by
`(thread_id, checkpoint_ns, checkpoint_id)`. A node is any unit in the graph:

- an LLM-backed agent,
- a tool call,
- a deterministic function (router, parser, validator, scorer).

A compiled LangGraph may contain cycles, but one failed `invoke` unrolls to a DAG of
checkpoint instances. The UI projects these into readable chips ("Searcher, pass 2/3").

This matters: most real bugs in agent teams live in the deterministic nodes — the
router that picked the wrong branch, the parser that silently dropped a field, the
retriever that returned nothing. Those are also the nodes where replay is exactly
reproducible. See §9.1.

---

## 2. What we are building

A local debugger that, given one failed multi-agent run, names the **smallest set of
nodes** whose restoration makes the failure disappear — including sets of two nodes
that only fix the run together — by running the team again with no live model calls,
and **refuses to name a cause when the test would lie**.

### 2.1 The contribution, precisely

> Restore one (or two) nodes to a known-good behaviour or a known-good output that we
> actually have. Run every node *after* them again, with their failed behaviour still
> in place, so they produce a new answer from what they see this time. Allow no model
> or network call unless that exact call was already recorded under that same
> behaviour. Take as the cause the smallest set of nodes such that the failure dies and
> no proper subset does. If no such set can be tested honestly, abstain.

A week-clone can ship a stub cache and a subset search — that is roughly fifty lines.
The project is **the failure behaviour of the test itself**: catching paste-and-play,
blocking live calls, refusing planted names as gold, and scoring abstention instead of
hiding it.

### 2.2 What this is not

Not a trace viewer, prompt playground, eval platform, annotation queue, cost dashboard,
production-issue clusterer, auto-fix PR bot, or a chatbot that reads the log and
guesses. The viewer is deliberately the least novel part of the product.

---

## 3. Positioning

### 3.1 Against shipping tools

Verified October 2026. **No observability platform can replay a multi-agent workflow
from a mid-point.** Langfuse, Phoenix, Braintrust, Datadog, Opik, and Weave store
traces as append-only records; what they call "replay" is lifting a single LLM call
into a prompt playground. This is architectural, not a gap anyone is about to close: a
trace records what *happened*, while resuming needs channel state, `channel_versions`,
`versions_seen`, pending writes, and reducer semantics — none of which appear in any
trace format, OTel or proprietary.

LangSmith is the apparent exception and is not one. Its "Re-run from here" works
because LangChain also ships the runtime; the fork goes through the **checkpointer**,
not the trace store. Even LangSmith's "clone thread locally" describes history as
*"inferred and copied"*.

The closest competitor is **LangGraph Studio** (`langgraph dev`), which already offers
node inspection, breakpoints, state editing, fork-from-checkpoint, and DAP attach. What
it does not offer is deterministic replay — forking re-runs the LLM, as LangChain's own
docs state plainly. **That gap is the product.**

### 3.2 Against research

| | CAR (2606.08275) | AgenTracer (2509.03312) | GCJR (2608.29228) | **Sherlock** |
|---|---|---|---|---|
| Question asked | How much does re-rolling step *k* move the outcome? | What is the *earliest* step whose correction suffices? | Which minimal message-swap sets make the run pass? | Which minimal **node** sets must be restored? |
| Unit changed | Live re-roll of a step | Oracle-corrected action | One message, overwritten | A node's **behaviour** or output |
| Live calls | Yes | Yes | Yes | **No — cache or abstain** |
| Multi-cause | Shapley credit; one locus | No, single by construction | Yes, bounded at size ≤ 2 | Yes, every 1-minimal set |
| Dependency graph | n/a | n/a | **Assumed given** | **Recovered from checkpoints** |
| Deployable | Research prototype | Research prototype | Research prototype | Installable debugger |

### 3.3 On GCJR specifically

GCJR (arXiv 2608.29228, v1 29 Aug 2026, v2 6 Sep 2026, Li et al.) was published after
our proposal was signed and independently arrives at a formulation close to ours at the
**message level**. Citation and all claims verified against the full text, 12 Oct 2026.

**This confirms the bet rather than killing it.** A separate group reaching the same
formulation is evidence the problem is real and the approach is sound. Four things
remain ours:

1. **No live calls.** GCJR re-runs live. We cache or abstain. This is the whole
   determinism argument in §1.1.
2. **Node behaviour, not messages.** GCJR overwrites one message. We restore a node's
   behaviour, which then recomputes its output — so a downstream node genuinely reacts.
3. **Chained faults.** GCJR abstains on **all 30** of its Sequential-Joint controls —
   two faults on the same causal chain. That is explicitly out of its scope and in
   ours.
4. **The dependency graph.** GCJR assumes it is given. We recover it. See §9.2 — GCJR
   measured exactly how badly this degrades, which is useful to us and is now a
   quantified risk rather than an unknown.

GCJR also bounds its search at size ≤ 2 and describes itself as "deliberately
oracle-assisted", not generating repair messages automatically.

**Correction to the 9 October brief:** it proposed replacing our "no live model calls"
promise with repeated live trials. We are not doing that. That promise is the
contribution, and abandoning it would make the diagnosis non-deterministic for the
reason in §1.1. The brief's durable content is the GCJR citation and the competitor
survey, both folded in above.

**Two citation errors to fix anywhere they appear:** "TraceElephant" is not a paper —
the ACL URL resolves to *"Seeing the Whole Elephant"* (Chen et al., ACL 2026).
AgentAssay is **AGPL-3.0**, not Apache-2.0, which matters if we vendor any of it.

---

## 4. Architecture

```
┌─ user's machine ────────────────────────────────────────────────┐
│                                                                 │
│  $ sherlock run python app.py      ← records a tape             │
│  ┌──────────────────────────────┐                               │
│  │ user's Python process        │                               │
│  │  ┌────────────────────────┐  │                               │
│  │  │ sherlock bootstrap     │  │  sitecustomize → meta_path    │
│  │  │  · httpx transport     │──┼─→ records / intercepts        │
│  │  │  · BaseTool patch      │  │   LLM + tool calls            │
│  │  │  · LC callbacks        │  │   (structure only)            │
│  │  └────────────────────────┘  │                               │
│  │     LangGraph 1.2.x          │                               │
│  └──────────────┬───────────────┘                               │
│                 │ HTTP (fork + resume)                          │
│                 ▼                                               │
│         LangGraph Agent Server                                  │
│                 ▲                                               │
│  ┌──────────────┴───────────────┐                               │
│  │ sherlock engine (Rust)       │   G0–G3, minimality search,   │
│  │  · ingestion                 │   check evaluation, budget    │
│  │  · cassette store            │                               │
│  │  · diagnosis                 │                               │
│  └──────────────┬───────────────┘                               │
│                 │                                               │
│          SQLite (.sherlock/)        local web UI (:3000)        │
└─────────────────────────────────────────────────────────────────┘
```

### 4.1 Distribution

`pip install sherlock`. The user is a Python engineer; a cargo install or a binary
download loses them at minute one, and the interceptor must live in their Python
process regardless.

The Rust engine ships compiled into the wheel via PyO3/maturin. The user types `pip
install`, gets a native binary, and never knows. This preserves the existing Rust work
and the Phoenix-weight install promise simultaneously.

Rust keeps: ingestion, checkpoint diffing, check evaluation, candidate pruning,
minimality search, budget accounting. Python keeps: the bootstrap, the interceptors,
and the LangGraph HTTP client.

**Open:** whether the local web UI is served from Rust (current: axum + rust-embed) or
replaced. Defer — it works today and is not on the critical path.

### 4.2 Recording: zero lines of user code

`sherlock run python app.py` mirrors the `ddtrace-run` pattern:

1. Prepend our bootstrap directory to `PYTHONPATH`, then `execl` the user's command.
2. Python's `site` module imports our `sitecustomize` at interpreter startup.
3. The bootstrap strips its own path from `PYTHONPATH` (prevents double-instrumentation
   in subprocesses), chains to any pre-existing user `sitecustomize`, and installs a
   `sys.meta_path` hook.
4. The hook patches httpx's transport when httpx is first imported — order-independent,
   unlike eager patching.

httpx is the single chokepoint beneath `openai`, `anthropic`, and `litellm`, so this is
independent of LangChain versions.

Three interception layers, each with a distinct job:

| Layer | Records | Intercepts | Covers |
|---|---|---|---|
| httpx transport shim | ✅ | ✅ | all LLM calls, HTTP tools |
| `BaseTool.run` / `arun` patch | ✅ | ✅ | local/non-HTTP tools |
| LangChain callbacks | ✅ | ❌ | graph structure, node boundaries |

**Callbacks cannot intercept.** Every hook in `langchain_core/callbacks/base.py` is
typed `-> Any` and the return value is discarded. Confirmed in source. They are for
recording structure only — never for replay. The same applies to every OpenTelemetry
and OpenInference instrumentor, by specification.

**Rejected mechanisms, with reasons:** `.pth` files (deprecated in Python 3.15);
`PYTHONSTARTUP` (interactive sessions only); `usercustomize` (silently disabled by
`PYTHONNOUSERSITE` or uid mismatch, and machine-global); gateway caches — Helicone,
LiteLLM, Cloudflare — (all fall through to the provider on a miss, so none can
abstain); `set_llm_cache` alone (can abort, but is bypassed by `.stream()`/`.astream()`,
covers no tool calls, and keys on the serialized model repr so it invalidates on every
dependency bump — acceptable as a prototype or a secondary guard, not as the mechanism).

### 4.3 Replay: fork over HTTP

Verified against `langgraph-api` 0.16.0. All four endpoints predate 1.0 and are stable.

1. `POST /threads` with a `supersteps` array → synthesise an isolated thread with
   history rebuilt to the fork point. **Not** `POST /threads/{id}/copy`, which is
   synchronous and blocking with reports of 12+ minutes on large threads.
2. `POST /threads/{id}/history` → locate the snapshot whose `next` contains the target
   node.
3. `POST /threads/{id}/state` with `{values, checkpoint, as_node}` → create the fork;
   capture the returned checkpoint.
4. `POST /threads/{id}/runs/wait` with `input: null` and that checkpoint → resume.

The user's original thread is never modified.

**Sharp edges, all load-bearing:**

- `as_node` resumes at that node's **successors**. To re-run node B with a modified
  input, set `as_node` to B's *predecessor*, not B.
- Reducers append. Sending `{"messages": [m]}` to a `MessagesState` graph appends; it
  does not replace. Overwriting needs the message `id` from the checkpoint, or the
  `{"__overwrite__": [...]}` reducer-bypass form. **Unverified over HTTP** — the source
  implies it works through `update_state` but no doc or test confirms it. Verify
  empirically before relying on it.
- Conditional edges re-evaluate against the new state, so "downstream" means the
  *newly selected* downstream path.
- Message surgery must preserve provider validity — every assistant `tool_calls`
  message needs matching `tool` results, or the resumed run dies inside the model call.
- Parallel super-steps: omitting `as_node` when two nodes wrote raises
  `InvalidUpdateError`.

### 4.4 Behaviour restoration

Two mechanisms, in preference order:

**Interceptor-level (primary).** The bootstrap already sits in front of every model and
tool call. For a trial, it is told "node `writer` uses prompt P" and rewrites the
outbound request. Works on any graph, instrumented or not.

**LangGraph `context` (secondary).** If the graph author declared a `context_schema`
and reads `runtime.context.system_prompt`, we can override per-run via the API with no
interception. `GET /assistants/{id}/schemas` is the capability probe — an empty or null
`context_schema` means this path is unavailable. Note the server returns **HTTP 400**
if both `config.configurable` and `context` are sent in one request; send `context`
only.

Prefer per-run `context` over creating assistants — `PATCH /assistants/{id}` replaces
config wholesale and pollutes the user's version history.

### 4.5 State

SQLite in `.sherlock/`. Holds tapes, cassettes, checks, diagnoses, trials, and verdicts.
Stores pointers to LangGraph thread IDs rather than duplicating run data where
practical, to limit the secrets surface.

---

## 5. Functional requirements

Priority: **M** must, **S** should, **C** could. Status: ✅ done, 🔨 in progress,
⬜ not started.

### 5.1 Recording (FR-R)

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-R1 | Record a LangGraph run with zero edits to user source, via `sherlock run <cmd>` | M | ⬜ |
| FR-R2 | Record every LLM call: full request body, response body, model, params, timing | M | ⬜ |
| FR-R3 | Record every tool call, including non-HTTP local functions | M | ⬜ |
| FR-R4 | Record graph structure: nodes, handoffs, which checkpoint each handoff came from | M | 🔨 |
| FR-R5 | Record SSE/streaming responses as an **ordered chunk sequence**, not one blob | M | ⬜ |
| FR-R6 | Chain to a pre-existing user `sitecustomize` without clobbering it | M | ⬜ |
| FR-R7 | Prompts and tool I/O recorded **on by default** locally (OTel's default hides them) | M | ⬜ |
| FR-R8 | Strip secrets and PII on ingest against a documented deny-list | M | ⬜ |
| FR-R9 | Detect and report when a run has no usable checkpoint history (e.g. `durability="exit"`) | M | ⬜ |
| FR-R10 | Ingest teams, runs, and per-node history from a LangGraph Agent Server | M | ✅ |
| FR-R11 | Import a LangSmith trace for **browsing only**; refuse to diagnose it, with a reason | S | 🔨 |
| FR-R12 | `sherlock doctor` — probe server version, checkpointer presence, `context_schema`, durability | S | ⬜ |

> **FR-R10 defect, fix first.** `crates/app-core/src/ingestion.rs:250` reads
> `metadata.writes` to expand per-node events. That field was **removed from checkpoint
> metadata in langgraph 0.5.x**; current metadata is
> `{source, step, parents, run_id, counters_since_delta_snapshot}`, and
> `langgraph-api` 0.16.0's encryption allowlist confirms no `writes`. Tests pass only
> because fixtures contain it. Against a current server every checkpoint falls to the
> `None` branch and the timeline degrades to "unknown" placeholders. Replacement: diff
> `values` against `parent_checkpoint` and attribute the delta to nodes named in the
> parent's `next`/`tasks[]`. For runs we trigger ourselves, prefer
> `stream_mode: ["updates", "tasks", "checkpoints"]`, which is strictly better data.

### 5.2 Outcome checks — Z (FR-C)

Checks are **promptfoo-compatible YAML**. We parse the same `assert:` objects rather
than inventing a DSL. Rationale: promptfoo is the only format that scores *outputs you
already have* (`--assertions ... --model-outputs ...` and `providerOutput`) with no
provider call — every alternative assumes it owns the model call. It is also already
familiar, version-controllable, and schema-validated.

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-C1 | Load checks from `sherlock.yaml`, auto-discovered; `-c` to override | M | ⬜ |
| FR-C2 | `file://` paths resolve relative to **the config file's directory**, not cwd | M | ⬜ |
| FR-C3 | Deterministic assertions: `equals`, `contains`, `icontains`, `contains-all`, `contains-any`, `regex`, `is-json` | M | ⬜ |
| FR-C4 | `not-` prefix on every assertion type | M | ⬜ |
| FR-C5 | `is-json` accepts an optional JSON Schema, inline or `file://` | M | ⬜ |
| FR-C6 | Per-assertion result `{pass, score, reason}`; `reason` names *which* substring was missing | M | ⬜ |
| FR-C7 | Escape hatch: `python` / `javascript` assertion, inline or `file://` | S | ⬜ |
| FR-C8 | Emit a JSON Schema and the `# yaml-language-server: $schema=` header for editor autocomplete | S | ⬜ |
| FR-C9 | Error clearly on unsupported assertion types: "unsupported assertion type: X" | S | ⬜ |
| FR-C10 | Node-level assertions from checkpoint history: `node-ran`, `node-sequence`, `node-output-contains`, `step-count` | C | ⬜ |
| FR-C11 | `starts-with`, `word-count`, `levenshtein`, `assert-set` with pass threshold | C | ⬜ |

**No LLM-as-judge in v1.** It is non-deterministic, and if Z is LLM-judged we have
rebuilt the weak baseline this field exists to beat. Note that LangSmith's own
"assertions" feature stores free-form English for an LLM to grade — determinism is a
deliberate split from the incumbent, not a gap.

FR-C10 is the differentiator. promptfoo has `trajectory:tool-used` and siblings, but
gates them on OpenTelemetry span data most users never wire up. We have the equivalent
natively from checkpoint history.

### 5.3 Intake — how a run is known to be wrong (FR-I)

The platform **never guesses** that an answer is wrong.

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-I1 | FAIL via expected-vs-actual mismatch | M | ⬜ |
| FR-I2 | FAIL via a check (FR-C) on the final output | M | ⬜ |
| FR-I3 | Intake via the engineer clicking **Wrong** — tape and clues only, **no node named** | M | ⬜ |
| FR-I4 | A marked-wrong run becomes diagnosable once a check or a pasted known-good output is added | M | ⬜ |
| FR-I5 | One URL for all three: `/runs/:id`. Not separate Datasets/Queues products | M | ⬜ |

### 5.4 Diagnosis gates (FR-G)

Cheap first, expensive last. The language model never gets the last word.

**G0 — cheap non-LLM suspects**

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-G0.1 | Flag schema-invalid or policy-violating tool calls (programmatic only, never an LLM judge) | M | ⬜ |
| FR-G0.2 | Flag empty retrieval and malformed JSON | M | ⬜ |
| FR-G0.3 | Flag **extractive** tokens in the final output absent from every upstream packet — numbers, URLs, closed strings. Not full-sentence verbatim matching, which over-fires on paraphrase | M | ⬜ |
| FR-G0.4 | Loop detector: a node repeating itself without state progress. No LLM | S | ⬜ |
| FR-G0.5 | G0 hits are **clues**, rendered visually weaker than G3. They may widen the G3 candidate list only when extractive, empty, or schema-invalid | M | ⬜ |

**G1 — optional LLM shortlist**

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-G1.1 | A hosted model may nominate a shortlist of candidates. Swappable model, user's key | S | ⬜ |
| FR-G1.2 | **Zero tools** on this call | M | ⬜ |
| FR-G1.3 | Redact secrets/PII before the call | M | ⬜ |
| FR-G1.4 | Multiple samples may only **widen** the list, never narrow it | M | ⬜ |
| FR-G1.5 | G1 never auto-starts G3 and never highlights a cause | M | ⬜ |
| FR-G1.6 | Disabling G1 entirely must leave the system functional | M | ⬜ |

**G2 — path check**

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-G2.1 | Each candidate must name a recorded arrow ("Writer used Searcher's output"). No arrow on the tape → discard | M | ⬜ |
| FR-G2.2 | Deterministic and repeatable. No model | M | ⬜ |
| FR-G2.3 | G2 only **rejects** invented stories; surviving candidates may still be wrong | M | ⬜ |

**G3 — run-again test (the only gate that may label a cause)**

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-G3.1 | Fork a run at a checkpoint and resume, without modifying the original thread | M | ⬜ |
| FR-G3.2 | Nodes in the candidate set *S* get a known-good behaviour or a known-good output | M | ⬜ |
| FR-G3.3 | Every node **after** *S* keeps its failed behaviour and must produce a **new** answer. Recorded outputs for those nodes are discarded for the trial | M | ⬜ |
| FR-G3.4 | **Paste-and-play is forbidden.** Replaying a downstream node's recorded output after its input changed must be impossible by construction, not by convention | M | ⬜ |
| FR-G3.5 | Model/network calls served **only** from a recording made under that same behaviour. Cache miss → abstain. **No live calls, no invented replies** | M | ⬜ |
| FR-G3.6 | Do not fill a cache miss from a success run of a node **not** in *S* — that silently fixes an untested node and collapses two-cause to one | M | ⬜ |
| FR-G3.7 | Verify the fix was actually applied, and that the replay's prefix matches the original. Mismatch → "replay went off track", not a verdict | M | ⬜ |
| FR-G3.8 | Never fire a side-effecting tool during a trial. Allowlist read-safe tools; abort the trial otherwise | M | ⬜ |
| FR-G3.9 | Set `durability: "sync"` on trials we start | S | ⬜ |
| FR-G3.10 | HITL / `interrupt` resumes are out of G3 for v1 — stated limitation, not a silent hole | M | ⬜ |

### 5.5 Minimality search and verdicts (FR-D)

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-D1 | Prune to nodes that can affect the final output, using static topology + write-diffs | M | ⬜ |
| FR-D2 | Prune **conservatively** — over-inclusion costs replays, under-inclusion costs correctness | M | ⬜ |
| FR-D3 | Test singletons, then pairs. Return **every** 1-minimal set: *S* flips Z and no proper subset does | M | ⬜ |
| FR-D4 | Support pairs on the same causal chain (the case GCJR abstains on) | M | ⬜ |
| FR-D5 | If several smallest sets flip Z, **report all of them**. Never collapse to a single locus | M | ⬜ |
| FR-D6 | Four verdicts per candidate: fixes it / partly helps / doesn't help / cannot say | M | ⬜ |
| FR-D7 | **Abstain is a first-class result** with a one-sentence reason: no known-good output for a node in *S*; a downstream node needed an unrecorded call; empty candidate set after widening; budget exhausted | M | ⬜ |
| FR-D8 | Hard budget: `--max-trials`, `--max-minutes`. Exhaustion is an abstain reason, not a crash | M | ⬜ |
| FR-D9 | Search cap on the 2^k subset space, with the cutoff documented | M | ⬜ |
| FR-D10 | Flakiness pre-check: re-run the failed run unchanged N times from its recording. If it sometimes passes, report **flaky** and stop | S | ⬜ |
| FR-D11 | Report counts, never ticks — "2 of 3", with the trial log | M | ⬜ |
| FR-D12 | Order candidates by cheap rules (loop, out-of-role, differs-from-passing-run) to reduce trials. Order affects speed only; G3 still decides | C | ⬜ |
| FR-D13 | Sets of three or more nodes | C | ⬜ |

### 5.6 Known-good sources (FR-K)

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-K1 | A passing run of the same input at temperature 0 — compare node by node, test only nodes whose output differs | M | ⬜ |
| FR-K2 | A user-pasted known-good output for a specific node | M | ⬜ |
| FR-K3 | A confirmed prior success on the **same node input bytes**. Never a silent auto-oracle — the engineer confirms | S | ⬜ |
| FR-K4 | If two same-input success packets disagree on whether restoring that node flips Z → **abstain**. Do not take any-flip as gold | M | ⬜ |
| FR-K5 | An earlier node configuration (prompt/model/tools) as a known-good **behaviour** | S | ⬜ |
| FR-K6 | A pasted *final answer* is a check (FR-C), not a known-good source. It cannot restore an upstream node | M | ⬜ |

### 5.7 Interface (FR-U)

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-U1 | One failed-run page — a Sentry *issue*, not a LangSmith *project*. Graph in the middle | M | ⬜ |
| FR-U2 | Judgment strip at the top: expected vs actual, or marked wrong | M | ⬜ |
| FR-U3 | Nodes coloured by **verified** result: must change / not needed / cannot say. Never by an LLM's opinion | M | ⬜ |
| FR-U4 | Evidence panel showing each trial and its outcome; smallest fix first; G1 visually weaker than G2/G3 | M | ⬜ |
| FR-U5 | Each node's input shown beside its output | M | ⬜ |
| FR-U6 | A green `ok` span must never hide a wrong answer | M | ⬜ |
| FR-U7 | Empty/broken recording → a health checklist (flushed? root exists? I/O missing vs redacted?), never a hollow graph | M | ⬜ |
| FR-U8 | Multiple minimal sets render as multiple chips | M | ⬜ |
| FR-U9 | First screen after install is a **seeded two-cause demo**. No signup, no API key | M | ⬜ |
| FR-U10 | Copy a node's prompt to clipboard. We are not a playground | S | ⬜ |
| FR-U11 | Read-only share view with no button that can re-run or fire a tool | S | ⬜ |
| FR-U12 | Run list with columns: question, actual output, judgment, diagnosis state. Not a cost chart | S | ⬜ |
| FR-U13 | Per-node timeline, errors first | M | ✅ |
| FR-U14 | Graph view of nodes and handoffs | S | ⬜ |

### 5.8 CLI and CI (FR-X)

CLI-first: every feature gets a CLI path before a GUI path.

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-X1 | `sherlock run <cmd>` — record a tape | M | ⬜ |
| FR-X2 | `sherlock diagnose --run <id>` — full G0–G3, prints the minimal sets or the abstain reason | M | ⬜ |
| FR-X3 | `sherlock check --config sherlock.yaml` — score without diagnosing | M | ⬜ |
| FR-X4 | `sherlock validate` — lint the check file; exit 1 on malformed config | S | ⬜ |
| FR-X5 | `sherlock serve` — local dashboard | M | ✅ |
| FR-X6 | `sherlock ingest teams\|runs\|logs` | M | ✅ |
| FR-X7 | Exit codes: `0` pass, `100` check failure, `1` infrastructure error. Distinct codes for "answered wrong" vs "graph crashed" | M | ⬜ |
| FR-X8 | `--output results.junit.xml` with `<failure>` for assertion failures and `<error>` for runtime problems | S | ⬜ |
| FR-X9 | `--output results.json` with a `stats.{successes,failures}` shape for custom `jq` gates | S | ⬜ |
| FR-X10 | `SHERLOCK_PASS_RATE_THRESHOLD` and `SHERLOCK_FAILED_CHECK_EXIT_CODE` | C | ⬜ |
| FR-X11 | GitHub Action: diagnose a failing test on PR, post the result as a comment | C | ⬜ |

### 5.9 Regression and sharing (FR-S)

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-S1 | Save a diagnosed run as a regression example: input + check + known-good references | S | ⬜ |
| FR-S2 | A runner that re-tests saved examples. **Do not ship FR-S1 without this** — review item 37: saving without a runner creates dead artifacts | S | ⬜ |
| FR-S3 | Re-run this test after a code change; link the result as a child of the original failure, not a new orphan run | S | ⬜ |
| FR-S4 | Export a read-only share view | S | ⬜ |

### 5.10 Comparison and evaluation harness (FR-E)

Needed for our own evaluation, so it is product code, not scripts.

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-E1 | 4–6 LangGraph demo teams with a fault-injection script | M | ⬜ |
| FR-E2 | Plant single faults and chained two-node faults | M | ⬜ |
| FR-E3 | Derive gold by **restoring subsets and observing**, never from "we injected these names" | M | ⬜ |
| FR-E4 | Baselines runnable on the same tapes and the same Z: plain LLM guess, G0-only, G0+G2, full G0–G3, random node, last node, plain retry | M | ⬜ |
| FR-E5 | Report exact-set match, Jaccard, and abstain rate, split by one-node vs two-node | M | ⬜ |
| FR-E6 | Hard slice defined **before** any method runs: silent-OK, last-step-looks-fine, two-cause | M | ⬜ |
| FR-E7 | CI freeze invariant: same tape, pinned G0–G2 candidates, same cassette → identical minimal sets across process starts | M | ⬜ |
| FR-E8 | CI invariant: paste-and-play **must fail** the two-cause case | M | ⬜ |
| FR-E9 | CI invariant: live time-travel without call blocking **must fail** the same case | M | ⬜ |

---

## 6. Non-functional requirements

### Correctness and honesty

| ID | Requirement |
|---|---|
| NFR-1 | Same tape, same pinned candidates, same cassette → identical result. Disagreement between process starts is a **failed freeze** (a CI bug), never a user-facing verdict |
| NFR-2 | The original run's history is never modified. All forking happens on synthesised threads |
| NFR-3 | No live model or network call on the diagnosis path. Ever. A missing recording produces an abstain |
| NFR-4 | Every abstain carries a one-sentence reason in plain English |
| NFR-5 | No LLM output may label a cause. Swapping out or deleting the G1 model must leave the contribution intact |
| NFR-6 | Every reported cause is backed by a trial log the user can read |

### Performance

| ID | Requirement |
|---|---|
| NFR-7 | Diagnose the three-node demo in ≤ 5 minutes on a developer laptop, no GPU |
| NFR-8 | ≥ 40% fewer trials than exhaustive subset enumeration, by pruning |
| NFR-9 | Trial count bounded by an explicit budget, never by hope |
| NFR-10 | SQLite retention policy or size cap, documented. A concurrent recorder plus an open UI must not deadlock (review item 39) |

### Usability

| ID | Requirement |
|---|---|
| NFR-11 | Install to first diagnosis in ≤ 15 minutes from the README, on the participant's own machine |
| NFR-12 | First screen is a seeded failing run. No signup, no API key, no "tracing pending" |
| NFR-13 | Zero edits to the user's source for recording and replay |
| NFR-14 | A stranger understands the seeded failure in ≤ 10 minutes — comprehension, not time-to-cause |

### Security and privacy

| ID | Requirement |
|---|---|
| NFR-15 | Binds to localhost by default |
| NFR-16 | API keys never logged |
| NFR-17 | Secrets and PII masked on ingest, before anything is written to disk or shared |
| NFR-18 | The share view cannot invoke a tool or start a run |
| NFR-19 | G1 has zero tool access; prompt-injection exposure documented as a known limitation |
| NFR-20 | No telemetry leaves the machine unless the user opts in |

### Portability

| ID | Requirement |
|---|---|
| NFR-21 | `pip install` on Windows, macOS, Linux. Wheels for each |
| NFR-22 | LangGraph pinned: `langgraph>=1.2.5,<2`, `langgraph-checkpoint>=4`. Lockfile after the first integration spike |
| NFR-23 | Record `GET /info` server version alongside every ingested artifact |
| NFR-24 | Deserialise checkpoint metadata permissively and preserve unknown fields — LangGraph adds metadata in minor releases |

---

## 7. Deliberately out of scope

Named so nobody rebuilds them by accident: prompt playground, prompt hub, cost/token
dashboards, annotation queues, pairwise review, production-issue clustering, GitHub
auto-PRs, Slack/PagerDuty, embedding clusters, a separate Datasets product, "ask an AI
why this failed" as the main answer, a debugger-buddy chatbot, aggregation across many
runs, and any second framework (CrewAI, AutoGen — different step grain, est. 4–8 weeks
to port, not scheduled).

**Words we will not use**, because competitors own them for different features: *time
travel* (AgentOps), *span replay* / *session replay* (Phoenix, HoneyHive), *root cause*
/ *2× detection* (LangSmith Engine, Datadog, HoneyHive), *rerun* (AgentDebugX Composer).
Working vocabulary: **this failed run**, **run-again cause**, **smallest set**, **marked
wrong**, **not in the input**.

---

## 8. Build order

Sequenced by dependency, not by calendar.

**Phase 0 — unblock.** Fix the `metadata.writes` defect (FR-R10 note). Verify the fork
recipe end-to-end against a live `langgraph dev`. Verify the `__overwrite__` form over
HTTP. Build demo team #1 with a fault-injection script (FR-E1, FR-E2). Nothing below
can be tested without these.

**Phase 1 — record and freeze.** The `sherlock run` launcher, the three interception
layers, the cassette store, and abort-on-miss (FR-R1–R8, FR-G3.5). This is the riskiest
component; everything else is ordinary engineering.

**Phase 2 — Z and G3.** Check file and the eight assertions (FR-C1–C6). Fork, restore,
resume, verify-applied (FR-G3.1–G3.8). First real verdict.

**Phase 3 — the search.** Pruning, singletons, pairs, 1-minimality, the four verdicts,
abstain reasons, budget (FR-D1–D9).

**Phase 4 — G0, G2, intake.** Cheap clues, the path check, mark-wrong, known-good
sources (FR-G0, FR-G2, FR-I, FR-K).

**Phase 5 — surface.** Run page, verified colouring, evidence panel, trial log, share
(FR-U).

**Phase 6 — evaluation.** Remaining demo teams, baselines, hidden set, hard slice, CI
invariants (FR-E).

Ownership is shared across all three of us on every phase. No module silos — each of us
must be able to explain, justify, predict the failure modes of, and modify any part of
G0–G3 under questioning.

---

## 9. Risks

### 9.1 Cassette coverage on stochastic nodes — highest

Consider the two-cause demo. Tapes recorded: a success run (good Searcher, good Writer)
and the failed run (bad Searcher, bad Writer). Trial *S* = {Searcher}: Searcher is
restored and emits the good text; Writer keeps its **bad** behaviour and receives that
good text for the first time.

That combination appears in neither tape. Cache miss. Under FR-G3.5 the trial abstains,
and the headline {Searcher, Writer} result never materialises.

`freeze_stub_spike.py` does not hit this because its bad Writer is a plain function
that ignores its input. The moment a bad node is a *prompt variant* of an LLM call,
every cross-combination is a miss.

**Mitigation, and the design decision that follows:** plant faults in **deterministic**
nodes — routers, parsers, retrievers, tool calls, validators — for the headline demo.
No model call on the counterfactual path, so no miss, so G3 always resolves. This is
consistent with §1.2 (any node, not just agents), it is where most real bugs live, and
it yields a clean claim: *Sherlock diagnoses deterministic nodes exactly and abstains
honestly on stochastic ones.* That still beats GCJR, which needed live calls.

**Explicitly rejected:** pre-recording the full behaviour cross-product. It would make
the demo work and a reviewer would correctly call it assuming the answer.

**Residual:** on a team whose faults are purely prompt-level, Sherlock abstains. Say so
in the limitations, first, before anyone finds it.

### 9.2 Dependency graph recovery — quantified

GCJR's accuracy falls from **1.000 to 0.552** when 10% of dependency edges are missing
— and GCJR *assumed the graph was given*. We must recover ours, and the recovery is
provably partial: checkpoints give static topology plus write-diffs, but nothing records
which state **keys** a node read, and dynamic `Command(goto=...)` routing is invisible
in the static graph.

Mitigation: prune conservatively (FR-D2), report the pruning ratio as the evidence for
NFR-8, and state the limitation plainly — *"we recover ancestry, not read-dependencies"*
is a legitimate finding, not a confession.

### 9.3 Remaining risks

| Risk | Mitigation |
|---|---|
| Looks like another dashboard | Viewer is deliberately the least novel part. First screen is a seeded failure, not a project list |
| A week-clone ships the freeze button | Correct — and it will get paste-and-play, live fallback, planted-names-as-gold, and never-abstain wrong. Those four are the project |
| Side effects re-fire during replay | LangGraph re-executes everything after the fork by default. Allowlist + abort (FR-G3.8). This is a real hazard, not theoretical |
| SSE replay delivers one chunk where the original delivered many | Store ordered chunk sequences (FR-R5). Every prior-art LLM cassette library hit this |
| Cassette key brittleness | Request bodies carry growing histories. Hash matching with sequential-order fallback |
| `PYTHONPATH` clobbered by a user startup script | Detect and warn in `sherlock doctor` (FR-R12) |
| Uncaught exception in `sitecustomize` | Python swallows only `ImportError` named `sitecustomize`; anything else causes a silent, mysterious process failure. Wrap the whole bootstrap |
| LangGraph API churn | Pin 1.2.x. Record server version per artifact. Thin adapter over public endpoints only |
| CrewAI ships checkpoint forking (shipped v1.14.2, Apr 2026) | Accept. Define a `CheckpointSource` seam so LangGraph is adapter #1; build only that one |
| Scoreboard fraud in the write-up | Same tapes, same Z, same cause definition. Never compare our % to AgentRx's +23.6%, AgentTrace's 94.9%, or CAR's Who&When number |

---

## 10. Open items

Not blocking the build; each needs a decision before the component that depends on it.

1. **PII deny-list** — exact field list, before writing ingest (FR-R8).
2. **Subset search cutoff** — the concrete cap for FR-D9.
3. **G1 empty after widening** — fall back to G0-only, or abstain? Either way it is scored.
4. **`__overwrite__` over HTTP** — verify empirically; design the fallback if unsupported.
5. **Live packet-picker UX** when several prior successes exist (FR-K3).
6. **G0 extractive-check false-positive rate** — measure on practice teams (review item 21).
7. **UI framework for the graph view** — current Rust+React stack stays unless FR-U14 forces a change.
8. **AgentRx programmatic subset** — run their repo or reimplement? Say which in the write-up.
9. **Seeded abstain demo** alongside the two-cause demo (review item 33).
10. **SQLite retention policy** — concrete cap (NFR-10).

---

## Appendix A — verified external facts

Everything below was verified on 12 October 2026 and has a shelf life. Re-check before
relying on any of it in the final report.

**LangGraph.** `langgraph` 1.2.14; `langgraph-api` 0.16.0; `langgraph-sdk` 0.4.6;
`langgraph-runtime-inmem` 0.36.0. Fork endpoints stable and pre-1.0. `metadata.writes`
removed in 0.5.x despite the docs still showing it. `config_schema` → `context_schema`
in 0.6, removal planned for 2.0. Sending both `config.configurable` and `context` in one
request → HTTP 400. `durability` ∈ `sync | async | exit`, default `async`; `exit` leaves
no intermediate checkpoints.

**Replay landscape.** No observability platform supports mid-point workflow replay.
LangSmith's forking goes through the checkpointer, not the trace store. LangGraph's own
time travel is re-execution with state injection — LangChain's docs state that nodes
after the checkpoint re-execute "including any LLM calls… which may produce different
results".

**Instrumentation.** LangChain callbacks are observe-only (every hook returns `Any`,
discarded). OTel and OpenInference instrumentors are observe-only by specification.
Gateway caches cannot abstain. `.pth` files deprecated in Python 3.15.

**Prior art.** GCJR arXiv 2608.29228 (v1 29 Aug, v2 6 Sep 2026), Li et al.; search
bounded at size ≤ 2; abstains on all 30 Sequential-Joint controls; 1.000 → 0.552 at 10%
missing edges. CAR 2606.08275 (Shah, CMU, Apache-2.0 declared but no `LICENSE` file).
AgenTracer 2509.03312. Who&When — the dataset; the paper is *"Which Agent Causes Task
Failures and When?"*, ICML 2025 spotlight, 184 failures, 53.5% agent / 14.2% step.
MAScope-Bench: 408 LangGraph runs confirmed (the `LG-Ctrl` corpus, part of 2,220 total).

**Two corrections.** "TraceElephant" is not a paper — the ACL URL resolves to *"Seeing
the Whole Elephant"* (Chen et al., ACL 2026). AgentAssay is **AGPL-3.0**, not Apache-2.0.
