"""Demo team #2 — order desk (spec FR-E1). Parallel branches.

parse -> (stock || pricing) -> assemble. `stock` and `pricing` run in the same superstep and
both feed `assemble`. Every node is plain code (spec 9.1). Faults arrive through runtime
context, ``context={"faults": [...]}``; their names are NOT prefixed with the node, so
Sherlock needs a node map to know which node a fault belongs to.

Loaded by path by ``langgraph dev``; must not import from the rest of ``sherlock_harness``.
"""

from __future__ import annotations

import operator
from dataclasses import dataclass, field
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

PRICES = {"widget": 10.0, "gadget": 25.0}
STOCK = {"widget": 10, "gadget": 4}
INPUT = {"order": "3 widget, 2 gadget"}


@dataclass
class Context:
    faults: list[str] = field(default_factory=list)


class State(TypedDict, total=False):
    order: str
    items: list[list]
    in_stock: bool
    total: float
    final_output: str
    notes: Annotated[list[str], operator.add]


def _faulty(runtime: Runtime[Context], fault: str) -> bool:
    return runtime.context is not None and fault in runtime.context.faults


def parse(state: State, runtime: Runtime[Context]) -> State:
    items = []
    for part in state["order"].split(","):
        qty, name = part.split()
        items.append([name, int(qty) + (1 if _faulty(runtime, "qty_off_by_one") else 0)])
    return {"items": items, "notes": ["parse: %d lines" % len(items)]}


def stock(state: State, runtime: Runtime[Context]) -> State:
    ok = all(STOCK[name] >= qty for name, qty in state["items"])
    if _faulty(runtime, "stale_inventory"):
        ok = False  # a stale snapshot says everything is sold out
    return {"in_stock": ok}


def pricing(state: State, runtime: Runtime[Context]) -> State:
    total = 0.0
    for name, qty in state["items"]:
        line = PRICES[name] * qty
        if qty >= 3 and not _faulty(runtime, "no_bulk_discount"):
            line *= 0.9  # 10% off lines of three or more
        total += line
    return {"total": round(total, 2)}


def assemble(state: State, runtime: Runtime[Context]) -> State:
    lines = ["Items: " + ", ".join(f"{q} {n}" for n, q in state["items"]), f"Total: {state['total']:.2f}"]
    if not _faulty(runtime, "drops_shipping_line"):
        lines.append("Ships: in stock" if state["in_stock"] else "Ships: backorder")
    if _faulty(runtime, "verbose_notes"):
        lines.append("(order processed)")  # cosmetic only
    return {"final_output": "\n".join(lines)}


NODES = ["parse", "stock", "pricing", "assemble"]

builder = StateGraph(State, context_schema=Context)
for _name, _fn in (("parse", parse), ("stock", stock), ("pricing", pricing), ("assemble", assemble)):
    builder.add_node(_name, _fn, metadata={"kind": "deterministic"})
builder.add_edge(START, "parse")
builder.add_edge("parse", "stock")
builder.add_edge("parse", "pricing")
builder.add_edge("stock", "assemble")
builder.add_edge("pricing", "assemble")
builder.add_edge("assemble", END)
graph = builder.compile()

CHECK = [
    {"type": "contains", "value": "Items: 3 widget, 2 gadget"},
    {"type": "contains", "value": "Total: 77.00"},
    {"type": "contains", "value": "Ships: in stock"},
]
