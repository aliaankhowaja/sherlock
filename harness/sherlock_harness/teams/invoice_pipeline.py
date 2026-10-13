"""Demo team #3 — invoice pipeline (spec FR-E1). Redundant repair path.

extract -> normalize -> validate -> post. `normalize` recomputes the amount from the raw text, so it
repairs a bad `extract` on its own. A bad extract is therefore harmless unless normalize has also
lost that repair (`normalize.trust_parsed`); then EITHER node, restored alone, fixes the run, so
the gold is two minimal sets. Plain code throughout (spec 9.1).

Loaded by path by ``langgraph dev``; must not import from the rest of ``sherlock_harness``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

RATE = 1.10  # EUR -> USD
INPUT = {"invoice": "INV-7: 1,200.50 EUR"}


@dataclass
class Context:
    faults: list[str] = field(default_factory=list)


class State(TypedDict, total=False):
    invoice: str
    ref: str
    raw: str
    amount: float
    usd: float
    status: str
    final_output: str


def _faulty(runtime: Runtime[Context], fault: str) -> bool:
    return runtime.context is not None and fault in runtime.context.faults


def extract(state: State, runtime: Runtime[Context]) -> State:
    ref, rest = state["invoice"].split(": ")
    raw = rest.split()[0]
    amount = float(raw.split(",")[0]) if _faulty(runtime, "extract.comma_split") else float(raw.replace(",", ""))
    return {"ref": ref, "raw": raw, "amount": amount}


def normalize(state: State, runtime: Runtime[Context]) -> State:
    if _faulty(runtime, "normalize.trust_parsed"):
        amount = state["amount"]
    else:
        amount = float(state["raw"].replace(",", ""))  # repairs a bad parse
    rate = 1.0 if _faulty(runtime, "normalize.stale_rate") else RATE
    return {"usd": round(amount * rate, 2)}


def validate(state: State, runtime: Runtime[Context]) -> State:
    if _faulty(runtime, "validate.reject_large") and state["usd"] > 1000:
        return {"status": "REJECTED"}
    return {"status": "OK"}


def post(state: State, runtime: Runtime[Context]) -> State:
    if state["status"] != "OK":
        return {"final_output": f"{state['ref']}: REJECTED"}
    usd = int(state["usd"]) if _faulty(runtime, "post.round_down") else f"{state['usd']:.2f}"
    return {"final_output": f"Posted {state['ref']}: {usd} USD"}


NODES = ["extract", "normalize", "validate", "post"]

builder = StateGraph(State, context_schema=Context)
builder.add_node("extract", extract)
builder.add_node("normalize", normalize)
builder.add_node("validate", validate)
builder.add_node("post", post)
builder.add_edge(START, "extract")
for _a, _b in zip(NODES, NODES[1:]):
    builder.add_edge(_a, _b)
builder.add_edge("post", END)
graph = builder.compile()

CHECK = [
    {"type": "contains", "value": "Posted INV-7: 1320.55 USD"},
    {"type": "not-contains", "value": "REJECTED"},
]
