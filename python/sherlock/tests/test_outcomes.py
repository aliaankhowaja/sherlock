"""`sherlock-rec outcomes`: which runs of a team passed or failed the check (pure part, no server)."""

import json
from pathlib import Path

from sherlock import cli
from sherlock.checks import Checks
from sherlock.outcomes import outcomes

CHECKS = Checks([{"type": "contains", "value": "ISO 27001"}], "final_output", Path("."), Path("sherlock.yaml"))


def thread(tid, out=None, status="idle", fork=False, created="2026-10-14T06:35:47+00:00"):
    meta = {"graph_id": "g", **({"sherlock_fork_of": "x"} if fork else {})}
    return {"thread_id": tid, "status": status, "created_at": created, "metadata": meta,
            "values": {"final_output": out} if out is not None else {}}


def test_each_run_is_judged_by_the_check():
    rows = outcomes([thread("a", "has ISO 27001"), thread("b", "has SOC 2")], CHECKS)
    assert [(r["thread_id"], r["outcome"]) for r in rows] == [("a", "pass"), ("b", "fail")]
    assert rows[1]["failed"] == ["output does not contain 'ISO 27001'"] and rows[0]["failed"] == []
    assert rows[0]["created_at"] == "2026-10-14T06:35:47+00:00"


def test_sherlock_trial_forks_are_not_runs():
    assert outcomes([thread("a", "ISO 27001"), thread("f", "ISO 27001", fork=True)], CHECKS)[0]["thread_id"] == "a"
    assert len(outcomes([thread("f", "x", fork=True)], CHECKS)) == 0


def test_a_crashed_run_or_a_run_without_output_says_so():
    rows = outcomes([thread("e", "ISO 27001", status="error"), thread("n")], CHECKS)
    assert [r["outcome"] for r in rows] == ["error", "no_output"]


def test_cli_prints_the_outcomes_as_json(tmp_path, monkeypatch, capsys):
    (tmp_path / "sherlock.yaml").write_text("assert:\n  - type: contains\n    value: ok\n", encoding="utf-8")
    calls = []

    class FakeClient:
        def __init__(self, url, key=None):
            calls.append(url)

        def request(self, method, path, body=None):
            calls.append((method, path, body))
            return [thread("a", "ok"), thread("b", "no")]

    monkeypatch.setattr("sherlock.g3.Client", FakeClient)
    code = cli.main(["outcomes", "--graph-id", "g", "-c", str(tmp_path / "sherlock.yaml"), "--url", "http://h:1"])
    assert code == 0
    rows = json.loads(capsys.readouterr().out)
    assert [r["outcome"] for r in rows] == ["pass", "fail"]
    assert calls[0] == "http://h:1" and calls[1][1] == "/threads/search"
    assert calls[1][2]["metadata"] == {"graph_id": "g"}
