"""The four demo teams, their fault catalogues, gold derivation and the evaluation cases (spec FR-E1..E6).

Gold is derived by restoring subsets of the faulty nodes and observing the check (FR-E3), never
from "we injected these names". The oracle re-runs the whole graph in-process, which is equivalent
to forking and re-running downstream only because it may call the (deterministic) echo stub live;
that is ground truth, not the product under test.

Hard slice (FR-E6), defined here, before any method runs. A case is in it when it is tagged:
  two_cause         the only gold set has two nodes (chained faults; fixing either alone still fails Z)
  or_fix            more than one gold set (redundant repair path; either node alone fixes the run)
  silent_decoy      a harmless fault is planted next to the real one (planted names are not gold)
  abstain_by_design the fault is in an LLM node's prompt combined with another request-changing
                    fault, so restoring one of them needs a request that was never recorded (spec 9.1)
`last_step_ok` is reported separately: the node that writes the final output is not a culprit.
"""

from __future__ import annotations

import contextlib
import os
import random
from dataclasses import dataclass, field
from itertools import combinations
from types import ModuleType

from sherlock_harness.faults import FAULTS as VENDOR_FAULTS
from sherlock_harness.faults import Fault
from sherlock_harness.stub import EchoStub
from sherlock_harness.teams import invoice_pipeline, order_desk, support_bot, vendor_brief

SEED = 20261014
HIDDEN_PER_TEAM = 4

ORDER_FAULTS = {
    "qty_off_by_one": Fault("parse", "Adds one to every quantity"),
    "stale_inventory": Fault("stock", "A stale snapshot says everything is sold out"),
    "no_bulk_discount": Fault("pricing", "Skips the 10% discount on lines of three or more"),
    "drops_shipping_line": Fault("assemble", "Leaves the shipping line out of the confirmation"),
    "verbose_notes": Fault("assemble", "Appends a cosmetic note", harmful=False),
}
INVOICE_FAULTS = {
    "extract.comma_split": Fault("extract", "Reads 1,200.50 as 1.0 (normalize repairs it unless it lost that)", harmful=False),
    "normalize.trust_parsed": Fault("normalize", "Stops recomputing the amount from the raw text", harmful=False),
    "normalize.stale_rate": Fault("normalize", "Uses a 1.0 exchange rate"),
    "validate.reject_large": Fault("validate", "Rejects invoices over 1000 USD"),
    "post.round_down": Fault("post", "Truncates the posted amount to whole dollars"),
}
SUPPORT_FAULTS = {
    "prep.truncate": Fault("prep", "Cuts the question to 8 characters before the model call"),
    "ask.terse_instruction": Fault("ask", "Prepends a prompt instruction, changing the model request"),
    "fmt.shout": Fault("fmt", "Upper-cases the answer"),
    "fmt.trailing_newline": Fault("fmt", "Appends a newline", harmful=False),
}


@dataclass(frozen=True)
class Team:
    name: str
    module: ModuleType
    faults: dict[str, Fault]
    input: dict
    llm: bool = False
    request_nodes: frozenset = frozenset()  # nodes whose faults change the LLM request body

    @property
    def nodes(self) -> list[str]:
        return list(self.module.NODES)

    @property
    def check(self) -> list[dict]:
        return self.module.CHECK

    @property
    def node_map(self) -> dict[str, str]:
        """Which node each fault name configures (the owner of a run-context item)."""
        return {name: f.node for name, f in self.faults.items()}


TEAMS: dict[str, Team] = {t.name: t for t in (
    Team("vendor_brief", vendor_brief, VENDOR_FAULTS, {"vendor": "acme"}),
    Team("order_desk", order_desk, ORDER_FAULTS, order_desk.INPUT),
    Team("invoice_pipeline", invoice_pipeline, INVOICE_FAULTS, invoice_pipeline.INPUT),
    Team("support_bot", support_bot, SUPPORT_FAULTS, support_bot.INPUT, llm=True,
         request_nodes=frozenset({"prep", "ask"})),
)}


def passes(assertions: list[dict], output: str) -> bool:
    for a in assertions:
        present = a["value"] in output
        if (a["type"] == "contains") != present:
            return False
    return True


def run_team(team: Team, faults: list[str]) -> dict:
    unknown = set(faults) - team.faults.keys()
    if unknown:
        raise ValueError(f"unknown faults: {sorted(unknown)}")
    return team.module.graph.invoke(dict(team.input), context=team.module.Context(faults=list(faults)))


_PASSES: dict[tuple, bool] = {}  # an LLM-team run costs ~1s (httpx builds an SSL context); the graphs are deterministic


def _passes(team: Team, faults: list[str]) -> bool:
    key = (team.name, tuple(sorted(faults)))
    if key not in _PASSES:
        _PASSES[key] = passes(team.check, run_team(team, faults)["final_output"])
    return _PASSES[key]


def gold_minimal_sets(team: Team, faults: list[str]) -> list[list[str]]:
    """Every 1-minimal set of nodes whose restoration makes the run pass (restoring a node removes all its faults)."""
    if _passes(team, faults):
        return []
    faulty = sorted({team.faults[f].node for f in faults})
    minimal: list[frozenset[str]] = []
    for size in range(1, len(faulty) + 1):
        for subset in combinations(faulty, size):
            candidate = frozenset(subset)
            if any(found <= candidate for found in minimal):
                continue
            if _passes(team, [f for f in faults if team.faults[f].node not in candidate]):
                minimal.append(candidate)
    return sorted((sorted(s) for s in minimal), key=lambda s: (len(s), s))


@dataclass
class Case:
    team: str
    faults: list[str]
    split: str  # visible | hidden
    gold: list[list[str]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    expect_abstain: bool = False

    @property
    def id(self) -> str:
        return f"{self.team}:{'+'.join(self.faults)}"

    @property
    def hard(self) -> bool:
        return bool({"two_cause", "or_fix", "silent_decoy", "abstain_by_design"} & set(self.tags))

    def to_dict(self) -> dict:
        return {"id": self.id, "team": self.team, "faults": self.faults, "split": self.split, "gold": self.gold,
                "tags": self.tags, "hard": self.hard, "expect_abstain": self.expect_abstain,
                "size": max((len(s) for s in self.gold), default=0)}


VISIBLE: list[tuple[str, list[str]]] = [  # the cases we tuned on
    ("vendor_brief", ["router.wrong_source"]),
    ("vendor_brief", ["writer.stale_template"]),
    ("vendor_brief", ["reviewer.false_block"]),
    ("vendor_brief", ["retriever.drop_latest", "extractor.legacy_pattern"]),
    ("vendor_brief", ["retriever.reverse_order", "writer.stale_template"]),
    ("order_desk", ["no_bulk_discount"]),
    ("order_desk", ["qty_off_by_one"]),
    ("order_desk", ["stale_inventory", "drops_shipping_line"]),
    ("invoice_pipeline", ["normalize.stale_rate"]),
    ("invoice_pipeline", ["extract.comma_split", "normalize.trust_parsed"]),
    ("invoice_pipeline", ["extract.comma_split", "post.round_down"]),
    ("support_bot", ["fmt.shout"]),
    ("support_bot", ["prep.truncate"]),
    ("support_bot", ["ask.terse_instruction"]),
    ("support_bot", ["prep.truncate", "ask.terse_instruction"]),
]


def _annotate(case: Case) -> Case:
    team = TEAMS[case.team]
    case.gold = gold_minimal_sets(team, case.faults)
    in_gold = {n for s in case.gold for n in s}
    planted = {team.faults[f].node for f in case.faults}
    tags = []
    if any(len(s) == 2 for s in case.gold):
        tags.append("two_cause")
    if len(case.gold) > 1:
        tags.append("or_fix")
    if planted - in_gold and case.gold:
        tags.append("silent_decoy")
    if team.llm and len(planted & team.request_nodes) >= 2:
        tags.append("abstain_by_design")
        case.expect_abstain = True
    if case.gold and not any(team.nodes[-1] in s for s in case.gold):
        tags.append("last_step_ok")
    case.tags = tags
    return case


@contextlib.contextmanager
def stub_env():
    """Point STUB_URL at a fresh echo stub for in-process runs of the LLM team."""
    stub = EchoStub().start()
    old = os.environ.get("STUB_URL")
    os.environ["STUB_URL"] = stub.url
    try:
        yield stub
    finally:
        stub.stop()
        if old is None:
            os.environ.pop("STUB_URL", None)
        else:
            os.environ["STUB_URL"] = old


def build_cases(seed: int = SEED, hidden_per_team: int = HIDDEN_PER_TEAM) -> list[Case]:
    """Visible cases, then a seeded sample of fault combinations never listed above (the hidden set)."""
    with stub_env():
        cases = [_annotate(Case(t, f, "visible")) for t, f in VISIBLE]
        seen = {(t, frozenset(f)) for t, f in VISIBLE}
        rng = random.Random(seed)
        for name, team in TEAMS.items():
            pool = [c for k in (1, 2) for c in combinations(sorted(team.faults), k)
                    if (name, frozenset(c)) not in seen]
            pool = [list(c) for c in pool if not _passes(team, list(c))]  # a passing run has nothing to diagnose
            for faults in rng.sample(pool, min(hidden_per_team, len(pool))):
                cases.append(_annotate(Case(name, faults, "hidden")))
    return cases
