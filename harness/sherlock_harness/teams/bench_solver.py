"""Replay-corpus team (docs/notes/replay-corpus-plan.md): one model call on a benchmark question.

read -> bias -> preface -> steer -> solve -> extract -> format, joined by ordinary edges. Only `solve` calls a
model: one chat-completions request to the OpenAI-compatible server at BENCH_URL (model BENCH_MODEL, bearer key
BENCH_API_KEY when set), or one Anthropic Messages request when BENCH_API=anthropic.
Every other node is plain code, so a replay that serves `solve` from the cassette reproduces the run
exactly.

Faults are switched on per run through context, `{"faults": [...]}`, and are named `<node>.<flag>`, so the patch
that undoes one is owned by its node. Headline faults sit on `extract` and `format` and always change
`final_output`. `bias.flag` is the decoy: it changes a field nothing downstream reads. `steer.flag` and
`preface.flag` change the `solve` request; only the abstain case uses them.

Loaded by path by ``langgraph dev``; must not import from the rest of ``sherlock_harness``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import TypedDict

import httpx
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

# No digits in any text `solve` sends besides the question: a short numeric key must not appear in the request.
INSTRUCTION = ("Solve the problem below. End your reply with one line of the form '#### <answer>', where <answer> "
               "is only the final short answer, with no units, no thousands separators and no extra words.")
WORDS = ("Solve the problem below. End your reply with one line of the form '#### <answer>', where <answer> "
         "is the final answer written out in words.")
PREFACE = "Think out loud before you answer."

HEADLINE = {  # each one changes final_output whenever the clean answer is non-empty
    "extract.drop_last": "slices one character too few off the answer",
    "format.prefix": "writes 'Answer: ' before the answer",
}
DECOY = "bias.flag"  # changes `lean`, which no node reads
REQUEST = {"steer.flag": "asks for the answer in words", "preface.flag": "adds a line before the instruction"}


@dataclass
class Context:
    faults: list[str] = field(default_factory=list)


class State(TypedDict, total=False):
    question: str
    problem: str
    lean: str
    preface: str
    instruction: str
    reply: str
    answer: str
    final_output: str


def _on(runtime: Runtime[Context], fault: str) -> bool:
    return runtime.context is not None and fault in runtime.context.faults


def ask(content: str) -> str:
    """The team's only network call."""
    body = {"model": os.environ["BENCH_MODEL"], "messages": [{"role": "user", "content": content}]}
    key = os.environ.get("BENCH_API_KEY")
    base = os.environ["BENCH_URL"].rstrip("/")
    with httpx.Client(timeout=300) as client:
        if os.environ.get("BENCH_API") == "anthropic":
            resp = client.post(base + "/messages", json={**body, "max_tokens": 8192},
                               headers={"x-api-key": key} if key else {})
            resp.raise_for_status()  # text blocks only: a thinking block is not the reply
            return "".join(b.get("text") or "" for b in resp.json().get("content") or [] if b.get("type") == "text")
        resp = client.post(base + "/chat/completions", json=body,
                           headers={"Authorization": f"Bearer {key}"} if key else {})
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"] or ""


_UNIT = re.compile(r",\s*the unit is\b.*$", re.I)
_GROUPED = re.compile(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?")


def tidy(answer: str) -> str:
    """One rule for both sides of `equals` (the benchmark key and the model's answer): trimmed; a SciBench unit
    suffix, dollar signs, markdown stars and a \\boxed{} wrapper removed; one trailing full stop and digit-grouping
    commas dropped; a single letter casefolded."""
    text = _UNIT.sub("", answer.strip()).replace("\\$", "").replace("$", "").strip(" *`")
    boxed = re.fullmatch(r"\\boxed\{(.*)\}", text)
    text = (boxed.group(1) if boxed else text).strip().removesuffix(".").strip()
    if _GROUPED.fullmatch(text):
        text = text.replace(",", "")
    return text.casefold() if len(text) == 1 else text


def short_answer(reply: str) -> str:
    """The first line after the last '####', tidied."""
    if "####" not in reply:
        return ""
    lines = reply.rsplit("####", 1)[1].strip().splitlines()
    return tidy(lines[0]) if lines else ""


def read(state: State, runtime: Runtime[Context]) -> State:
    return {"problem": state["question"]}


def bias(state: State, runtime: Runtime[Context]) -> State:
    return {"lean": "the first option" if _on(runtime, "bias.flag") else "none"}


def preface(state: State, runtime: Runtime[Context]) -> State:
    return {"preface": PREFACE if _on(runtime, "preface.flag") else ""}


def steer(state: State, runtime: Runtime[Context]) -> State:
    return {"instruction": WORDS if _on(runtime, "steer.flag") else INSTRUCTION}


def solve(state: State, runtime: Runtime[Context]) -> State:
    content = "\n\n".join(part for part in (state["preface"], state["instruction"], state["problem"]) if part)
    return {"reply": ask(content)}


def extract(state: State, runtime: Runtime[Context]) -> State:
    answer = short_answer(state["reply"])
    return {"answer": answer[:-1] if _on(runtime, "extract.drop_last") else answer}


def format_answer(state: State, runtime: Runtime[Context]) -> State:
    answer = state["answer"]
    return {"final_output": "Answer: " + answer if _on(runtime, "format.prefix") else answer}


NODES = ["read", "bias", "preface", "steer", "solve", "extract", "format"]
_FNS = [read, bias, preface, steer, solve, extract, format_answer]

builder = StateGraph(State, context_schema=Context)
for name, fn in zip(NODES, _FNS):
    builder.add_node(name, fn, metadata={"kind": "llm" if name == "solve" else "deterministic"})
builder.add_edge(START, NODES[0])
for upstream, downstream in zip(NODES, NODES[1:]):
    builder.add_edge(upstream, downstream)
builder.add_edge(NODES[-1], END)
graph = builder.compile()
