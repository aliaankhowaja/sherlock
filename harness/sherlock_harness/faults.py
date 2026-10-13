"""Fault catalogue for demo team #1 and in-process gold derivation (spec FR-E2, FR-E3)."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from sherlock_harness.teams.vendor_brief import Context, check, graph


@dataclass(frozen=True)
class Fault:
    node: str
    description: str
    harmful: bool = True


FAULTS: dict[str, Fault] = {
    "router.wrong_source": Fault("router", "Routes compliance questions to the marketing site"),
    "retriever.drop_latest": Fault("retriever", "Drops the newest document (the ISO 27001 audit)"),
    "retriever.reverse_order": Fault(
        "retriever", "Returns documents newest-first; nothing downstream depends on order", harmful=False
    ),
    "extractor.legacy_pattern": Fault(
        "extractor", "Legacy pattern reports the expired SOC 2 as a current certification"
    ),
    "writer.stale_template": Fault("writer", "Old template omits the data-region line"),
    "reviewer.false_block": Fault("reviewer", "Wrongly blocks briefs with EU data residency"),
}


def run_team(faults: list[str], vendor: str = "acme") -> dict:
    unknown = set(faults) - FAULTS.keys()
    if unknown:
        raise ValueError(f"unknown faults: {sorted(unknown)}")
    return graph.invoke({"vendor": vendor}, context=Context(faults=list(faults)))


def _passes(faults: list[str]) -> bool:
    return check(run_team(faults)["final_output"]).passed


def gold_minimal_sets(faults: list[str]) -> list[frozenset[str]]:
    """Every 1-minimal set of nodes whose restoration makes the run pass.

    Gold is derived by restoring subsets and observing the check, never from the planted
    fault names (FR-E3). Restoring a node removes every fault planted on it. Re-running the
    whole graph in-process is equivalent to forking and re-running downstream only because
    every node in this team is deterministic.
    """
    if _passes(faults):
        return []
    faulty_nodes = sorted({FAULTS[name].node for name in faults})
    minimal: list[frozenset[str]] = []
    for size in range(1, len(faulty_nodes) + 1):
        for subset in combinations(faulty_nodes, size):
            candidate = frozenset(subset)
            if any(found <= candidate for found in minimal):
                continue
            remaining = [name for name in faults if FAULTS[name].node not in candidate]
            if _passes(remaining):
                minimal.append(candidate)
    return minimal
