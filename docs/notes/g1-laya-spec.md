> **Working note (tier 3). Not authoritative.** It may be stale or wrong. Facts come from the code and from docs/eval. Never cite this file in anything submitted to the university.

# Sherlock G1 Spec: Laya Suspicion Scorer (API iteration, v0)

Oct 27, 2026 · @Ali · Revision of the Oct 23 spec

**What changed in this revision.** The first iteration calls Laya through an HTTP API, zero-shot. There is no fine-tuning, no training data pipeline, no combiner fitting, no local weights handling and no ONNX export. The goal of v0 is to answer one question cheaply: does an off-the-shelf Laya, shown a node card, rank the right nodes higher than the deterministic baselines? Local weights and fine-tuning are deferred to a later version and listed in section 13.

## 1. Purpose and scope

G1 scores how likely each node is to belong to a minimal fix, so that G3 (the run-again trial) tests the likeliest nodes first. It changes the order of trials and nothing else: G3 remains the only gate that can name a cause.

Today G1 is an optional hosted-model shortlist (FR-18). This spec adds a Laya-based ranker as a new backend, called over HTTP. The existing hosted shortlist stays available as a separate backend.

**What the engineer delivers**

- A node-card builder: a pure function that turns a failed run, a known-good run and the recording into one short text card per node.
- A Laya API client: sends one card plus the question set per call, parses the answers, and is deterministic from the point of view of the result file (response cache, section 7).
- A fixed scoring rule that turns the answers into one suspicion score per node. No fitted parameters.
- Integration into the orchestrator, the result file, the progress lines and the web verdict.
- A zero-shot evaluation that shows whether the ranker helps, without ever changing a diagnosis.

**Where it helps, honestly.** On the 86 planted cases the cheap G0 clues already pointed at a correct node every time (report Table 6.4), and large teams needed 1, 3 or 7 trials. There is little room to improve there. The gain, if any, is on real failures, large teams and tight trial budgets, so the evaluation in section 11 is built around those. Also expect a real chance of a null result: Laya's zero-shot accuracy is reported close to random (section 4), and v0 is deliberately a zero-shot test.

## 2. Hard constraints

Every constraint below comes from the Sherlock mid-evaluation report and is a release gate. C3, C5, C7 and C8 are reworded for the API approach; the rest are unchanged.

| # | Constraint | Source |
| --- | --- | --- |
| C1 | G1 may reorder candidates and, only when enabled, widen the list. It never names a cause. Only a passing G3 trial does. | FR-17, FR-18, NFR-3 |
| C2 | With G1 off or on, `minimal_sets` must be identical on every evaluation case. This is the invariant the hint model already meets (TC-15). | FR-18, TC-15 |
| C3 (revised) | The only network use during diagnosis is the G1 call to the configured Laya endpoint, and only when `--g1 laya` is set. No other host is contacted. The default endpoint is the hosted Laya API, `https://api.laya.studio/v1/systemone`, which is remote, so the opt-in in C5 applies. G3 trials and search never make network calls. | FR-3, NFR-2 |
| C4 | Same inputs give a byte-identical result file. Raw API probabilities are rounded to 4 decimals, cached by card hash, and ties are broken by a fixed rule (section 7). | NFR-1, AC-8 |
| C5 (revised) | Nothing leaves the machine without opt-in and there is no telemetry. The default Laya endpoint is remote, so using it is an explicit opt-in (`--g1-allow-remote`, or `g1.allow_remote = true` in config), because card text then leaves the machine. Cards are redacted first (C6). Jev stays research-only. | NFR-11 |
| C6 | Cards are built from redacted data only. | FR-4, NFR-10 |
| C7 (revised) | The Sherlock side runs on a laptop CPU with no GPU and no model weights. Where the model runs is the endpoint's concern. | NFR-4 |
| C8 (revised) | A G1 failure (endpoint unreachable, timeout, auth error, malformed response, empty card) never causes an abstain. G1 is skipped and the run continues as if it were off. A G1 call must never block diagnosis longer than the configured total timeout (section 10). | FR-15, AC-6 |
| C9 | The trial budget rules are unchanged. G1 API calls do not count as trials. | FR-16 |
| C10 | No abstain result names a node, and G1 scores never appear as a culprit label. | FR-15, AC-6 |

## 3. System overview

G1 sits between pruning and the path check, and the only new work is step 3. Everything else already exists in the report's design (Figure 5.5, Table 5.1).

1. **G0 clues.** Deterministic rules read the run history and recording and produce clues with weights.
2. **Prune.** Drop nodes that ran after the last write to the output field, wrote the same output as the good run, or have no good patch.
3. **G1 (new).** For each surviving node, build a card, send it with the question set to the Laya API, and compute one suspicion score from the answers.
4. **Order.** Sort candidates by (clue tier, G1 score, node name). Clues stay stronger than G1, as the report requires.
5. **G2 path check.** A suspect must lie on a recorded hand-off path to the output.
6. **G3 and search.** Trials run in the new order. Enumeration or duality search decides and proves minimality exactly as before.

**Inputs to G1:** the failed run's checkpoint history, the known-good run's history, the recording database, and the check result. **Output of G1:** an ordered list of node names with scores and the answers behind them, written into the result file.

**Why exactness is untouched.** The search proves completeness by testing sets, not by trusting the order. Order only decides which sets are tried first and therefore how early a fix is found inside the budget. The one place a bad order can cost something is a tight budget, where it could end as `budget_exhausted`, never as a wrong claim.

## 4. The Laya API

Laya is a small open-weight "System 1" decision model: it reads a state plus typed questions and returns probabilities in one forward pass, with no text generation. In v0 Sherlock uses it only as a remote scorer.

**Endpoint for v0.** Use the hosted Laya API at `https://api.laya.studio/v1/systemone`, authenticated with a bearer key in the environment variable `LAYA_API_KEY`. Open-weight Laya can also be served locally (`laya-serve`, Unsloth, LiteLLM or Bifrost gateways) with the same request format, so keep the base URL, path and model name configurable. That lets the client later point at a local server with no code change. The Laya docs for the hosted service were not available to me, so confirm the details below with the smoke test in section 10.

| Setting | Value |
| --- | --- |
| URL | `POST https://api.laya.studio/v1/systemone` |
| Auth | `Authorization: Bearer $LAYA_API_KEY` |
| Request body | `state` (a string or any JSON), `questions` (map of answer ID to question). `model` is optional. Omit it by default, and send it only if `--g1-model` is set. If the service offers a typed-decisions checkpoint (1k-token context), prefer it. |
| Limits (from other servers, verify) | up to 64 questions per request, up to 255 options per choice, up to 10 levels per score |

Reference call from the Laya docs, kept as the shape the client must reproduce:

```python
import os, requests

r = requests.post(
    "https://api.laya.studio/v1/systemone",
    headers={"Authorization": f"Bearer {os.environ['LAYA_API_KEY']}"},
    json={
      "state": {"message": "I was charged twice this month. Refund me or I cancel."},
      "questions": {
        "intent": {
          "type": "choice",
          "instructions": "What does the customer want?",
          "criteria": {
            "refund": "money back or a duplicate charge reversed",
            "technical_help": "a bug or integration problem",
            "cancellation": "wants to cancel",
            "other": "anything else"
          }
        },
        "urgent": {"type": "noul", "instructions": "Does the message communicate time pressure?"},
        "frustration": {
          "type": "score",
          "instructions": "How frustrated does the customer sound?",
          "criteria": ["calm", "concerned", "annoyed", "very angry"]
        }
      }
    },
    timeout=30,
)
r.raise_for_status()
answer = r.json()["answers"]["intent"]
print(answer["choice"], answer["probabilities"])
```

Note the shape: a `choice` answer has `choice` and `probabilities`, a `noul` answer has the yes probability, and a `score` answer has a score and `probabilities`. The Sherlock client reads `probabilities` and `noul`, not `confidence`.

**Question types and responses**

| Type | Use | Response field |
| --- | --- | --- |
| `noul` | yes/no | `answers.<id>.noul` is the probability of yes, 0 to 1 |
| `choice` | one option from a described set | `answers.<id>.probabilities` maps each option to a probability |
| `score` | rating on a scale | not used in v0 |

The response also carries `usage.input_tokens` and, on some servers, `usage.truncated`. Use `probabilities` and `noul`, never `confidence`, because confidence is computed differently across servers.

**Cautions you must design around**

- **Zero-shot may be near chance.** Laya's own typed-decision evaluation reports base zero-shot accuracy only slightly above the random baseline, and an independent paired study found neither Laya nor Jev beat chance on zero-shot model routing ([Fast Models, Slow Evidence](https://arxiv.org/pdf/2610.02267)). v0 exists to measure this on node cards. A null result is a valid outcome, not a bug.
- **Context is 1k tokens at most** and longer input is truncated by the server. Agent state does not fit, which is why section 5 builds a compact card per node.
- **Weak at arithmetic.** Do not ask Laya to verify computed values. Leave that to deterministic checks.
- **Vendor numbers are self-reported.** Do not quote Laya's benchmark scores as evidence it will work on node cards.
- **No explanations.** Laya returns probabilities only. Any human-readable reason in the UI must come from the deterministic diff, not from Laya.
- **Question wording matters** for a zero-shot model, because it has never been trained on these questions. Treat question text as a versioned part of the system (section 6).

## 5. Node card specification

A node card is a fixed-format text of at most 800 tokens that shows Laya one node's failed behaviour next to its known-good behaviour. It is the most important design choice in the system, because Laya can see nothing else.

**Fields, in the order they appear.** Priority P0 is never truncated. Higher numbers are cut first when the card is over budget.

| Field | Source | Priority |
| --- | --- | --- |
| Node name and role (role from the node map or graph metadata, blank if none) | Graph, node map | P0 |
| Flags: `output_same_as_good`, `input_same_as_good`, `errored`, `tool_call_failed`, `upstream_differs=[names]` | Computed deterministically from both histories | P0 |
| Check: the assertions the run must satisfy, in plain words | Check file | P1 |
| Diff: removed and added snippets between failed and good output, max 200 characters each | Computed deterministically | P1 |
| Error text, if the node raised | Checkpoint task result | P1 |
| Output in the failed run | Checkpoint task result | P2 |
| Output in the good run | Known-good source | P2 |
| Input received in the failed run (state values before the node ran) | Checkpoint before the node | P3 |
| Tool calls: name, argument summary, status | Recording database | P3 |

**Example card (vendor brief, extractor node).**

```text
NODE: extractor | ROLE: pick certifications and data region from documents
CHECK: contains "ISO 27001"; contains "Data region: EU"; not contains "SOC 2"
FLAGS: output_same_as_good=no input_same_as_good=no errored=no tool_call_failed=no upstream_differs=[retriever]
DIFF: removed "ISO 27001" | added "SOC 2 (current)"
OUT_FAILED: {"certs": ["SOC 2"], "region": "EU"}
OUT_GOOD: {"certs": ["ISO 27001"], "region": "EU"}
IN_FAILED: docs=[doc1: "SOC 2 certificate ... expired in 2023", doc2: "All data stored in the EU"]
```

**Rules**

1. The builder is a pure function of (failed history, good history, recording, check). Same inputs give the same string, byte for byte. Sort keys, normalize whitespace and use fixed truncation lengths.
2. When a field is over budget, cut from the highest priority number down. Cut a long string to its head and tail with a marker such as `[...312 chars cut...]`. Never cut a flag.
3. **Token budget without a local model.** The builder must not depend on Laya weights. Estimate tokens with a fixed conservative rule (for example 1 token per 3 characters) and target 800 tokens for the card. At call time, check `usage.input_tokens` from the response, and treat `usage.truncated = true` or `input_tokens` above 1,000 as a failed card (rule 4). In tests, an integration check against a live endpoint (skipped when none is configured) confirms real token counts. Reserve about 200 tokens for the question text and options.
4. If a card was truncated by the builder or by the server, record the node name in `g1.truncated_cards`. A server-truncated card gets a null score, because the end of the card or the questions may have been cut. This never stops the run.
5. Apply the same secret and e-mail redaction as the recorder to every card (C6). Do not write full cards into the result file. Store a hash of each card so a run can be reproduced.
6. For the name-masking ablation (section 9), the builder must support a mode that replaces node names with stable random IDs.

**Open question for the engineer.** Confirm that the checkpoint before a node reliably gives its input, including for parallel branches and joins that feed several nodes (a known limitation in the report). If not, set `input_same_as_good=unknown` and drop the input field for that node.

## 6. Question set (version g1_questions_v1)

Every card is asked the same typed questions in one API call. Q7 is the real objective and the only one used for the score in v0. The others are logged so that later versions, and the analysis, can use them. They are cheap, since all questions share one forward pass.

| ID | Name | Type | Options | Used for |
| --- | --- | --- | --- | --- |
| Q1 | `output_effect`: how does the failed output differ from the good output? | choice | same, cosmetic, meaningful | Logged, analysis |
| Q2 | `fault_origin`: where did the difference start? | choice | originated_here, inherited, none | Logged, analysis |
| Q3 | `dropped_input`: did the node omit information that was in its input? | noul | yes/no | Logged, analysis |
| Q4 | `invented_output`: does the output contain content its input does not support? | noul | yes/no | Logged, analysis |
| Q5 | `pass_through`: did the node only pass its input along? | noul | yes/no | Logged, analysis |
| Q6 | `tool_relevance`: was the tool call needed for the task? Asked only if the node made a tool call | choice | necessary, redundant, irrelevant | Logged, analysis |
| **Q7** | **`needs_restore`: must this node be restored to its good behaviour for the run to pass?** | noul | yes/no | **The score** |

**Notes**

- Q2 is the key question for a minimal-set tool. A node that behaved correctly on corrupted input is inherited, not a cause, and the writer in the vendor example is the standard case. A node can be both.
- Q5 is the question most likely to be answered by a rule, so compare Laya against that rule (section 11).
- Tool-call validity against a schema is deterministic and belongs in G0, so it is not asked here.
- Write every question's `instructions` and every choice option's description in plain, short sentences, with the options described in the `criteria` map. Because there is no fine-tuning, the wording is the only lever. Keep the exact text in one constants file.
- **Question wording may be tuned in v0**, on a development set of generated cases only, never on the 86 existing cases or on real failures. Every change to question text or option order needs a new version string (`g1_questions_v2`, and so on). Store the version in the result file.
- Do not ask Laya anything that needs arithmetic or exact string comparison. Those are computed in the card flags and diff.
- Q8 `fault_kind` is reserved for a later version and must not feed the score.

## 7. Scoring, ordering and determinism

**Score.** In v0 the suspicion score of node i is simply

```text
s_i = P(Q7 = yes)   # the noul value for needs_restore, rounded to 4 decimals
```

It is a ranking signal, not a probability of guilt. No weights are fitted and there is no combiner in v0. The other answers are stored in the result file, so a combiner can be fitted offline later without re-calling the API.

**Ordering.** Use variant A only in v0:

| Variant | Priority key | Note |
| --- | --- | --- |
| A: lexicographic | (clue tier, s_i descending, node name) with G0 weights bucketed into tiers | Keeps clues strictly stronger. G1 only breaks ties inside a tier. Check how G0 weights are distributed first, or G1 may never get to act. |
| B: blended | Deferred. It needs a tuned lambda, which needs training-style validation data. | Not in v0 |

Node name is always the last tie-breaker so ordering is total and reproducible. Nodes with a null score sort last within their tier, by name.

**Widening.** Off in v0. Out of scope (section 13).

**Status values written to the result file**

| Status | When | Effect |
| --- | --- | --- |
| `ok` | All cards scored | Order applied |
| `partial` | Some cards failed to build, were truncated, or failed to score | Failed nodes get a null score and sort last within their tier, by name |
| `skipped` | Fewer than 2 candidates, or `--g1` is `off` | No reordering needed |
| `unavailable` | Endpoint unreachable, timeout, auth error, malformed response, model name rejected, or the total G1 time limit hit | Run continues exactly as if G1 were off (C8) |

**Determinism (C4), now that the model is remote.** A remote server can change its model or numerics under you, so determinism is enforced on the Sherlock side:

1. Send one card per request, sequentially, with the same fixed question set and question order every time.
2. Cache every response on disk under `.sherlock/g1_cache/`, keyed by SHA-256 of (card text, question version, model name, endpoint server version if the server reports one). A cache hit makes no network call. A re-run of the same inputs therefore reproduces the same scores, even offline.
3. Round every stored probability to 4 decimals before it is used or written.
4. Record the endpoint host (not any key), model name as reported in the response, question version, client version and, if the server reports it, the server version. If the reported model name changes between runs, log a warning and treat it as a cache miss.
5. The committed evaluation file holds only ranks and trial counts. Raw probabilities are compared in a separate test with a tolerance of 1e-3, because different servers or hardware can differ slightly.
6. `--g1-no-cache` exists for evaluation runs that must hit the live endpoint. Such runs are not byte-reproducible and must say so in the result (`g1.cache = "disabled"`).

## 8. Integration contract

G1 plugs into the Python diagnosis engine through one backend interface, and reaches the Rust side only through new optional fields in the diagnosis result file. Names below are proposed. Align them with the repository's conventions before coding.

**Backend interface (Python)**

```python
class G1Backend(Protocol):
    name: str  # "off" | "hosted" | "laya" | "fake"
    def rank(self, candidates: list[str], cards: dict[str, str]) -> G1Result: ...

@dataclass
class G1Result:
    status: Literal["ok", "partial", "skipped", "unavailable"]
    scores: dict[str, float | None]                # node -> score, 4 decimals
    answers: dict[str, dict[str, dict[str, float]]]  # node -> question -> option -> prob
    truncated_cards: list[str]
    meta: dict                                      # backend, endpoint host, model, question version, versions, cache stats, ms
```

Four backends. `off` returns `skipped`. `hosted` wraps the existing hint model. `laya` is the new one and calls the API. `fake` returns scores derived from a hash of the node name and exists so the orchestrator and search can be tested with no network and no endpoint, the same way the search is already tested with a fake trial. A fifth test helper, a fake HTTP server that replays canned System One responses, is used to test the `laya` client itself.

**Switches (proposed)**

- `sherlock-rec diagnose --g1 off|hosted|laya`, default `off`.
- `--g1-endpoint URL`, or env `LAYA_API_BASE`. Default `https://api.laya.studio`.
- `--g1-path PATH`, default `/v1/systemone`.
- `--g1-model NAME`, default unset (the `model` field is omitted from the request).
- API key from env (load .env) `LAYA_API_KEY` only (a missing key makes G1 `unavailable`), never from a flag, never written to the result file or logs.
- `--g1-allow-remote`: required if the endpoint host is not `localhost`, `127.0.0.1` or `::1`. Because the default endpoint is remote, `--g1 laya` needs this flag too. Without it, G1 is `unavailable` with a clear message that says card text would leave the machine (C5).
- `--g1-timeout-ms` per call, default 10000. `--g1-total-timeout-ms` for all of G1 on one diagnosis, default 60000.
- `--g1-no-cache`, as above.
- There is no `fetch-model` command in v0.

**Result file additions.** Add one optional `g1` object. Keep it additive.

```json
"g1": {
  "backend": "laya",
  "status": "ok",
  "question_version": "g1_questions_v1",
  "endpoint_host": "api.laya.studio",
  "model": null,
  "client_version": "...",
  "server_version": null,
  "cache": {"hits": 0, "misses": 6},
  "order_variant": "A",
  "scores": [{"node": "retriever", "score": 0.8231, "answers": {"needs_restore": {"yes": 0.8231, "no": 0.1769}}}],
  "truncated_cards": [],
  "card_hashes": {"retriever": "..."},
  "order_changed": true,
  "ms": 2140
}
```

The Rust reader already validates results before use. Confirm it ignores unknown fields. If it does not, bump `schema` from 1 to 2 and keep reading 1.

**Progress lines.** The `g1` line kind already exists. Emit one when G1 finishes, with backend, status, number scored, cache hits and milliseconds.

**Rust and web application**

- Node status (culprit, cleared, unverified, abstained) is derived only from trials. G1 must never influence it, and a unit test should prove it.
- In the evidence panel, show the G1 score as a hint tagged weaker than tested results, the same treatment the report plans for the hint model.
- Never show a G1 score on an abstain result next to a node (C10).

**Packaging.** The client needs only an HTTP library. Use the one the repository already uses, or the standard library, so there is no new heavy dependency and no `laya` package in the base install. Include a README section on configuring the endpoint, the privacy rule for remote endpoints, and the zero-shot caveat.

**Performance target.** G1 adds at most 10 seconds to a 33-node team (33 sequential calls, so about 300 ms per call or better). Network latency to the hosted API counts. This is a starting target. Measure in step 3 and revise. The first request to a server may be slow while it loads the model, so run one warm-up call and exclude it from the timing, but count it against the total timeout.

## 9. Evaluation data (no training in v0)

Nothing is trained, so there is no train split and no label-fitting. The existing evaluation harness already produces free, exact ground truth for every case: it restores each subset of nodes and records which subsets pass, so a node's Q7 label is whether it appears in any minimal set. Use that label only to score the ranker, never to build prompts.

| Source | Used for | Target size | Notes |
| --- | --- | --- | --- |
| The existing 86 cases (52 visible, 34 hidden) | Regression test and first measurement | 86 | Never used to tune question wording |
| Harder generated cases: larger teams, layered graphs, varied roles, paraphrased outputs | Development set (question wording) and test set, kept as separate files | start with about 200 failed runs, split 50/50 | Seeded and byte-reproducible. Needed because the 86 are probably too easy |
| Real failed runs collected in FYP-2 | Real-world test | about 10 | Test only. Redacted before storage. Report separately |

**Reporting.** Show planted (86), generated test, and real-failure results in separate tables. Never average planted and real results together.

**Shortcut controls.** Build these in from the start, as a ranker on synthetic data can find easy cues.

- **Name masking.** Run a variant where node names are replaced by random IDs. A large change means the model keys on names.
- **Position.** Shuffle node order in cards, and report a position-only baseline.
- **Deterministic baselines.** Always report G0 clue order and a rule that ranks nodes whose output differs from the good run. After pruning, these may already be strong. Laya has to beat them to justify itself.
- **Text variety.** The demo teams use deterministic code and a local stand-in model, so their text is templated. The generated set must add paraphrase and format variation.

**Reproducibility and privacy.** Dataset generation is seeded and byte-reproducible like the evaluation (NFR-1). Store it as JSON Lines with a version string. Real failures must be redacted before they are stored, and no customer data goes in the repository. The generated and planted cases are synthetic and safe to send.

## 10. Instructions for calling the Laya API

Follow these steps in order. Put the client in one module, for example `g1/laya_client.py`, with no side effects at import time.

**1. Configure.** Read endpoint, path, model, timeout and key as in section 8. Default to `https://api.laya.studio/v1/systemone`. If the host is not local and `--g1-allow-remote` is absent, or `LAYA_API_KEY` is unset, return `unavailable` before building any request.

**2. Build the request.** One request per node card. Header `Content-Type: application/json`, plus `Authorization: Bearer $LAYA_API_KEY` only when the key is set. Body (add `"model"` only if `--g1-model` is set):

```json
{
  "state": "<the card text>",
  "questions": {
    "output_effect": {
      "type": "choice",
      "instructions": "How does the failed output differ from the good output?",
      "criteria": {
        "same": "identical in meaning and content",
        "cosmetic": "only wording, order or formatting differs",
        "meaningful": "facts, values or content differ"
      }
    },
    "fault_origin": {
      "type": "choice",
      "instructions": "Where did the difference start?",
      "criteria": {
        "originated_here": "this node introduced the difference",
        "inherited": "the node's input already differed and the node behaved correctly on it",
        "none": "no difference"
      }
    },
    "dropped_input":   {"type": "noul", "instructions": "Did the node omit information that was in its input?"},
    "invented_output": {"type": "noul", "instructions": "Does the output contain content its input does not support?"},
    "pass_through":    {"type": "noul", "instructions": "Did the node only pass its input along unchanged?"},
    "tool_relevance": {
      "type": "choice",
      "instructions": "Was the tool call needed for the task?",
      "criteria": {"necessary": "needed", "redundant": "not needed but harmless", "irrelevant": "unrelated to the task"}
    },
    "needs_restore": {"type": "noul", "instructions": "Must this node be restored to its good behaviour for the run to pass the check?"}
  }
}
```

Omit `tool_relevance` when the node made no tool call. The key names above are the stable answer IDs. The exact wording is part of `g1_questions_v1`.

**3. Send.** `POST {endpoint}{path}`. Use a per-call timeout (default 10 s, since the reference call uses 30 s and this is a remote service), one retry on connection error or HTTP 5xx or 429 with a short fixed delay (no random jitter, to keep behaviour reproducible), and no retry on 4xx. Do not follow redirects to a different host. Never log the Authorization header or the card text.

**4. Parse.** For each requested question, read `answers.<id>.noul` (a number in 0 to 1) for yes/no questions, and `answers.<id>.probabilities` (a map of option to probability) for choice questions. Reject the response for that card if a requested answer is missing, a probability is not a finite number in [0, 1], or the choice probabilities do not sum to about 1 (tolerance 0.02). Clip to [0.001, 0.999] only for display or later logit use, not for the stored value. Round to 4 decimals.

**5. Check the response.** Compare `usage.input_tokens` against the 1,000-token context. If `usage.truncated` is true, or `input_tokens` is above 1,000, mark the card truncated, null its score and list it in `truncated_cards`. Record the `model` string in the response.

**6. Cache.** Write the parsed, rounded answers to the cache before using them. Look up the cache before every call (section 7).

**7. Fail safe.** Any exception, timeout or malformed response for one card gives that node a null score (`partial`). If the first call fails with a connection or auth error, or the total time limit is reached, stop calling, return `unavailable`, and let the run continue as if G1 were off (C8). G1 must never raise out of the orchestrator.

**8. Smoke test, before any other work with the endpoint.** Provide `sherlock-rec g1-check`, which:
   - sends the sample card from section 5 plus the full question set,
   - prints the HTTP status, the path used, the reported model name, `usage`, and all parsed probabilities,
   - sends the same card twice and reports whether the two answers are identical,
   - times a warm call,
   - prints the privacy note: "this sends card text to <host>".

   This command is how the engineer confirms the path, model name and response shape against the real server. If the response shape differs from section 4, update only the parser and note the difference in the README.

**9. Tests.** Unit-test the parser and client against a fake HTTP server (recorded System One responses, including a truncated, a malformed, a 429, a 401, a timeout and a wrong-model response). Mark live-endpoint tests as integration tests that are skipped when `LAYA_API_BASE` is unset.

## 11. Evaluation plan and acceptance criteria

G1 earns its place only if it cuts the trials needed to find the first fix on cases the deterministic baselines handle badly, while every invariant in section 2 still holds. Declare the pass rule below before running the final test, as the report does for its other criteria.

**Metrics**

| Metric | Definition |
| --- | --- |
| Mean reciprocal rank (MRR) | 1 divided by the rank of the first node that belongs to any minimal set |
| Recall@3 | Share of nodes in the union of minimal sets that appear in the top 3 |
| NDCG@3 | Ranking quality of the top 3 against the gold nodes |
| Trials to first fix | Number of G3 trials until the first passing set is found, mean and median |
| Budget outcomes | Count of `budget_exhausted` abstains at the default budget and at a tight budget (for example 10 trials on 33-node teams) |
| Cost | G1 milliseconds per run, cache hit rate, calls per run, failure rate of calls |

**Methods to compare, on the same recordings and checks**

1. Random order with a fixed seed.
2. G0 clue order only.
3. Rule baseline: rank nodes whose output differs from the good run.
4. The existing hosted hint model, using the local stand-in.
5. Laya API, zero-shot, Q7 score (the v0 system).
6. Laya API, zero-shot, with name masking (shortcut control).
7. Laya API, zero-shot, with a Q2-based score (`P(originated_here)`) as an extra analysis column only. It does not become the product score without a new version.
8. Optional, research only: Jev zero-shot on synthetic cards, with explicit opt-in because it sends data to a hosted API.

**Reporting rules.** Show the 86 planted, generated-test and real-failure results in separate tables. Report counts as well as rates, because n is small. Show per-team rows. Because there is no training, there is no seed spread to report, but repeat each live run 3 times to report API answer stability (the share of runs whose ranking is identical), with the cache disabled.

**Acceptance criteria**

| ID | Criterion | How it is checked |
| --- | --- | --- |
| AC-G1-1 | At default budgets, `minimal_sets`, `unverified_sets`, status and reason code are identical with G1 on and off, on all 86 cases and the scale tests (30 to 300 nodes). | Paired run, automatic diff |
| AC-G1-2 | At tight budgets, zero wrong claims, and the exact-answer count with G1 on is at least the count with G1 off. | Evaluation harness |
| AC-G1-3 | Same inputs give a byte-identical result file on three runs on one machine. | Existing regeneration check, with the response cache enabled |
| AC-G1-4 | During diagnosis with G1 on, the only network connections are to the configured G1 endpoint, and zero with `--g1 off` or `--g1 fake`. A non-local endpoint without `--g1-allow-remote` makes zero connections. | Socket trap |
| AC-G1-5 | If the endpoint is unreachable, times out, returns an error or returns malformed answers, the result equals the G1-off result except for the `g1` object (`status = unavailable`). | Tests with a dead port and with the fake HTTP server |
| AC-G1-6 | Every card is at most 800 estimated tokens, and the builder matches golden files. | Unit tests; token counts confirmed in the live integration test |
| AC-G1-7 | Node status in the verdict is unchanged by any G1 score. | Rust test |
| AC-G1-8 | G1 adds at most 10 seconds on a 33-node team against a warm local endpoint, and never more than the total timeout in any case. | Timed run |
| AC-G1-9 | The orchestrator and search are fully tested with the `fake` backend and the fake HTTP server, no endpoint required. | Python tests |
| AC-G1-10 | The README section and `g1-check` command exist, and a clean machine can point Sherlock at an endpoint and run the check. | Manual test |
| AC-G1-11 | The API key never appears in the result file, logs, progress lines or cache. Card text never appears in logs. | Test that scans outputs for a planted key and card string |

**Pre-declared ship rule (confirm the margin with your supervisor before the final run).** Make Laya API the default backend only if all acceptance criteria pass, and on the generated test set or on real failures it cuts mean trials to first fix by at least 20 percent against the better of G0 order and the rule baseline, under the tight budget, without increasing `budget_exhausted` anywhere. Otherwise it stays an optional backend, off by default, and the result is reported as it is. Given the zero-shot caveat in section 4, the expected outcome of v0 is "optional, off by default". A null result is still a result and fits the report's honesty rules. It is also the evidence that decides whether the next version (fine-tuning) is worth building.

## 12. Build steps

Build in six steps, each ending in a check you can run. Steps 1 to 3 need no real endpoint until step 3.

| Step | Build | Exit check |
| --- | --- | --- |
| 1 | Backend interface, the `off` and `fake` backends, and the orchestrator call site | AC-G1-1 holds with `off`. AC-G1-9 passes with `fake` |
| 2 | Node-card builder with golden-file tests | AC-G1-6. Read the cards for 10 cases by eye, including the vendor-brief example |
| 3 | Laya API client, response cache, error handling, `g1-check`, fake HTTP server tests | Section 10 steps 1 to 9 done. AC-G1-4, 5 and 11 pass. Same card twice gives identical output. Measured time replaces the 10-second target |
| 4 | Zero-shot evaluation of methods 1 to 6 on the 86 cases | Metrics table written. **Gate:** if G0 order or the rule baseline already finds the first fix in at most 1 trial on 95 percent of cases, planted data cannot show a gain. Tell your supervisor and move straight to harder generated cases and real failures |
| 5 | Harder generated cases and shortcut controls (can run in parallel with steps 2 to 4). Tune question wording on the development half only, bump the version string for each change | Dataset v1 is byte-reproducible. Dev and test files committed. Evaluation of methods 1 to 7 on the test half |
| 6 | Integration: `g1` result field, progress line, Rust reader, evidence panel, schema decision. Then the final evaluation with frozen question version, and the ship decision | AC-G1-3, 7 and 10 pass. Tables for all three data sources. Decision recorded against the pre-declared rule |

Real-failure evaluation (FYP-2) is run as soon as real cases exist, reported separately, and uses the frozen question version.

**Working rules.** Keep every step behind `--g1`, off by default, so the main branch stays releasable. Freeze the question version before the single final test run. After that, do not change questions, scoring or order variant without a new version string.

## 13. Risks, open questions and out of scope

The biggest risk is not technical: the planted test cases may be too easy for any ranker to show a gain, and zero-shot Laya may be near chance on node cards. The honest result could be "no measurable improvement". The plan is built to detect that early (step 4) and to move the real test to harder cases and real failures.

**Risks**

| Risk | Likelihood, impact | Mitigation |
| --- | --- | --- |
| Zero-shot Laya is near chance on node cards | High, high | That is what v0 measures. Report it. Decide on fine-tuning only after seeing the result |
| Planted cases are already solved by G0 order, so no gain is measurable | High, medium | Step 4 gate. Harder generated cases. Real failures in FYP-2 |
| The hosted API's model, limits, context length or response shape differ from what section 4 assumes | Medium, medium | `g1-check` smoke test. Parser isolated in one place. Check `usage` for token counts and truncation |
| Rate limits, cost per call or key quota on the hosted API | Medium, medium | Caching, sequential calls, one retry, `unavailable` fallback. Count calls per run in the metrics |
| Card text leaves the machine when the endpoint is remote | Medium, high | Local default, `--g1-allow-remote` opt-in, redaction before cards, no real failures sent without approval |
| The remote model changes under you, so results drift | Medium, medium | Cache by card hash and model, record the reported model, warn on a change, ranks-only committed evaluation file |
| Latency or rate limits make 33 sequential calls too slow | Medium, medium | Warm-up call, per-call and total timeouts, caching, `unavailable` fallback. Batch or parallel calls only after determinism is re-checked |
| Truncation drops the evidence on large nodes | Medium, medium | Flags are never cut. `truncated_cards` is logged. Server truncation nulls the score. Ablate the card budget |
| Question wording overfits the development set | Medium, medium | Tune on the dev half only, freeze before the test, never touch the 86 or real failures |
| Real faults sit in model-calling nodes where Sherlock abstains anyway, so ordering cannot help | High, medium | State it in the report. G1 helps only where trials can run |
| A reader sees G1 as a language-model judge and calls it a contradiction | Medium, low | Wording fix in report Table 1.2 (section 2) |

**Open questions to settle early**

1. Does `api.laya.studio` let you choose the typed-decisions checkpoint, and what is its context limit? If it only offers a 512-token model, the card budget must drop to about 300 tokens. (section 4)
2. What are its rate limits, pricing and data-retention terms? Check them before sending any non-synthetic data. (section 10)
3. Is a node's input recoverable from the checkpoint before it for parallel branches and joins? (section 5)
4. Does the Rust result reader ignore unknown fields, or does the schema number need to change? (section 8)
5. How are G0 clue weights distributed, and can they be bucketed into tiers for ordering variant A? (section 7)
6. Is the 20 percent margin in the ship rule acceptable to the supervisor? (section 11)

**Out of scope for v0**

- Fine-tuning, LoRA, any training data pipeline, checkpoint selection, calibration, the fitted combiner and ordering variant B. These return only if the zero-shot result justifies them, using the stored answers and the generated dataset from this version.
- Loading Laya weights in the Sherlock process, ONNX export and `fetch-model`.
- Any use of Laya to name a cause, write an explanation or verify arithmetic.
- Widening the candidate list.
- Jev on the product path, or any hosted call outside G1.
- The multilingual checkpoint, other frameworks, hosted deployment and automatic repair, as in the report's scope table.
