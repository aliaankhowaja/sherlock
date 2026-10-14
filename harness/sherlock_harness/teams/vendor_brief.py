"""Demo team #1 — vendor compliance brief (spec FR-E1).

Five deterministic nodes in a chain: router -> retriever -> extractor -> writer -> reviewer.
Every node is plain code, so a re-run is exactly reproducible and no model call ever
sits on the counterfactual path (spec §9.1).

Faults are switched on per run through LangGraph runtime context,
``context={"faults": [...]}``. That is also the spec's secondary mechanism for restoring a
node's behaviour over the Agent Server API (spec §4.4): resume a fork with that node's
fault removed from the list.

This file is loaded by path by ``langgraph dev`` (see ``langgraph.json``), so it must not
import from the rest of ``sherlock_harness``.
"""

from __future__ import annotations

import operator
import re
from dataclasses import dataclass, field
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

CORPUS: dict[str, dict[str, list[str]]] = {
    "compliance_db": {
        "acme": [
            "2023 assessment: Acme held SOC 2 Type II (expired 2023, not renewed).",
            "Data residency: all customer data is stored in the EU (Frankfurt).",
            "2026 audit: Acme is ISO 27001 certified.",
        ]
    },
    "marketing_site": {
        "acme": [
            "Acme is trusted by thousands of teams.",
            "Acme is fast, friendly and secure.",
        ]
    },
}

CERTIFICATION = re.compile(r"ISO 27001|SOC 2")
DATA_REGION = re.compile(r"stored in the (\w+)")


@dataclass
class Context:
    faults: list[str] = field(default_factory=list)


class State(TypedDict, total=False):
    vendor: str
    source: str
    documents: list[str]
    certifications: list[str]
    data_region: str
    brief: str
    final_output: str
    notes: Annotated[list[str], operator.add]


def _faulty(runtime: Runtime[Context], fault: str) -> bool:
    return runtime.context is not None and fault in runtime.context.faults


def router(state: State, runtime: Runtime[Context]) -> State:
    source = "marketing_site" if _faulty(runtime, "router.wrong_source") else "compliance_db"
    return {"source": source, "notes": [f"router: {source}"]}


def retriever(state: State, runtime: Runtime[Context]) -> State:
    documents = list(CORPUS[state["source"]].get(state["vendor"], []))
    if _faulty(runtime, "retriever.drop_latest"):
        documents = documents[:-1]
    if _faulty(runtime, "retriever.reverse_order"):
        documents = documents[::-1]
    return {"documents": documents, "notes": [f"retriever: {len(documents)} documents"]}


def extractor(state: State, runtime: Runtime[Context]) -> State:
    legacy = _faulty(runtime, "extractor.legacy_pattern")
    certifications: set[str] = set()
    data_region = ""
    for document in state["documents"]:
        # The legacy pattern ignores expiry notes and reports lapsed certifications as current.
        if legacy or "expired" not in document:
            certifications.update(CERTIFICATION.findall(document))
        match = DATA_REGION.search(document)
        if match:
            data_region = match.group(1)
    found = sorted(certifications)
    return {
        "certifications": found,
        "data_region": data_region,
        "notes": [f"extractor: {', '.join(found) or 'no certifications'}"],
    }


def writer(state: State, runtime: Runtime[Context]) -> State:
    certifications = ", ".join(state["certifications"]) or "none found"
    brief = f"Vendor brief: {state['vendor']}. Certifications: {certifications}."
    # The stale template predates the data-residency requirement.
    if not _faulty(runtime, "writer.stale_template"):
        brief += f" Data region: {state['data_region'] or 'unknown'}."
    return {"brief": brief, "notes": ["writer: drafted brief"]}


def reviewer(state: State, runtime: Runtime[Context]) -> State:
    # The faulty reviewer wrongly treats EU data residency as a compliance violation.
    if _faulty(runtime, "reviewer.false_block") and "Data region: EU" in state["brief"]:
        return {
            "final_output": "BLOCKED: reviewer flagged the data region.",
            "notes": ["reviewer: blocked"],
        }
    return {"final_output": state["brief"], "notes": ["reviewer: approved"]}


NODES = ["router", "retriever", "extractor", "writer", "reviewer"]

# Node kind for Sherlock's graph view (LangGraph node metadata; no effect on execution).
DETERMINISTIC = {"kind": "deterministic"}

builder = StateGraph(State, context_schema=Context)
builder.add_node("router", router, metadata=DETERMINISTIC)
builder.add_node("retriever", retriever, metadata=DETERMINISTIC)
builder.add_node("extractor", extractor, metadata=DETERMINISTIC)
builder.add_node("writer", writer, metadata=DETERMINISTIC)
builder.add_node("reviewer", reviewer, metadata=DETERMINISTIC)
builder.add_edge(START, "router")
for upstream, downstream in zip(NODES, NODES[1:]):
    builder.add_edge(upstream, downstream)
builder.add_edge("reviewer", END)

graph = builder.compile()

# The outcome check Z for this team, in promptfoo assertion form (spec FR-C3, FR-C4).
CHECK = [
    {"type": "contains", "value": "ISO 27001"},
    {"type": "contains", "value": "Data region: EU"},
    {"type": "not-contains", "value": "SOC 2"},
    {"type": "not-contains", "value": "BLOCKED"},
]


@dataclass
class CheckResult:
    passed: bool
    reasons: list[str]


def check(output: str) -> CheckResult:
    """Evaluate CHECK against a final output. Harness-only; the product's Z is FR-C."""
    reasons = []
    for assertion in CHECK:
        value = assertion["value"]
        if assertion["type"] == "contains" and value not in output:
            reasons.append(f"missing required text: {value!r}")
        elif assertion["type"] == "not-contains" and value in output:
            reasons.append(f"contains forbidden text: {value!r}")
    return CheckResult(passed=not reasons, reasons=reasons)
