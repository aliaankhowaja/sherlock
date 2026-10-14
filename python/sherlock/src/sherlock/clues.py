"""G0 cheap clues, G2 path check and candidate ordering (spec 5.4; FR-G0.1-G0.5, FR-G2.1-G2.3, FR-D12).

Pure and deterministic: no server, no model, no I/O. Everything here reads the recorded tape
(checkpoint history, plus tool calls from the cassette). Clues are NOT verdicts: they are shown as
evidence, they may reorder the search and, when `widens` is set (extractive, empty, schema-invalid,
error), they may bring a node the pruning dropped back into the candidate list (FR-G0.5). Only G3
decides.

Extractive check (FR-G0.3, open item 6): numbers, URLs and quoted strings in the final output that
appear in no upstream packet (the run input and everything written before the output was written).
Paraphrase never fires it, since only closed tokens are compared. Known false-positive source:
numbers the writer derives (a sum, a count, spelled-out digits).
"""

import json
import re
from dataclasses import dataclass, field

from sherlock.search import _supersteps

SKIP_KEYS = {"notes"}  # bookkeeping channel, not a packet
URL = re.compile(r"https?://[^\s\"'<>)\]]+")
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?%?")
QUOTED = re.compile(r"\"([^\"]{2,})\"|“([^”]{2,})”")


@dataclass
class Clue:
    kind: str  # node_error | empty_output | malformed_json | extractive | loop | tool_error | schema_invalid_tool_call | differs_from_passing_run
    node: str | None
    detail: str
    weight: int = 1  # ordering strength (FR-D12)
    widens: bool = False  # may widen the candidate list (FR-G0.5)
    evidence: dict = field(default_factory=dict)

    def to_dict(self):
        return {"kind": self.kind, "node": self.node, "detail": self.detail, "weight": self.weight,
                "widens": self.widens, "evidence": self.evidence, "strength": "clue"}


def _text(value) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(value)


def _writer_index(steps, output_key):
    return max((i for i, step in enumerate(steps) if any(output_key in (t.get("result") or {}) for t in step)),
               default=None)


def _tokens(text: str) -> set[str]:
    found = set(URL.findall(text))
    found |= {n.rstrip(",") for n in NUMBER.findall(text)}
    found |= {a or b for a, b in QUOTED.findall(text)}
    return {t.rstrip(".,;:").lower() for t in found if t}


def _number_set(text: str) -> set[str]:
    return {n.rstrip(",").lower() for n in NUMBER.findall(text)}


def extractive_tokens(upstream: list[str], output: str) -> list[str]:
    """Closed tokens (numbers, URLs, quoted strings) of `output` that no upstream text contains."""
    haystack = "\n".join(upstream).lower()
    numbers = _number_set(haystack)
    missing = []
    for tok in sorted(_tokens(output)):
        if NUMBER.fullmatch(tok):
            if tok not in numbers:
                missing.append(tok)
        elif tok not in haystack:
            missing.append(tok)
    return missing


def history_clues(history: list[dict], output_key: str) -> list[Clue]:
    """G0 clues from the recorded per-node events: errors, empty values, malformed JSON, extractive, loops."""
    steps = _supersteps(history)
    clues: list[Clue] = []
    seen_results: dict[str, list[str]] = {}
    for step in steps:
        for task in step:
            node, result = task["name"], task.get("result") or {}
            if task.get("error"):
                clues.append(Clue("node_error", node, f"{node} raised: {str(task['error'])[:200]}", 3, True,
                                  {"error": str(task["error"])[:500]}))
            for key, value in result.items():
                if key in SKIP_KEYS:
                    continue
                if value in ("", [], {}, None):
                    clues.append(Clue("empty_output", node, f"{node} wrote an empty `{key}`", 2, True, {"key": key}))
                elif isinstance(value, str) and value.lstrip()[:1] in ("{", "["):
                    try:
                        json.loads(value)
                    except ValueError as exc:
                        clues.append(Clue("malformed_json", node, f"{node} wrote malformed JSON in `{key}`: {exc}",
                                          2, True, {"key": key}))
            seen_results.setdefault(node, []).append(_text(result))
    for node, results in seen_results.items():
        repeats = len(results) - len(set(results))
        if repeats:
            clues.append(Clue("loop", node, f"{node} ran {len(results)} times and repeated itself {repeats} time(s) "
                                            "with no change in what it wrote", 2, False, {"runs": len(results)}))
    clues.extend(_extractive(steps, output_key))
    return clues


def _extractive(steps, output_key) -> list[Clue]:
    w = _writer_index(steps, output_key)
    if w is None:
        return []
    writers = [t for t in steps[w] if output_key in (t.get("result") or {})]
    output = _text(writers[0]["result"][output_key])
    upstream = []
    for step in steps[:w]:
        for t in step:
            upstream += [_text(v) for k, v in (t.get("result") or {}).items() if k not in SKIP_KEYS]
    missing = extractive_tokens(upstream, output)
    if not missing:
        return []
    node = writers[0]["name"]
    return [Clue("extractive", node, f"`{output_key}` holds {', '.join(missing)} which no upstream packet contains",
                 3, True, {"tokens": missing, "output_key": output_key})]


def tool_call_clues(calls: list[dict], chunks) -> list[Clue]:
    """G0.1 from recorded tool calls (programmatic only). `chunks(call_id)` returns the stored payload chunks.

    The cassette does not say which node made a call, so these clues name no node.
    """
    clues = []
    for call in calls:
        if call.get("kind") != "tool":
            continue
        name = call["name"]
        try:
            args = json.loads(call["request"])
            if not isinstance(args, dict):
                clues.append(Clue("schema_invalid_tool_call", None, f"tool {name} was called with non-object arguments",
                                  3, True, {"tool": name}))
        except (TypeError, ValueError):
            clues.append(Clue("schema_invalid_tool_call", None, f"tool {name} was called with arguments that are not JSON",
                              3, True, {"tool": name}))
        if call.get("status") == 1:
            parts = chunks(call["id"])
            text = parts[1].decode("utf-8", "replace") if len(parts) > 1 else ""
            kind = "schema_invalid_tool_call" if "validation" in text.lower() else "tool_error"
            clues.append(Clue(kind, None, f"tool {name} raised: {text[:200]}", 3, True, {"tool": name}))
    return clues


def differs_clues(differing: list[str], same: list[str], good_thread: str) -> list[Clue]:
    """FR-D12 / FR-K1: nodes whose output differs from the prior successful run."""
    return [Clue("differs_from_passing_run", n, f"{n} wrote something different from the passing run {good_thread}", 2,
                 False, {"good_thread": good_thread}) for n in differing]


# --- G2: the path check ---------------------------------------------------------------------------------

@dataclass
class PathCheck:
    kept: list[str]
    rejected: dict[str, str]  # suspect as given -> why it was discarded
    arrows: dict[str, list[str]]  # kept node -> the recorded arrow [from, to]

    def to_dict(self):
        return {"kept": self.kept, "rejected": self.rejected, "arrows": self.arrows}


def path_check(history: list[dict], output_key: str, suspects: list[str]) -> PathCheck:
    """G2: every suspect must name a recorded arrow ("A's output was used by B"), else it is discarded.

    A suspect is `A` (its arrow is to the next node on the tape, or to the output if A wrote it) or
    `A->B`. Deterministic; it only ever rejects (FR-G2.3).
    """
    steps = _supersteps(history)
    first, last = {}, {}
    for i, step in enumerate(steps):
        for t in step:
            first.setdefault(t["name"], i)
            last[t["name"]] = i
    wrote = {t["name"]: any(k not in SKIP_KEYS for k in (t.get("result") or {})) for s in steps for t in s}
    w = _writer_index(steps, output_key)
    kept, rejected, arrows = [], {}, {}
    for s in suspects:
        src, _, dst = (p.strip() for p in s.partition("->"))
        if src not in first:
            rejected[s] = f"{src} never ran in the recorded run, so no arrow leaves it"
        elif dst and dst not in first:
            rejected[s] = f"{dst} never ran in the recorded run, so nothing could have used {src}'s output"
        elif not wrote.get(src):
            rejected[s] = f"{src} recorded no output, so there is no arrow from it"
        elif dst and first[src] >= last[dst]:
            rejected[s] = f"{src} did not run before {dst} on the tape, so {dst} cannot have used its output"
        elif w is not None and first[src] > w:
            rejected[s] = f"{src} ran after `{output_key}` was written, so it cannot have shaped it"
        else:
            if dst:
                arrow = [src, dst]
            elif w is not None and first[src] == w:
                arrow = [src, output_key]
            else:
                nxt = next((t["name"] for step in steps[last[src] + 1:] for t in step), None)
                arrow = [src, nxt or output_key]
            if src not in kept:
                kept.append(src)
            arrows[src] = arrow
    return PathCheck(kept, rejected, arrows)


# --- ordering (FR-D12) ------------------------------------------------------------------------------------

def order_candidates(candidates: list[str], clues: list[Clue], nominated: list[str] = ()) -> list[str]:
    """Strongest G0 clues first, then G1 nominations (weaker: they only break ties between equal clue scores,
    most-named first); remaining ties keep the recorded order. Speed only: G3 still decides."""
    score = {n: 0 for n in candidates}
    for c in clues:
        if c.node in score:
            score[c.node] += c.weight
    rank = {n: i for i, n in enumerate(nominated)}
    return sorted(candidates, key=lambda n: (-score[n], rank.get(n, len(rank))))
