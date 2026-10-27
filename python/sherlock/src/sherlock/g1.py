"""G1 suspicion scorer (docs/notes/g1-laya-spec.md, v0): one score per surviving candidate, used only to order G3 trials.

The scores feed `order_candidates` as the tie-breaker inside equal G0 clue scores (ordering variant A), so a clue
always outranks a score. G1 never names a cause, never adds or removes a candidate, and never fails a diagnosis.
Backends: `laya` (the Laya System One API, zero-shot: the score is P(needs_restore = yes)) and `fake` (a hash of the
node name, no network, for tests). Today's hosted shortlist stays in gates.py.

The Laya call is the only network use in a diagnosis, and only with `--g1 laya`. A non-local endpoint also needs
`--g1-allow-remote`, because the card text leaves the machine. Answers are rounded to 4 decimals and cached on disk
by card, so a re-run gives the same scores offline. The API key comes from the environment, never from a flag, and
is never written anywhere.

Each candidate is shown to the scorer as a node card: a short, redacted, deterministic text that puts the node's
failed behaviour next to its known-good behaviour. The recording does not say which node made a tool call, so
cards carry no tool fields; nothing in a run names a node's role, so there is no role field either.
"""

import difflib
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from sherlock import __version__
from sherlock.redact import redact_body
from sherlock.sources import node_outputs

CARD_CHARS = 2400  # 800 tokens at a conservative 1 token per 3 characters (spec 5, rule 3)
SNIPPET = 200
LOCAL = ("localhost", "127.0.0.1", "::1")
DEFAULTS = {"endpoint": "https://api.laya.studio", "path": "/v1/systemone", "model": "typed-decisions",
            "timeout_ms": 10000, "total_timeout_ms": 60000}  # typed-decisions: English, 1,024-token context
QUESTION_VERSION = "g1_questions_v1"
QUESTIONS = {  # the wording is part of QUESTION_VERSION: any change needs a new version. No tool_relevance (see above)
    "output_effect": {"type": "choice", "instructions": "How does the failed output differ from the good output?",
                      "criteria": {"same": "identical in meaning and content",
                                   "cosmetic": "only wording, order or formatting differs",
                                   "meaningful": "facts, values or content differ"}},
    "fault_origin": {"type": "choice", "instructions": "Where did the difference start?",
                     "criteria": {"originated_here": "this node introduced the difference",
                                  "inherited": "the node's input already differed and the node behaved correctly on it",
                                  "none": "no difference"}},
    "dropped_input": {"type": "noul", "instructions": "Did the node omit information that was in its input?"},
    "invented_output": {"type": "noul", "instructions": "Does the output contain content its input does not support?"},
    "pass_through": {"type": "noul", "instructions": "Did the node only pass its input along unchanged?"},
    "needs_restore": {"type": "noul",
                      "instructions": "Must this node be restored to its good behaviour for the run to pass the check?"},
}
SAMPLE_CARD = """NODE: extractor
CHECK: contains "ISO 27001"; contains "Data region: EU"; not contains "SOC 2"
FLAGS: output_same_as_good=no input_same_as_good=no errored=no upstream_differs=[retriever]
DIFF: removed "ISO 27001" | added "SOC 2 (current)"
OUT_FAILED: {"certs": ["SOC 2"], "region": "EU"}
OUT_GOOD: {"certs": ["ISO 27001"], "region": "EU"}
IN_FAILED: docs=[doc1: "SOC 2 certificate ... expired in 2023", doc2: "All data stored in the EU"]"""


def _redacted(value):
    return json.loads(redact_body(json.dumps(value, default=str).encode()))


def _flat(value) -> str:
    return " ".join(json.dumps(_redacted(value), sort_keys=True, ensure_ascii=False).split())


def _words(value) -> list[str]:
    if isinstance(value, dict):
        return [w for k in sorted(value) for w in _words(value[k])]
    if isinstance(value, list):
        return [w for v in value for w in _words(v)]
    return str(value).split()


def _cut(text: str, keep: int) -> str:
    if len(text) <= keep:
        return text
    head = keep // 2
    return f"{text[:head]}[...{len(text) - keep} chars cut...]{text[len(text) - (keep - head):]}"


def _diff(failed, good) -> str:
    """Word-level over the values: what the good output has that the failed one lacks (removed), and the reverse."""
    a, b = _words(_redacted(good)), _words(_redacted(failed))
    removed, added = [], []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op != "equal":
            removed += [" ".join(a[i1:i2])] if i2 > i1 else []
            added += [" ".join(b[j1:j2])] if j2 > j1 else []
    if not removed + added:
        return "none"
    side = lambda parts: json.dumps(_cut(" ... ".join(parts), SNIPPET), ensure_ascii=False)  # noqa: E731
    return f"removed {side(removed)} | added {side(added)}"


def _first_runs(history: list[dict]) -> tuple[dict, dict, dict]:
    """node -> superstep of its first run, the state it started from, its first error. Oldest first."""
    step, before, error = {}, {}, {}
    for i, snap in enumerate(reversed(history)):
        for t in snap.get("tasks") or []:
            if not t["name"].startswith("__"):
                step.setdefault(t["name"], i)
                before.setdefault(t["name"], snap.get("values"))
                if t.get("error"):
                    error.setdefault(t["name"], str(t["error"]))
    return step, before, error


def node_card(node: str, history: list[dict], good_history: list[dict] | None, checks, mask: bool = False):
    """(card text, truncated). A pure function of its inputs: the same run gives the same card, byte for byte."""
    step, before, error = _first_runs(history)
    out = node_outputs(history)
    good_out = node_outputs(good_history) if good_history else {}
    good_before = _first_runs(good_history)[1] if good_history else {}
    one = lambda writes: writes[0] if len(writes) == 1 else writes  # noqa: E731
    yn = lambda same: "unknown" if same is None else "yes" if same else "no"  # noqa: E731
    same_out = out.get(node) == good_out[node] if node in good_out else None
    same_in = before.get(node) == good_before[node] if node in good_before else None
    upstream = (f"[{', '.join(n for n in out if step[n] < step[node] and out[n] != good_out.get(n))}]"
                if good_history else "unknown")
    fields = [  # (priority, line): P0 is never cut, the highest number is cut first (spec 5)
        (0, f"NODE: {node}"),
        (0, f"FLAGS: output_same_as_good={yn(same_out)} input_same_as_good={yn(same_in)} "
            f"errored={yn(node in error)} upstream_differs={upstream}"),
        (1, "CHECK: " + "; ".join(f"{a.get('type')} {_flat(a.get('value'))}" for a in checks.assertions)),
        *([(1, "DIFF: " + _diff(one(out[node]), one(good_out[node])))] if node in good_out else []),
        *([(1, f"ERROR: {error[node]}")] if node in error else []),
        (2, f"OUT_FAILED: {_flat(one(out.get(node, [])))}"),
        *([(2, f"OUT_GOOD: {_flat(one(good_out[node]))}")] if node in good_out else []),
        (3, f"IN_FAILED: {_flat(before.get(node))}"),
    ]
    fields = [(p, redact_body(line.encode()).decode()) for p, line in fields]
    if mask:  # shortcut control (spec 9): the same card with every node name replaced by a stable ID
        for n in sorted(out, key=len, reverse=True):
            alias = "node_" + hashlib.sha256(n.encode()).hexdigest()[:6]
            fields = [(p, re.sub(rf"(?<![\w-]){re.escape(n)}(?![\w-])", alias, line)) for p, line in fields]
    over = sum(len(line) + 1 for _, line in fields) - CARD_CHARS
    truncated = over > 0
    for prio in (3, 2, 1):
        for i in reversed(range(len(fields))):
            p, line = fields[i]
            if over > 0 and p == prio and len(line) > 40:
                fields[i] = (p, _cut(line, max(40, len(line) - over - 30)))  # 30: room for the cut marker
                over -= len(line) - len(fields[i][1])
    return "\n".join(line for _, line in fields), truncated


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):  # a redirect could carry the card and the key to another host
        return None


def blocked(cfg: dict) -> str | None:
    """Why G1 may not call this endpoint at all, checked before any request is built."""
    host = urlsplit(cfg["endpoint"]).hostname or ""
    if host not in LOCAL and not cfg.get("allow_remote"):
        return f"{host} is not local, so card text would leave the machine; pass --g1-allow-remote to allow it"
    if host not in LOCAL and not os.environ.get("LAYA_API_KEY"):
        return "LAYA_API_KEY is not set"
    return None


def ask(cfg: dict, card: str, timeout_s: float) -> dict:
    """POST one card with the question set; the raw response. One retry on a connection error, 429 or 5xx."""
    key = os.environ.get("LAYA_API_KEY")
    body = {"state": card, "questions": QUESTIONS, **({"model": cfg["model"]} if cfg.get("model") else {})}
    req = urllib.request.Request(cfg["endpoint"].rstrip("/") + cfg["path"], json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "User-Agent": f"sherlock-rec/{__version__}",
                                  **({"Authorization": f"Bearer {key}"} if key else {})})
    for attempt in (0, 1):
        try:
            with urllib.request.build_opener(_NoRedirect).open(req, timeout=timeout_s) as resp:  # noqa: S310
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if attempt or not (exc.code == 429 or exc.code >= 500):
                raise
        except urllib.error.URLError:
            if attempt:
                raise
        time.sleep(1)  # fixed, no jitter: behaviour stays reproducible
    raise AssertionError("unreachable")


def parse(raw: dict) -> tuple[dict, bool]:
    """(answers as option -> probability, rounded to 4 decimals; truncated). ValueError if anything is malformed."""
    answers = {}
    try:
        for qid, q in QUESTIONS.items():
            a = raw["answers"][qid]
            probs = ({"yes": a["noul"], "no": 1 - a["noul"]} if q["type"] == "noul"
                     else {o: a["probabilities"][o] for o in q["criteria"]})
            ok = all(isinstance(p, int | float) and 0 <= p <= 1 for p in probs.values())
            if not ok or abs(sum(probs.values()) - 1) > 0.02:
                raise ValueError(f"answer {qid} is not a probability distribution")
            answers[qid] = {o: round(p, 4) for o, p in probs.items()}
        usage = raw.get("usage") or {}
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"malformed response: missing {exc}") from exc
    # input_tokens counts the card once per question, so it says nothing about truncation; these fields do
    return answers, bool(usage.get("truncated") or usage.get("state_tokens_dropped") or usage.get("truncated_questions"))


def cached_answers(cfg: dict, card: str, timeout_s: float) -> tuple[dict, bool]:
    """({answers, truncated, model}, cache hit). The cache holds answers only: never the card, never the key."""
    key = json.dumps([urlsplit(cfg["endpoint"]).netloc, cfg["path"], cfg.get("model"), QUESTION_VERSION, card])
    path = Path(cfg["cache_dir"]) / f"{hashlib.sha256(key.encode()).hexdigest()}.json" if cfg.get("cache_dir") else None
    if path and path.is_file():
        return json.loads(path.read_text(encoding="utf-8")), True
    raw = ask(cfg, card, timeout_s)
    answers, truncated = parse(raw)
    entry = {"answers": answers, "truncated": truncated, "model": raw.get("model")}
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entry, sort_keys=True), encoding="utf-8")
    return entry, False


def fake_score(node: str) -> float:
    return round(int(hashlib.sha256(node.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF, 4)


def rank(cfg: dict, candidates: list[str], card_of) -> dict:
    """The artifact's `g1` object. `scores` is in rank order: score high to low, then name; null scores last.
    `card_of(node)` gives (card, truncated); a card that cannot be built gives a null score (C8), never an error."""
    start = time.monotonic()
    cfg = {**DEFAULTS, **cfg}
    laya = cfg["backend"] == "laya"
    out = {"backend": cfg["backend"], "status": "skipped", "order_variant": "A", "scores": [], "truncated_cards": [],
           "card_hashes": {}}
    if laya:
        out.update(question_version=QUESTION_VERSION, endpoint_host=urlsplit(cfg["endpoint"]).hostname,
                   model=cfg.get("model"), client_version=__version__, server_version=None,
                   cache={"hits": 0, "misses": 0} if cfg.get("cache_dir") else "disabled")
    if len(candidates) < 2:
        return {**out, "ms": 0}
    problem = blocked(cfg) if laya else None
    scores, answers, called = {}, {}, False
    for n in candidates if not problem else ():
        try:
            card, truncated = card_of(n)
        except Exception:  # noqa: BLE001 - C8: G1 must never fail the diagnosis
            scores[n] = None
            continue
        out["card_hashes"][n] = hashlib.sha256(card.encode()).hexdigest()[:16]
        out["truncated_cards"] += [n] if truncated else []
        if not laya:
            scores[n] = fake_score(n)
            continue
        left = cfg["total_timeout_ms"] / 1000 - (time.monotonic() - start)
        if left <= 0:
            problem = f"the G1 time limit of {cfg['total_timeout_ms']} ms was reached"
            break
        try:
            entry, hit = cached_answers(cfg, card, min(cfg["timeout_ms"] / 1000, left))
        except Exception as exc:  # noqa: BLE001 - C8: one bad card is a null score; a dead endpoint stops G1
            if isinstance(exc, OSError) and (not called or getattr(exc, "code", None) in (401, 402, 403)):
                problem = f"the endpoint failed: {type(exc).__name__} {getattr(exc, 'code', '')}".rstrip()
                break
            scores[n] = None
            continue
        called = True
        if out["cache"] != "disabled":
            out["cache"]["hits" if hit else "misses"] += 1
        out["model"] = entry["model"]
        answers[n] = entry["answers"]
        if entry["truncated"] and n not in out["truncated_cards"]:
            out["truncated_cards"].append(n)
        # a card the server cut may have lost its end or the questions, so it gets no score
        scores[n] = None if entry["truncated"] else entry["answers"]["needs_restore"]["yes"]
    if not problem and all(v is None for v in scores.values()):
        problem = "no card got a score"
    if problem:  # C8: the run goes on exactly as if G1 were off
        out.update(status="unavailable", reason=problem)
    else:
        order = sorted(candidates, key=lambda n: (scores[n] is None, -(scores[n] or 0.0), n))
        out.update(status="ok" if None not in scores.values() else "partial",
                   scores=[{"node": n, "score": scores[n], **({"answers": answers[n]} if n in answers else {})}
                           for n in order])
    out["ms"] = round(1000 * (time.monotonic() - start))
    return out
