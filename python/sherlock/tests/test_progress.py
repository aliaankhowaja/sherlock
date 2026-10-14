"""Live progress: `diagnose` reports each step as it happens (for `sherlock-rec diagnose --progress` and the web app)."""

import io
import json

import pytest
from test_diagnose_unit import KG, DiagServer
from test_g3_unit import CHECKS
from test_search import Oracle

from sherlock import cli
from sherlock.cassette import Cassette
from sherlock.diagnose import diagnose
from sherlock.search import Budget, search


@pytest.fixture
def cassette(tmp_path):
    path = tmp_path / "c.db"
    Cassette(path).mark_replay(1)
    return path


def test_search_reports_each_trial_before_and_after_it_runs():
    events = []
    r = search(["a", "b"], Oracle([{"a"}]), 0.0, Budget(), progress=events.append)
    names = [e["event"] for e in events]
    assert names == ["trial_start", "trial"] * r.counts["total"]
    assert events[0] == {"event": "trial_start", "n": 1, "restored": ["a", "b"]}
    done = events[1]
    assert done["n"] == 1 and done["verdict"] == "pass" and done["label"] == "fixes" and "check" not in done


def test_search_without_a_listener_is_unchanged():
    assert search(["a", "b"], Oracle([{"a"}]), 0.0, Budget()).minimal_sets == [["a"]]


def test_diagnose_streams_every_step_in_order(cassette):
    events = []
    r = diagnose(DiagServer(["retriever.drop_latest", "extractor.legacy_pattern"]), "T", KG, CHECKS, cassette,
                 Budget(), progress=events.append)
    names = [e["event"] for e in events]
    assert names[:3] == ["start", "check", "plan"] and names[-1] == "done"
    assert events[0]["thread_id"] == "T" and "retriever" in events[0]["nodes_on_path"]
    assert events[1]["pass"] is False and events[1]["failed"]
    plan = events[2]
    assert plan["candidates"] == ["retriever", "extractor"] and set(plan["pruned"]) == {"router", "writer"}
    assert plan["max_trials"] == 40 and plan["exhaustive_trials"] >= 3
    trials = [e for e in events if e["event"] == "trial"]
    assert len(trials) == r["counts"]["total"] == 3
    forks = [e for e in events if e["event"] == "fork"]
    assert len(forks) == 3 and all(f["fork_node"] and f["fork_thread"] for f in forks)
    assert names.count("resume") == 3
    # each trial is announced, forked, resumed, then judged
    assert names[3:8] == ["trial_start", "fork", "resume", "rerun", "trial"]
    done = events[-1]
    assert done["status"] == "found" and done["minimal_sets"] == [["retriever", "extractor"]]
    assert done["trials_used"] == 3


def test_each_trial_shows_every_rerun_node_with_its_input_and_output(cassette):
    events = []
    diagnose(DiagServer(["retriever.drop_latest", "extractor.legacy_pattern"]), "T", KG, CHECKS, cassette,
             Budget(), progress=events.append)
    reruns = [e for e in events if e["event"] == "rerun"]
    assert len(reruns) == 3
    for rerun in reruns:
        assert rerun["fork_thread"] and rerun["fork_node"] and rerun["restored"]
        nodes = [s["node"] for s in rerun["steps"]]
        assert set(rerun["restored"]) <= set(nodes) and nodes[0] == rerun["fork_node"]
        assert all(s["restored"] == (s["node"] in rerun["restored"]) for s in rerun["steps"])
        assert all({"step", "input", "output"} <= set(s) for s in rerun["steps"])
        # each node's output is part of what the next node receives
        for a, b in zip(rerun["steps"], rerun["steps"][1:]):
            assert set(a["output"]) <= set(b["input"])


def test_clip_caps_long_values_and_keeps_the_shape():
    from sherlock.g3 import clip
    out = clip({"text": "x" * 1000, "docs": list(range(50)), "n": 3})
    assert out["n"] == 3 and len(out["text"]) < 1000 and out["text"].startswith("xxx")
    assert len(out["docs"]) == 21 and out["docs"][-1] == "... (+30 more)"


def test_an_early_abstain_still_ends_with_done(cassette):
    events = []
    diagnose(DiagServer(["retriever.drop_latest"]), "T", None, CHECKS, cassette, Budget(), progress=events.append)
    assert events[-1]["event"] == "done" and events[-1]["status"] == "abstain"
    assert events[-1]["reason_code"] == "no_known_good"


def test_jsonl_writer_prints_one_flushed_object_per_line():
    out = io.StringIO()
    emit = cli.jsonl_progress(out)
    emit({"event": "trial_start", "n": 1, "restored": ["a"]})
    emit({"event": "done", "status": "found"})
    lines = out.getvalue().splitlines()
    assert [json.loads(line)["event"] for line in lines] == ["trial_start", "done"]


def test_cli_progress_flag_streams_json_lines_on_stderr(tmp_path, monkeypatch, capsys):
    (tmp_path / "sherlock.yaml").write_text("assert:\n  - type: contains\n    value: ok\n", encoding="utf-8")
    seen = {}

    def fake(client, thread_id, *a, progress=None, **kw):
        seen["progress"] = progress
        progress({"event": "start", "thread_id": thread_id})
        progress({"event": "done", "status": "abstain"})
        return {"thread_id": thread_id, "status": "abstain", "reason": "r", "clues": [],
                "counts": {"fixes": 0, "partly_helps": 0, "does_not_help": 0, "cannot_say": 0, "total": 0}}

    monkeypatch.setattr("sherlock.diagnose.diagnose", fake)
    code = cli.main(["diagnose", "--thread-id", "T", "--progress", "-c", str(tmp_path / "sherlock.yaml"),
                     "--cassette", str(tmp_path / "c.db"), "--out", str(tmp_path)])
    err = capsys.readouterr().err.splitlines()
    assert code == 75
    events = [json.loads(line) for line in err if line.startswith("{")]
    assert [e["event"] for e in events] == ["start", "done"]


def test_cli_without_progress_flag_prints_no_events(tmp_path, monkeypatch, capsys):
    (tmp_path / "sherlock.yaml").write_text("assert:\n  - type: contains\n    value: ok\n", encoding="utf-8")

    def fake(client, thread_id, *a, progress=None, **kw):
        assert progress is None
        return {"thread_id": thread_id, "status": "abstain", "reason": "r", "clues": [],
                "counts": {"fixes": 0, "partly_helps": 0, "does_not_help": 0, "cannot_say": 0, "total": 0}}

    monkeypatch.setattr("sherlock.diagnose.diagnose", fake)
    cli.main(["diagnose", "--thread-id", "T", "-c", str(tmp_path / "sherlock.yaml"),
              "--cassette", str(tmp_path / "c.db"), "--out", str(tmp_path)])
    assert not [line for line in capsys.readouterr().err.splitlines() if line.startswith("{")]
