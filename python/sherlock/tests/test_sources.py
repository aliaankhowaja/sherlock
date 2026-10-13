"""Known-good sources: derive a per-node patch from a prior successful run, and the picker rule."""

import copy

from test_g3_unit import CHECKS, FAULTS, HISTORY

from sherlock.g3 import apply_restore
from sherlock.sources import Source, assess, derive_known_good, node_outputs, rank, run_input

NODES = ["router", "retriever", "extractor", "writer", "reviewer"]
PASS_OUT = "Vendor brief: acme. Certifications: ISO 27001. Data region: EU."
GOOD_WRITES = {
    "retriever": {"documents": ["Data residency: EU", "2026 audit: Acme is ISO 27001 certified."], "notes": ["r: 2"]},
    "extractor": {"certifications": ["ISO 27001"], "data_region": "EU", "notes": ["e: ISO 27001"]},
    "writer": {"brief": PASS_OUT, "notes": ["w"]},
    "reviewer": {"final_output": PASS_OUT, "notes": ["rv"]},
}


def good_history(created="2026-10-14T10:00:00+00:00", writes=GOOD_WRITES, vendor="acme"):
    """The fixture's failed two-cause run with the nodes that were faulty writing the passing output."""
    h = copy.deepcopy(HISTORY)
    for snap in h:
        for t in snap["tasks"]:
            if t["name"] == "__start__":
                t["result"] = {"vendor": vendor}
            elif t["name"] in writes:
                t["result"] = writes[t["name"]]
    h[0]["values"] = {**h[0]["values"], "final_output": writes["reviewer"]["final_output"]}
    h[0]["created_at"] = created
    return h


# --- derive_known_good --------------------------------------------------------------------------------------

def test_list_differences_are_attributed_to_the_node_named_by_the_item():
    kg, lost = derive_known_good({"faults": FAULTS + ["router.x"]}, {"faults": ["router.x"]}, NODES)
    assert lost == [] and kg["retriever"] == {"faults": {"$remove": ["retriever.drop_latest"]}}
    assert kg["extractor"] == {"faults": {"$remove": ["extractor.legacy_pattern"]}}
    assert kg["writer"] == {} and kg["router"] == {}  # same behaviour as the passing run: nothing to restore


def test_added_items_scalars_and_unattributed_differences():
    kg, lost = derive_known_good({"faults": [], "writer.template": "old", "mystery": 1},
                                 {"faults": ["reviewer.strict"], "writer.template": "new", "mystery": 2, "other": 3},
                                 NODES)
    assert kg["reviewer"] == {"faults": {"$add": ["reviewer.strict"]}}
    assert kg["writer"] == {"writer.template": "new"}
    assert sorted(lost) == ["mystery", "other"]


def test_derived_patches_compose_with_apply_restore():
    kg, _ = derive_known_good({"faults": FAULTS}, {"faults": []}, NODES)
    assert apply_restore({"faults": FAULTS}, kg, ["retriever"])["faults"] == ["extractor.legacy_pattern"]
    assert apply_restore({"faults": FAULTS}, kg, ["retriever", "extractor"]) == {"faults": []}
    assert apply_restore({"faults": []}, {"w": {"faults": {"$add": ["a", "b"]}}}, ["w"]) == {"faults": ["a", "b"]}
    assert apply_restore({"faults": ["a"]}, {"w": {"faults": {"$add": ["a"]}}}, ["w"]) == {"faults": ["a"]}


def test_longest_node_name_wins_the_attribution():
    kg, _ = derive_known_good({"faults": ["pre_writer.x"]}, {"faults": []}, ["writer", "pre_writer"])
    assert "faults" in kg["pre_writer"] and kg["writer"] == {}


# --- assess and rank ----------------------------------------------------------------------------------------

def assess_good(good, ctx=None):
    return assess("G", True, HISTORY, {"faults": FAULTS}, good, {"faults": []} if ctx is None else ctx, CHECKS)


def test_a_passing_same_input_run_is_eligible_and_lists_only_the_differing_nodes():
    s = assess_good(good_history())
    assert s.eligible and s.differing == ["retriever", "extractor", "writer", "reviewer"]
    assert s.same_output == ["router"] and s.unattributed == []
    assert s.known_good["retriever"] and s.known_good["writer"] == {}
    assert s.to_dict()["context_diff"].keys() == {"retriever", "extractor"} and s.created_at.startswith("2026-10-14")


def test_a_different_input_a_failing_run_or_no_history_is_not_a_source():
    assert "different input" in assess_good(good_history(vendor="globex")).why
    failing = copy.deepcopy(HISTORY)
    s = assess("F", True, HISTORY, {"faults": FAULTS}, failing, {"faults": []}, CHECKS)
    assert not s.eligible and "does not pass the check" in s.why
    assert "no usable" in assess("E", True, HISTORY, {}, [], None, CHECKS).why


def test_the_picker_prefers_the_closest_success_then_the_newest():
    def src(name, differing, created, eligible=True):
        return Source(name, True, eligible=eligible, created_at=created, differing=differing)

    ranked = rank([src("far", ["a", "b", "c"], "2026-10-14"), src("old", ["a"], "2026-10-01"),
                   src("new", ["a"], "2026-10-10"), src("bad", [], "2026-10-15", eligible=False)])
    assert [s.thread_id for s in ranked] == ["new", "old", "far"]


def test_run_input_and_outputs_come_from_the_tape():
    assert run_input(HISTORY) == {"vendor": "acme"}
    out = node_outputs(HISTORY)
    assert list(out) == ["router", "retriever", "extractor", "writer", "reviewer"] and len(out["writer"]) == 1
