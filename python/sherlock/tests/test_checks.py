"""Check file loader and deterministic assertions (spec FR-C1-C6, FR-C9). No LLM judge."""

import json

import pytest

from sherlock.checks import CheckError, discover, evaluate, load_checks


def run(assertions, output, base=None, **kw):
    from pathlib import Path
    return evaluate(assertions, output, Path(base or "."), **kw)


def one(atype, value, output, **extra):
    return run([{"type": atype, "value": value, **extra}], output).results[0]


@pytest.mark.parametrize("atype,value,output,ok", [
    ("equals", "abc", "abc", True), ("equals", "abc", "abcd", False),
    ("contains", "Foo", "a Foo b", True), ("contains", "foo", "a Foo b", False),
    ("icontains", "foo", "a Foo b", True), ("icontains", "zzz", "a Foo b", False),
    ("contains-all", ["a", "b"], "ab", True), ("contains-all", ["a", "z"], "ab", False),
    ("contains-any", ["z", "b"], "ab", True), ("contains-any", ["y", "z"], "ab", False),
    ("icontains-all", ["A", "B"], "ab", True), ("icontains-any", ["Z", "B"], "ab", True),
    ("icontains-any", ["Z", "Y"], "ab", False),
    ("regex", r"^v\d+$", "v12", True), ("regex", r"^v\d+$", "x12", False),
    ("is-json", None, '{"a": 1}', True), ("is-json", None, "{nope", False),
])
def test_assertion_pass_and_fail(atype, value, output, ok):
    r = one(atype, value, output)
    assert r.pass_ is ok and r.score == (1.0 if ok else 0.0) and r.type == atype and r.reason


@pytest.mark.parametrize("atype,value,output", [
    ("contains", "Foo", "a Foo b"), ("equals", "abc", "abc"), ("icontains", "foo", "FOO"),
    ("contains-all", ["a"], "a"), ("contains-any", ["a"], "a"), ("regex", "a", "a"), ("is-json", None, "{}"),
])
def test_not_prefix_inverts_every_assertion(atype, value, output):
    plain, negated = one(atype, value, output), one("not-" + atype, value, output)
    assert plain.pass_ and not negated.pass_ and negated.score == 0.0 and negated.type == "not-" + atype


def test_reason_names_the_missing_substring():
    r = one("contains-all", ["alpha", "beta", "gamma"], "alpha only")
    assert not r.pass_ and "beta" in r.reason and "gamma" in r.reason and "alpha'" not in r.reason
    assert "SOC 2" in one("not-contains", "SOC 2", "has SOC 2 inside").reason
    assert "'zed'" in one("contains", "zed", "nothing").reason


def test_equals_object_compares_parsed_json_and_regex_bad_pattern_is_an_error():
    assert one("equals", {"a": 1}, '{"a":1}').pass_
    with pytest.raises(CheckError, match="regex"):
        one("regex", "(", "x")


def test_is_json_with_inline_schema():
    schema = {"type": "object", "required": ["n"], "properties": {"n": {"type": "integer"}}}
    assert one("is-json", schema, '{"n": 3}').pass_
    bad = one("is-json", schema, '{"n": "three"}')
    assert not bad.pass_ and "n" in bad.reason
    assert not one("is-json", schema, "[]").pass_


def test_unsupported_type_is_a_clear_error():
    with pytest.raises(CheckError, match="unsupported assertion type: llm-rubric"):
        one("llm-rubric", "be nice", "x")
    with pytest.raises(CheckError, match="unsupported assertion type: not-answer-relevance"):
        one("not-answer-relevance", None, "x")


def test_report_passes_only_when_every_assertion_passes():
    rep = run([{"type": "contains", "value": "a"}, {"type": "not-contains", "value": "b"}], "ab")
    assert not rep.passed and [r.pass_ for r in rep.results] == [True, False]
    assert run([{"type": "contains", "value": "a"}], "a").passed


def test_non_string_output_is_json_encoded():
    assert run([{"type": "contains", "value": '"k": 1'}], {"k": 1}).passed


def test_load_checks_promptfoo_shapes_and_file_paths_resolve_against_the_config_dir(tmp_path, monkeypatch):
    cfg = tmp_path / "conf"
    cfg.mkdir()
    (cfg / "schema.json").write_text(json.dumps({"type": "object", "required": ["n"]}))
    (cfg / "words.txt").write_text("1")
    (cfg / "sherlock.yaml").write_text(
        "# yaml-language-server: $schema=x\n"
        "output_key: answer\n"
        "defaultTest:\n  assert:\n    - {type: contains, value: 'file://words.txt'}\n"
        "assert:\n    - {type: is-json, value: 'file://schema.json'}\n")
    other = tmp_path / "elsewhere"
    other.mkdir()
    monkeypatch.chdir(other)  # cwd is NOT the config directory
    checks = load_checks(cfg / "sherlock.yaml")
    assert checks.output_key == "answer" and checks.base_dir == cfg.resolve()
    assert run(checks.assertions, '{"n": 1}', checks.base_dir).passed
    assert not run(checks.assertions, '{"m": 1}', checks.base_dir).passed


def test_default_output_key_and_tests_section_is_rejected(tmp_path):
    p = tmp_path / "sherlock.yaml"
    p.write_text("assert:\n  - {type: contains, value: x}\n")
    assert load_checks(p).output_key == "final_output"
    p.write_text("tests:\n  - assert: [{type: contains, value: x}]\n")
    with pytest.raises(CheckError, match="tests"):
        load_checks(p)
    p.write_text("assert: []\n")
    with pytest.raises(CheckError, match="no assertions"):
        load_checks(p)


def test_discovery_walks_up_and_override_wins(tmp_path):
    root = tmp_path / "proj"
    deep = root / "a" / "b"
    deep.mkdir(parents=True)
    (root / "sherlock.yaml").write_text("assert: [{type: contains, value: x}]\n")
    assert discover(deep) == root / "sherlock.yaml"
    assert discover(tmp_path / "nowhere") is None
    with pytest.raises(CheckError, match="no sherlock.yaml"):
        load_checks(None, start=tmp_path / "nowhere")
    custom = tmp_path / "mine.yaml"
    custom.write_text("assert: [{type: contains, value: y}]\n")
    assert load_checks(custom, start=deep).assertions[0]["value"] == "y"
