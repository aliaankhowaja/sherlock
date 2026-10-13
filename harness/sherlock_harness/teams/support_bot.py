"""Demo team #4 — support bot, the LLM-node team (spec FR-E1, 9.1).

prep -> ask -> fmt. `ask` makes a real chat-completions call (httpx) to the OpenAI-compatible
server named by STUB_URL; the evaluation points it at a local echo stub, never a provider.
Faults in `prep`/`fmt` are deterministic; the fault in `ask` is a prompt variant, so combining it
with another fault produces request bodies that were never recorded (spec 9.1: Sherlock must abstain).

Loaded by path by ``langgraph dev``; must not import from the rest of ``sherlock_harness``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TypedDict

import httpx
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

INPUT = {"question": "what is the vendor status"}


@dataclass
class Context:
    faults: list[str] = field(default_factory=list)


class State(TypedDict, total=False):
    question: str
    prompt: str
    answer: str
    final_output: str


def _faulty(runtime: Runtime[Context], fault: str) -> bool:
    return runtime.context is not None and fault in runtime.context.faults


def prep(state: State, runtime: Runtime[Context]) -> State:
    question = state["question"]
    return {"prompt": question[:8] if _faulty(runtime, "prep.truncate") else question}


def ask(state: State, runtime: Runtime[Context]) -> State:
    content = state["prompt"]
    if _faulty(runtime, "ask.terse_instruction"):
        content = "Answer in one word: " + content
    body = {"model": "stub-1", "messages": [{"role": "user", "content": content}]}
    with httpx.Client() as client:
        reply = client.post(os.environ["STUB_URL"] + "/v1/chat/completions", json=body).json()
    return {"answer": reply["choices"][0]["message"]["content"]}


def fmt(state: State, runtime: Runtime[Context]) -> State:
    text = f"ANSWER: {state['answer']}"
    if _faulty(runtime, "fmt.trailing_newline"):
        text += "\n"  # cosmetic only
    return {"final_output": text.upper() if _faulty(runtime, "fmt.shout") else text}


NODES = ["prep", "ask", "fmt"]

builder = StateGraph(State, context_schema=Context)
builder.add_node("prep", prep)
builder.add_node("ask", ask)
builder.add_node("fmt", fmt)
builder.add_edge(START, "prep")
builder.add_edge("prep", "ask")
builder.add_edge("ask", "fmt")
builder.add_edge("fmt", END)
graph = builder.compile()

CHECK = [{"type": "contains", "value": "ANSWER: echo: what is the vendor status"}]
