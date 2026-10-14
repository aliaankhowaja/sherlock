"""G1: the optional LLM shortlist (spec 5.4; FR-G1.1-G1.6, NFR-5, NFR-19) and per-gate attribution.

G1 asks a swappable OpenAI-compatible model which nodes of a failed run look suspicious. The call has ZERO
tools, sees node summaries that went through the FR-R8 redaction, and returns node names only. Its answer is
a hint: it changes the ORDER of G3 trials, never which nodes are searched, never a verdict (a nomination is
weaker evidence than a G2 arrow or a G3 trial and labels nothing). Several samples can only widen the list
(union). A model that fails, answers nonsense or names nothing falls back to G0-only ordering, and the
artifact says so (open item 3). With G1 off nothing here runs and the diagnosis is unchanged (FR-G1.6).

Known limitation (NFR-19): node outputs are untrusted text sent to the model, so a prompt injected into a
run can steer the shortlist. That can only reorder trials, never hide a culprit from the search.
"""

import json
import os
import re
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from sherlock.g3 import clip
from sherlock.redact import REDACTED, redact_body
from sherlock.search import _supersteps

MAX_NOMINEES = 5
SYSTEM = ("You help debug a failed multi-step LLM pipeline. You get the final output that failed its check and a "
          "summary of what each node wrote. Name the nodes most likely to have caused the failure, at most "
          f"{MAX_NOMINEES}. Reply with a JSON list of node names only, for example [\"a\", \"b\"]. You have no tools.")


@dataclass
class G1Result:
    enabled: bool = True
    model: str | None = None
    endpoint: str | None = None  # scheme + host only: never the key or a path with secrets
    samples_requested: int = 0
    samples_ok: int = 0
    per_sample: list[list[str]] = field(default_factory=list)
    nominated: list[str] = field(default_factory=list)  # union over samples, most-named first
    ignored: list[str] = field(default_factory=list)  # names the model gave that are not nodes on the path
    prompt_chars: int = 0
    redactions: int = 0
    fallback: str | None = None  # "g0_only" when nothing usable came back
    error: str | None = None
    note: str = ""

    def to_dict(self):
        return {"enabled": self.enabled, "model": self.model, "endpoint": self.endpoint, "strength": "weak",
                "tools_offered": 0, "samples_requested": self.samples_requested, "samples_ok": self.samples_ok,
                "per_sample": self.per_sample, "nominated": self.nominated, "ignored": self.ignored,
                "prompt_chars": self.prompt_chars, "redactions": self.redactions, "fallback": self.fallback,
                "error": self.error, "note": self.note}


def disabled() -> dict:
    return {"enabled": False, "strength": "weak", "tools_offered": 0, "nominated": [], "fallback": None,
            "note": "G1 was not asked for; the diagnosis uses G0 clues and G3 trials only"}


def node_summaries(history: list[dict], output_key: str, final_output: str, failures: list[str]) -> tuple[str, int]:
    """The user message: the failed output, the failed check reasons, and each node's clipped writes, redacted."""
    lines = []
    for step in _supersteps(history):
        for task in step:
            result = {k: clip(v, 300, 8) for k, v in (task.get("result") or {}).items()}
            lines.append({"node": task["name"], "wrote": result, "error": task.get("error")})
    payload = {"final_output_key": output_key, "final_output": clip(final_output, 600),
               "failed_checks": [clip(f, 200) for f in failures], "nodes_in_order": lines}
    text = redact_body(json.dumps(payload, default=str).encode()).decode()
    return text, text.count(REDACTED)


def parse_nominations(text: str, known: list[str]) -> tuple[list[str], list[str]]:
    """Node names from a reply: a JSON list (or {"nodes": [...]}) first, else known names found in the text."""
    names: list[str] = []
    try:
        parsed = json.loads(text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip())
        if isinstance(parsed, dict):
            parsed = next((v for v in parsed.values() if isinstance(v, list)), [])
        names = [str(x) for x in parsed] if isinstance(parsed, list) else []
    except ValueError:
        names = [n for n in known if re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])", text)]
    ok = list(dict.fromkeys(n for n in names if n in known))
    return ok[:MAX_NOMINEES], [n for n in dict.fromkeys(names) if n not in known][:MAX_NOMINEES]


def _post(url: str, key: str | None, body: dict, timeout: float) -> str:
    req = urllib.request.Request(url.rstrip("/") + "/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json", **({"Authorization": f"Bearer {key}"} if key else {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - the user's own endpoint
        return json.loads(resp.read())["choices"][0]["message"]["content"] or ""


def run_g1(history: list[dict], output_key: str, final_output: str, failures: list[str], known_nodes: list[str], *,
           url: str, model: str, samples: int = 1, key: str | None = None, post=_post, timeout: float = 30.0) -> G1Result:
    """Ask the model `samples` times (never with tools) and union the node names. Never raises."""
    key = key or os.environ.get("SHERLOCK_G1_API_KEY") or os.environ.get("OPENAI_API_KEY")
    parts = urlsplit(url)
    res = G1Result(model=model, endpoint=f"{parts.scheme}://{parts.netloc}", samples_requested=max(samples, 1))
    user, res.redactions = node_summaries(history, output_key, final_output, failures)
    res.prompt_chars = len(SYSTEM) + len(user)
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
    counts: Counter = Counter()
    errors = []
    for i in range(res.samples_requested):
        body = {"model": model, "messages": messages, "temperature": 0 if i == 0 else 0.7}  # no `tools` key, ever
        try:
            ok, ignored = parse_nominations(post(url, key, body, timeout), known_nodes)
        except (OSError, ValueError, KeyError, IndexError, urllib.error.URLError) as exc:
            errors.append(f"sample {i + 1}: {type(exc).__name__}: {str(exc)[:120]}")
            continue
        res.samples_ok += 1
        res.per_sample.append(ok)
        res.ignored += [n for n in ignored if n not in res.ignored]
        counts.update(ok)
    first = {n: i for i, n in enumerate(dict.fromkeys(n for s in res.per_sample for n in s))}
    res.nominated = sorted(counts, key=lambda n: (-counts[n], first[n]))  # union: more samples only ever add names
    res.error = "; ".join(errors) or None
    if not res.nominated:
        res.fallback = "g0_only"
        res.note = ("G1 gave no usable node name" + (f" ({res.error})" if res.error else "")
                    + "; the order comes from G0 clues only. The guaranteed search is unaffected.")
    else:
        res.note = "G1 nominations only reorder trials; they are weaker evidence than a G2 arrow or a G3 trial"
    return res
