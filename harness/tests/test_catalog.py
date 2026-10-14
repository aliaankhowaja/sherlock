"""Demo teams 2-4, gold derivation and the case sets (spec FR-E1..E6). In-process, no LangGraph server."""

import pytest

from sherlock_harness.catalog import TEAMS, build_cases, gold_minimal_sets, passes, run_team, stub_env


@pytest.fixture(scope="module")
def stub():
    with stub_env():
        yield


@pytest.mark.parametrize("name", sorted(TEAMS))
def test_clean_run_passes(name, stub):
    team = TEAMS[name]
    assert passes(team.check, run_team(team, [])["final_output"])


@pytest.mark.parametrize("name,fault", [(n, f) for n, t in sorted(TEAMS.items()) for f, x in sorted(t.faults.items()) if x.harmful])
def test_every_harmful_fault_breaks_its_team(name, fault, stub):
    team = TEAMS[name]
    assert not passes(team.check, run_team(team, [fault])["final_output"])
    assert gold_minimal_sets(team, [fault]) == [[team.faults[fault].node]]


@pytest.mark.parametrize("name,fault", [(n, f) for n, t in sorted(TEAMS.items()) for f, x in sorted(t.faults.items()) if not x.harmful])
def test_harmless_faults_alone_leave_the_run_passing(name, fault, stub):
    team = TEAMS[name]
    assert passes(team.check, run_team(team, [fault])["final_output"])


def test_redundant_repair_gives_two_minimal_sets(stub):
    team = TEAMS["invoice_pipeline"]
    assert gold_minimal_sets(team, ["extract.comma_split", "normalize.trust_parsed"]) == [["extract"], ["normalize"]]


def test_two_independent_faults_need_both_nodes(stub):
    team = TEAMS["order_desk"]
    assert gold_minimal_sets(team, ["stale_inventory", "drops_shipping_line"]) == [["assemble", "stock"]]


def test_decoy_fault_is_not_gold(stub):
    team = TEAMS["invoice_pipeline"]
    assert gold_minimal_sets(team, ["extract.comma_split", "post.round_down"]) == [["post"]]


def test_node_map_covers_every_fault():
    for team in TEAMS.values():
        assert set(team.node_map.values()) <= set(team.nodes)


def test_cases_are_seeded_and_reproducible():
    a = [c.to_dict() for c in build_cases(seed=7)]
    b = [c.to_dict() for c in build_cases(seed=7)]
    assert a == b
    assert [c["id"] for c in a] != [c["id"] for c in (x.to_dict() for x in build_cases(seed=8))]


def test_hidden_set_never_repeats_a_visible_case_and_every_case_fails_z():
    cases = build_cases()
    visible = {(c.team, frozenset(c.faults)) for c in cases if c.split == "visible"}
    hidden = [c for c in cases if c.split == "hidden"]
    assert hidden and all((c.team, frozenset(c.faults)) not in visible for c in hidden)
    assert all(c.gold for c in cases), "every case must fail Z so there is something to diagnose"
    assert {c.team for c in cases} == set(TEAMS)


def test_hard_slice_has_each_kind():
    tags = {t for c in build_cases() for t in c.tags}
    assert {"two_cause", "or_fix", "silent_decoy", "abstain_by_design"} <= tags


def test_every_node_declares_its_kind_for_the_graph_view():
    """The web app's pipeline graph reads `kind` from LangGraph node metadata (`GET /assistants/{id}/graph`)."""
    for team in TEAMS.values():
        drawn = team.module.graph.get_graph().to_json()
        kinds = {n["id"]: (n.get("metadata") or {}).get("kind") for n in drawn["nodes"]
                 if n["id"] not in ("__start__", "__end__")}
        assert set(kinds) == set(team.nodes), team.name
        assert set(kinds.values()) <= {"deterministic", "llm", "tool"}, (team.name, kinds)
    bot = {n["id"]: n.get("metadata") for n in TEAMS["support_bot"].module.graph.get_graph().to_json()["nodes"]}
    assert bot["ask"] == {"kind": "llm"} and bot["prep"] == {"kind": "deterministic"}
