"""The large demo teams (30+ nodes): shape, determinism and gold sets for the planned cases. In-process."""

import json
from pathlib import Path

import pytest

from sherlock_harness.catalog import BIG_TEAMS, HARMLESS, TEAMS, VISIBLE, gold_minimal_sets, passes, run_team, stub_env


@pytest.fixture(scope="module", autouse=True)
def stub():
    with stub_env():
        yield


@pytest.mark.parametrize("name", BIG_TEAMS)
def test_shape(name):
    team = TEAMS[name]
    g = team.module.graph.get_graph()
    assert 28 <= len(team.nodes) <= 42
    assert len(team.faults) >= 12
    assert {n.metadata["kind"] for n in g.nodes.values() if n.metadata} >= {"deterministic", "tool", "llm"}
    targets = [e for e in g.edges if e.source == e.source]
    fan_out = {}
    for e in targets:
        fan_out.setdefault(e.source, set()).add(e.target)
    assert max(len(v) for v in fan_out.values()) >= 3  # at least one 3-way parallel fan-out
    assert any(e.conditional for e in g.edges)  # at least one conditional route


@pytest.mark.parametrize("name", BIG_TEAMS)
def test_deterministic_and_clean_run_passes(name):
    team = TEAMS[name]
    a, b = run_team(team, [])["final_output"], run_team(team, [])["final_output"]
    assert a == b and passes(team.check, a)


@pytest.mark.parametrize("name", BIG_TEAMS)
def test_harmful_faults_break_z_and_harmless_do_not(name):
    team = TEAMS[name]
    for fault, f in team.faults.items():
        assert passes(team.check, run_team(team, [fault])["final_output"]) is (not f.harmful), fault


def test_every_visible_big_case_has_a_gold_set_and_is_deterministic():
    cases = [(t, f) for t, f in VISIBLE if t in BIG_TEAMS]
    assert len(cases) >= 24
    for t, f in cases:
        assert gold_minimal_sets(TEAMS[t], f) == gold_minimal_sets(TEAMS[t], f) != []


GOLD = [
    ("support_desk", ["customer_lookup.stale_cache", "urgency.threshold_off"], [["customer_lookup", "urgency"]]),
    ("support_desk", ["pii_redact.miss_card", "compliance_check.skip_pii_scan"], [["compliance_check"], ["pii_redact"]]),
    ("support_desk", ["intake.ref_lowercase"], [["intake"]]),  # the crash is reported by order_lookup, the cause is intake
    ("loan_underwriting", ["employer_verify.stale_registry", "risk_score.min_balance_x4"], [["employer_verify", "risk_score"]]),
    ("loan_underwriting", ["fraud_velocity.threshold_one", "fraud_device.default_device"], [["fraud_device"], ["fraud_velocity"]]),
    ("revenue_report", ["sign_flip", "sum_abs"], [["agg_month", "extract_refunds"]]),
    ("revenue_report", ["skip_first_row", "key_ignores_month"], [["dedupe"]]),  # skip_first_row is a silent decoy
]


@pytest.mark.parametrize("team,faults,gold", GOLD)
def test_gold_sets(team, faults, gold):
    assert gold_minimal_sets(TEAMS[team], faults) == gold


def test_harmless_probes_pass_and_have_no_gold():
    for t, f in HARMLESS:
        assert gold_minimal_sets(TEAMS[t], f) == []


def test_langgraph_json_serves_the_big_teams():
    graphs = json.loads((Path(__file__).resolve().parents[1] / "langgraph.json").read_text())["graphs"]
    assert set(BIG_TEAMS) <= set(graphs)
