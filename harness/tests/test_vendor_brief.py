"""Demo team #1 (spec FR-E1, FR-E2): behaviour of the team and its planted faults.

Runs the graph in-process, so no LangGraph server is needed.
"""

import pytest

from sherlock_harness.faults import FAULTS, gold_minimal_sets, run_team
from sherlock_harness.teams.vendor_brief import check


def test_clean_run_passes_check():
    result = run_team(faults=[])
    assert check(result["final_output"]).passed, result["final_output"]


HARMFUL = sorted(name for name, fault in FAULTS.items() if fault.harmful)
HARMLESS = sorted(name for name, fault in FAULTS.items() if not fault.harmful)


@pytest.mark.parametrize("fault", HARMFUL)
def test_every_harmful_fault_fails_check(fault):
    result = run_team(faults=[fault])
    assert not check(result["final_output"]).passed, f"{fault} did not break the run"


@pytest.mark.parametrize("fault", HARMLESS)
def test_harmless_faults_leave_the_run_passing(fault):
    result = run_team(faults=[fault])
    assert check(result["final_output"]).passed, result["final_output"]


def test_check_reports_which_assertion_failed():
    result = run_team(faults=["extractor.legacy_pattern"])
    outcome = check(result["final_output"])
    assert any("SOC 2" in reason for reason in outcome.reasons), outcome.reasons


@pytest.mark.parametrize("fault", HARMFUL)
def test_single_fault_gold_is_its_own_node(fault):
    node = FAULTS[fault].node
    assert gold_minimal_sets([fault]) == [frozenset({node})]


def test_chained_two_cause_needs_both_nodes():
    # Retriever drops the doc that carries ISO 27001, and the extractor's legacy pattern
    # reads an expired SOC 2 mention as current. Fixing either alone still fails Z.
    faults = ["retriever.drop_latest", "extractor.legacy_pattern"]
    assert gold_minimal_sets(faults) == [frozenset({"retriever", "extractor"})]


def test_gold_is_derived_by_restoring_not_by_planted_names():
    # FR-E3: a planted fault that changes nothing must not appear in the gold answer.
    faults = ["retriever.reverse_order", "writer.stale_template"]
    assert gold_minimal_sets(faults) == [frozenset({"writer"})]


def test_clean_run_has_no_gold():
    assert gold_minimal_sets([]) == []
