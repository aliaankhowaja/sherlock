"""Intake (spec 5.3; FR-I1-I5): how a run becomes known to be wrong.

Sherlock never guesses that an answer is wrong. The engineer says so, and the record lives in
`.sherlock/intake/<thread_id>.json`:
  * `wrong`    the "Wrong" click: no node named, no check yet (FR-I3). Diagnosis shows the tape and clues only,
               and becomes a verdict once a check or a known-good source is added (FR-I4).
  * `expected` an expected output: the run fails if its output differs (FR-I1). Becomes an `equals` check.
  * `check`    a check file Z (FR-I2).
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from sherlock.checks import Checks, CheckError, load_checks

SCHEMA = 1


def intake_path(sherlock_dir: Path | str, thread_id: str) -> Path:
    return Path(sherlock_dir) / "intake" / f"{thread_id}.json"


def write_intake(sherlock_dir: Path | str, thread_id: str, *, expected: str | None = None,
                 check_file: str | None = None, note: str | None = None) -> dict:
    if expected is not None and check_file:
        raise CheckError("give either an expected output or a check file, not both")
    kind = "expected" if expected is not None else "check" if check_file else "wrong"
    if check_file:
        load_checks(check_file)  # fail now, not at diagnosis time
        check_file = str(Path(check_file).resolve())
    record = {"schema": SCHEMA, "thread_id": thread_id, "kind": kind, "note": note, "expected": expected,
              "check_file": check_file, "marked_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    path = intake_path(sherlock_dir, thread_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def read_intake(sherlock_dir: Path | str, thread_id: str) -> dict | None:
    path = intake_path(sherlock_dir, thread_id)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def checks_for(record: dict | None, config: str | None, output_key: str = "final_output") -> Checks | None:
    """The check Z for a diagnosis: `-c` wins, then the intake record, then an auto-discovered sherlock.yaml.

    None only when the run was marked wrong and nothing supplies a check. With no intake record and no
    check file anywhere, this raises like `check` does.
    """
    if config:
        return load_checks(config)
    if record and record["kind"] == "check":
        return load_checks(record["check_file"])
    if record and record["kind"] == "expected":
        return Checks([{"type": "equals", "value": record["expected"]}], output_key, Path.cwd(),
                      intake_path(".sherlock", record["thread_id"]))
    try:
        return load_checks()
    except CheckError:
        if record:
            return None
        raise
