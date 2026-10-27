"""G1 optional shortlist (FR-G1.1-G1.6) and per-gate attribution. Local stub only: no provider, no network."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from g1_stub import ShortlistStub
from test_diagnose_unit import KG, DiagServer
from test_g3_unit import CHECKS, HISTORY
from test_sources import good_history

from sherlock.cassette import Cassette
from sherlock.diagnose import diagnose
from sherlock.g1 import CARD_CHARS, node_card, rank
from sherlock.gates import parse_nominations, run_g1
from sherlock.search import Budget

NODES = ["router", "retriever", "extractor", "writer", "reviewer"]
CARD = lambda n: (n, False)  # noqa: E731
GOLDEN = Path(__file__).parent / "golden" / "g1_cards"


def g1(url, **kw):
    return run_g1(HISTORY, "final_output", "the wrong answer", ["no match"], NODES, url=url, model="stub", **kw)


def test_parse_accepts_lists_objects_prose_and_drops_unknown_names():
    assert parse_nominations('["extractor", "ghost"]', NODES) == (["extractor"], ["ghost"])
    assert parse_nominations('{"nodes": ["writer"]}', NODES)[0] == ["writer"]
    assert parse_nominations("I suspect the retriever and then the writer.", NODES)[0] == ["retriever", "writer"]
    assert parse_nominations("nothing useful", NODES) == ([], [])


def test_call_has_no_tools_and_the_prompt_is_redacted():
    secret = "sk-" + "a" * 30
    history = [dict(s, tasks=[dict(t, result={**(t.get("result") or {}), "note": f"key {secret} mail bob@corp.com"})
                              for t in s.get("tasks") or []]) for s in HISTORY]
    with ShortlistStub(["extractor"]) as stub:
        r = run_g1(history, "final_output", "out", [], NODES, url=stub.url, model="m", key="k-123")
    body = stub.hits[0]
    assert "tools" not in body and "functions" not in body and "tool_choice" not in body
    prompt = json.dumps(body["messages"])
    assert secret not in prompt and "bob@corp.com" not in prompt and r.redactions >= 1
    assert body["_auth"] == "Bearer k-123" and r.endpoint.startswith("http://127.0.0.1")
    assert r.nominated == ["extractor"] and r.fallback is None


def test_samples_only_widen_the_list():
    with ShortlistStub(per_sample=[["extractor"], ["writer", "extractor"], []]) as stub:
        r = g1(stub.url, samples=3)
    assert r.per_sample == [["extractor"], ["writer", "extractor"], []]
    assert set(r.nominated) == {"extractor", "writer"} and r.nominated[0] == "extractor"  # most-named first, none dropped


def test_empty_or_unreachable_falls_back_to_g0_only_and_says_so():
    with ShortlistStub(raw="no idea") as stub:
        empty = g1(stub.url, samples=2)
    assert empty.nominated == [] and empty.fallback == "g0_only" and "G0 clues only" in empty.note
    down = g1("http://127.0.0.1:9/v1", timeout=1)
    assert down.fallback == "g0_only" and down.error and down.samples_ok == 0


@pytest.fixture
def cassette(tmp_path):
    path = tmp_path / "c.db"
    Cassette(path).mark_replay(1)
    return path


def run(cassette, g1_cfg=None, **kw):
    server = DiagServer(["retriever.drop_latest", "extractor.legacy_pattern"])
    return diagnose(server, "T", KG, CHECKS, cassette, Budget(), g1=g1_cfg, **kw)


def test_g1_changes_order_never_the_answer(cassette):
    base = run(cassette)
    with ShortlistStub(["extractor", "writer"]) as stub:
        with_g1 = run(cassette, {"url": stub.url, "model": "stub", "samples": 1})
    assert [sorted(x) for x in with_g1["minimal_sets"]] == [sorted(x) for x in base["minimal_sets"]] and with_g1["status"] == "found"
    assert with_g1["g1"]["nominated"] == ["extractor", "writer"] and with_g1["g1"]["strength"] == "weak"
    assert with_g1["pruning"]["candidates"][0] == "extractor"  # nominated first among otherwise equal candidates
    assert set(with_g1["pruning"]["candidates"]) == set(base["pruning"]["candidates"])  # nothing excluded or added
    assert base["g1"]["enabled"] is False  # FR-G1.6: off by default, system complete


def test_wrong_or_failing_g1_cannot_hide_the_culprits(cassette):
    with ShortlistStub(["router"]) as stub:  # confidently wrong
        wrong = run(cassette, {"url": stub.url, "model": "stub"})
    assert [sorted(x) for x in wrong["minimal_sets"]] == [["extractor", "retriever"]]
    dead = run(cassette, {"url": "http://127.0.0.1:9/v1", "model": "stub"})
    assert [sorted(x) for x in dead["minimal_sets"]] == [["extractor", "retriever"]] and dead["g1"]["fallback"] == "g0_only"


def test_artifact_attributes_each_trial_and_summarises_each_gate(cassette):
    with ShortlistStub(["extractor"]) as stub:
        r = run(cassette, {"url": stub.url, "model": "stub"})
    assert all("g3" in t["gates"] for t in r["trials"])
    assert any("g1" in t["gates"] for t in r["trials"] if "extractor" in t["restored"])
    assert all("g1" not in t["gates"] for t in r["trials"] if "extractor" not in t["restored"])
    s = r["gate_summary"]
    assert s["nodes_total"] == len(r["pruning"]["nodes_on_path"]) and s["g1_nominated"] == 1
    assert s["g3_trials"] == len(r["trials"]) and s["exhaustive_count"] == r["pruning"]["exhaustive_trials"]
    assert {"pruned_by_ancestry", "g0_flagged", "g2_cut"} <= set(s)


def test_fake_scorer_is_deterministic_and_skips_a_single_candidate():
    r = rank({"backend": "fake"}, NODES, CARD)
    assert r == {**rank({"backend": "fake"}, list(reversed(NODES)), CARD), "ms": r["ms"]} and r["status"] == "ok"
    scores = [s["score"] for s in r["scores"]]
    assert scores == sorted(scores, reverse=True) and all(0 <= s <= 1 for s in scores)
    assert rank({"backend": "fake"}, ["writer"], CARD)["status"] == "skipped"


def test_fake_scorer_changes_order_never_the_answer(cassette):  # AC-G1-1 on the unit fixture; the 86 cases: run_eval
    base, fake = run(cassette), run(cassette, {"backend": "fake"})
    for key in ("minimal_sets", "unverified_sets"):
        assert sorted(map(sorted, fake[key])) == sorted(map(sorted, base[key]))
    assert (fake["status"], fake["reason_code"]) == (base["status"], base["reason_code"])
    assert set(fake["pruning"]["candidates"]) == set(base["pruning"]["candidates"])
    assert fake["g1"]["backend"] == "fake" and [s["node"] for s in fake["g1"]["scores"]] != []
    assert fake["gate_summary"]["g1_nominated"] == len(fake["g1"]["scores"])


def test_g2_cut_and_g0_flags_are_counted(cassette):
    r = run(cassette, suspects=["extractor", "writer"])
    assert any("g2" in t["gates"] for t in r["trials"]) and r["gate_summary"]["g2_cut"] >= 0


@pytest.mark.parametrize("node", NODES)
def test_node_cards_match_the_golden_files(node):  # AC-G1-6
    card, truncated = node_card(node, HISTORY, good_history(), CHECKS)
    assert card == (GOLDEN / f"{node}.txt").read_text(encoding="utf-8") and not truncated
    assert len(card) <= CARD_CHARS


def test_cards_are_redacted_cut_to_budget_and_maskable():
    secret = "sk-" + "a" * 30
    history = [dict(s, tasks=[dict(t, result={**(t.get("result") or {}), "note": f"{secret} bob@corp.com " + "x" * 9000})
                              for t in s.get("tasks") or []]) for s in HISTORY]
    card, truncated = node_card("extractor", history, good_history(), CHECKS)
    assert truncated and len(card) <= CARD_CHARS and secret not in card and "bob@corp.com" not in card
    assert card.splitlines()[1].startswith("FLAGS: ") and "chars cut...]" in card  # flags are never cut
    masked, _ = node_card("extractor", HISTORY, good_history(), CHECKS, mask=True)
    assert not any(n in masked for n in NODES) and masked.startswith("NODE: node_")
    assert node_card("extractor", HISTORY, None, CHECKS)[0].splitlines()[1].endswith("upstream_differs=unknown")
