"""Intake: a run is wrong because the engineer says so (FR-I1-I4)."""

import json

import pytest

from sherlock.checks import CheckError, evaluate
from sherlock.intake import checks_for, intake_path, read_intake, write_intake


def test_wrong_with_no_node_named(tmp_path):
    rec = write_intake(tmp_path, "T", note="the brief cites SOC 2")
    assert rec["kind"] == "wrong" and rec["expected"] is None and rec["check_file"] is None
    assert read_intake(tmp_path, "T") == rec and intake_path(tmp_path, "T").parent.name == "intake"
    assert read_intake(tmp_path, "other") is None


def test_expected_becomes_an_equals_check(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rec = write_intake(tmp_path, "T", expected="right answer")
    checks = checks_for(rec, None)
    assert rec["kind"] == "expected" and checks.output_key == "final_output"
    assert evaluate(checks.assertions, "right answer").passed and not evaluate(checks.assertions, "wrong").passed


def test_a_check_file_is_validated_now_and_used_later(tmp_path):
    z = tmp_path / "z.yaml"
    z.write_text("assert:\n  - {type: contains, value: ISO}\n")
    rec = write_intake(tmp_path, "T", check_file=str(z))
    assert rec["kind"] == "check" and checks_for(rec, None).assertions[0]["value"] == "ISO"
    (tmp_path / "bad.yaml").write_text("assert: []\n")
    with pytest.raises(CheckError):
        write_intake(tmp_path, "U", check_file=str(tmp_path / "bad.yaml"))
    with pytest.raises(CheckError, match="either"):
        write_intake(tmp_path, "V", expected="x", check_file=str(z))


def test_marked_wrong_without_any_check_yields_none_but_unmarked_still_errors(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert checks_for(write_intake(tmp_path, "T"), None) is None  # FR-I4: diagnosable once a check is added
    with pytest.raises(CheckError):
        checks_for(None, None)
    z = tmp_path / "sherlock.yaml"
    z.write_text("assert:\n  - {type: contains, value: ISO}\n")
    assert checks_for(read_intake(tmp_path, "T"), None).path == z.resolve()  # a check added later is picked up
    assert json.loads(intake_path(tmp_path, "T").read_text())["kind"] == "wrong"
