"""Declarative builder for the large demo teams (not a team itself; spec FR-E1, scale demo).

A team file declares its nodes in execution order with `@P.node(name, after=..., faults={flag: text})`. Each node is a
plain function ``fn(state, f) -> dict`` where ``f("flag")`` says whether that fault is switched on for the run. The kit
wires the LangGraph (fan-out, fan-in, conditional routes), tags node kinds, and collects the fault catalogue, so a
40-node team needs no hand-written graph code. Fault names are ``node.flag`` (default) or the bare flag
(``prefixed=False``, which makes Sherlock need a node map, like order_desk).

Team files are loaded by path by ``langgraph dev``; they reach this file through ``sys.path`` (see ``use_kit``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, TypedDict

import httpx
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime


@dataclass
class Context:
    faults: list[str] = field(default_factory=list)


def ask_llm(content: str) -> str:
    """One chat-completions call to the OpenAI-compatible server in STUB_URL (the evaluation's echo stub)."""
    body = {"model": "stub-1", "messages": [{"role": "user", "content": content}]}
    with httpx.Client(verify=False) as client:  # plain http to the stub; skips the ~1s SSL-context build
        reply = client.post(os.environ["STUB_URL"] + "/v1/chat/completions", json=body).json()
    return reply["choices"][0]["message"]["content"]


class Pipeline:
    def __init__(self, keys: str):
        self.keys = keys.split()
        self.order: list[str] = []
        self.kinds: dict[str, str] = {}
        self.faults: dict[str, tuple[str, str, bool]] = {}  # fault -> (node, description, harmful)
        self._specs: list[dict] = []

    def node(self, name, after=(), *, any_of=(), kind="deterministic", faults=None, harmless=(),
             route=None, to=None, prefixed=True):
        """Register a node. `after`: wait for all of these; `any_of`: run when any of these ran (branch joins).
        `route(state)->label` with `to={label: node}` makes this node a conditional router. `faults` maps flag ->
        description; flags listed in `harmless` are cosmetic (they do not change what Z checks)."""
        after = [after] if isinstance(after, str) else list(after)

        def deco(fn):
            fault_names = {}
            for flag, text in (faults or {}).items():
                full = f"{name}.{flag}" if prefixed else flag
                assert full not in self.faults, f"duplicate fault {full}"
                fault_names[flag] = full
                self.faults[full] = (name, text, flag not in harmless)
            self.order.append(name)
            self.kinds[name] = kind
            self._specs.append({"name": name, "fn": fn, "after": after, "any_of": list(any_of),
                                "names": fault_names, "route": route, "to": to})
            return fn
        return deco

    def compile(self):
        state = TypedDict("State", {k: Any for k in self.keys + ["final_output"]}, total=False)
        builder = StateGraph(state, context_schema=Context)
        for spec in self._specs:
            builder.add_node(spec["name"], self._wrap(spec), metadata={"kind": self.kinds[spec["name"]]})
        routed = {(s["name"], dst) for s in self._specs if s["to"] for dst in s["to"].values()}  # router edges
        for spec in self._specs:
            name = spec["name"]
            srcs = [s for s in spec["after"] if (s, name) not in routed]
            if len(spec["after"]) == 1 and not srcs:
                pass  # reached only through its router's conditional edge
            elif not srcs and not spec["any_of"]:
                builder.add_edge(START, name)
            elif len(srcs) == 1:
                builder.add_edge(srcs[0], name)
            elif srcs:
                builder.add_edge(srcs, name)
            for src in spec["any_of"]:
                builder.add_edge(src, name)
            if spec["route"]:
                builder.add_conditional_edges(name, spec["route"], spec["to"])
        last = self._specs[-1]["name"]
        builder.add_edge(last, END)
        return builder.compile()

    @staticmethod
    def _wrap(spec):
        def run(state, runtime: Runtime[Context]):
            on = set(runtime.context.faults) if runtime.context is not None else set()
            return spec["fn"](state, lambda flag: spec["names"][flag] in on)
        run.__name__ = spec["name"]
        return run
