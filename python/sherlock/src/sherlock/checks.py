"""Outcome checks Z: promptfoo-compatible assertions, deterministic only (spec 5.2, FR-C1-C6, FR-C9).

A check file is YAML. Assertions are promptfoo `assert:` objects (`type`, `value`), either at
the top level or under `defaultTest:`. `output_key` (Sherlock extension) names the state key
whose value is the run's output; default `final_output`. No LLM judge: every assertion is a
pure function of the output text.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

FILENAMES = ("sherlock.yaml", "sherlock.yml")
DEFAULT_OUTPUT_KEY = "final_output"


class CheckError(Exception):
    """The check file or an assertion is unusable. Distinct from an assertion failing."""


@dataclass
class AssertionResult:
    type: str
    pass_: bool
    score: float
    reason: str

    def to_dict(self):
        return {"type": self.type, "pass": self.pass_, "score": self.score, "reason": self.reason}


@dataclass
class Report:
    results: list[AssertionResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(r.pass_ for r in self.results)

    def to_dict(self):
        return {"pass": self.passed, "results": [r.to_dict() for r in self.results]}


@dataclass
class Checks:
    assertions: list[dict]
    output_key: str
    base_dir: Path
    path: Path


def discover(start: Path | None = None) -> Path | None:
    """Nearest sherlock.yaml at or above `start` (default: cwd)."""
    here = Path(start or Path.cwd()).resolve()
    for d in (here, *here.parents):
        for name in FILENAMES:
            if (d / name).is_file():
                return d / name
    return None


def load_checks(path: Path | str | None = None, start: Path | None = None) -> Checks:
    """`path` is the `-c` override; otherwise auto-discover from `start`."""
    found = Path(path) if path else discover(start)
    if found is None:
        raise CheckError(f"no sherlock.yaml found at or above {Path(start or Path.cwd()).resolve()}; use -c")
    found = found.resolve()
    try:
        doc = yaml.safe_load(found.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise CheckError(f"cannot read {found}: {exc}") from exc
    if not isinstance(doc, dict):
        raise CheckError(f"{found}: expected a mapping at the top level")
    if "tests" in doc:
        raise CheckError(f"{found}: `tests:` is not supported; list the run's assertions under `assert:`")
    assertions = list((doc.get("defaultTest") or {}).get("assert") or []) + list(doc.get("assert") or [])
    if not assertions:
        raise CheckError(f"{found}: no assertions (expected `assert:` or `defaultTest.assert:`)")
    return Checks(assertions, str(doc.get("output_key") or DEFAULT_OUTPUT_KEY), found.parent, found)


def _resolve(value, base_dir: Path):
    """`file://` values resolve against the config file's directory, never cwd (FR-C2)."""
    if isinstance(value, list):
        return [_resolve(v, base_dir) for v in value]
    if not (isinstance(value, str) and value.startswith("file://")):
        return value
    target = base_dir / value[len("file://"):]
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise CheckError(f"cannot read {value}: {exc}") from exc
    if target.suffix == ".json":
        return json.loads(text)
    if target.suffix in (".yaml", ".yml"):
        return yaml.safe_load(text)
    return text


def _text(output) -> str:
    return output if isinstance(output, str) else json.dumps(output, sort_keys=True)


def _parse(text: str):
    try:
        return True, json.loads(text)
    except ValueError:
        return False, None


def _q(items) -> str:
    return ", ".join(repr(i) for i in items)


def _need_list(atype, value):
    if not isinstance(value, list) or not value:
        raise CheckError(f"{atype}: value must be a non-empty list")
    return [str(v) for v in value]


def _contains(atype, value, out, fold=False):
    needle, hay = str(value), out
    ok = (needle.lower() in hay.lower()) if fold else (needle in hay)
    return ok, f"output contains {needle!r}" if ok else f"output does not contain {needle!r}"


def _all(atype, value, out, fold=False):
    items = _need_list(atype, value)
    hay = out.lower() if fold else out
    missing = [i for i in items if (i.lower() if fold else i) not in hay]
    return (not missing), (f"output contains all of {_q(items)}" if not missing
                           else f"output is missing {_q(missing)}")


def _any(atype, value, out, fold=False):
    items = _need_list(atype, value)
    hay = out.lower() if fold else out
    hit = [i for i in items if (i.lower() if fold else i) in hay]
    return bool(hit), (f"output contains {_q(hit)}" if hit else f"output contains none of {_q(items)}")


def _equals(atype, value, out):
    if isinstance(value, (dict, list)):
        ok, parsed = _parse(out)
        same = ok and parsed == value
    else:
        same = out == str(value)
    return same, "output equals the expected value" if same else "output does not equal the expected value"


def _regex(atype, value, out):
    try:
        found = re.search(str(value), out)
    except re.error as exc:
        raise CheckError(f"regex: invalid pattern {value!r}: {exc}") from exc
    return bool(found), (f"output matches /{value}/" if found else f"output does not match /{value}/")


def _is_json(atype, value, out):
    ok, parsed = _parse(out)
    if not ok:
        return False, "output is not valid JSON"
    if value in (None, ""):
        return True, "output is valid JSON"
    import jsonschema
    errors = sorted(jsonschema.Draft202012Validator(value).iter_errors(parsed), key=lambda e: list(e.path))
    if errors:
        e = errors[0]
        where = "/".join(str(p) for p in e.path) or "(root)"
        return False, f"JSON does not match the schema at {where}: {e.message}"
    return True, "output is valid JSON matching the schema"


_TYPES = {
    "equals": _equals,
    "contains": _contains,
    "icontains": lambda t, v, o: _contains(t, v, o, fold=True),
    "contains-all": _all,
    "icontains-all": lambda t, v, o: _all(t, v, o, fold=True),
    "contains-any": _any,
    "icontains-any": lambda t, v, o: _any(t, v, o, fold=True),
    "regex": _regex,
    "is-json": _is_json,
}


def evaluate(assertions: list[dict], output, base_dir: Path | str = ".") -> Report:
    """Score `output` against every assertion. Raises CheckError for an unusable assertion."""
    out, base, report = _text(output), Path(base_dir), Report()
    for a in assertions:
        if not isinstance(a, dict) or "type" not in a:
            raise CheckError(f"assertion needs a `type`: {a!r}")
        atype = str(a["type"])
        negate, base_type = atype.startswith("not-"), atype.removeprefix("not-")
        fn = _TYPES.get(base_type)
        if fn is None:
            raise CheckError(f"unsupported assertion type: {atype}")
        ok, reason = fn(base_type, _resolve(a.get("value"), base), out)
        if negate:
            ok, reason = (not ok), f"expected the opposite: {reason}"
        report.results.append(AssertionResult(atype, ok, 1.0 if ok else 0.0, reason))
    return report
