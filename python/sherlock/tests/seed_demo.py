"""Generate the seeded demo diagnosis (FR-U9) with the real pipeline: record team 1 against a real
`langgraph dev`, restart it under replay in the socket trap, run `diagnose`, write the artifacts.

    cd python/sherlock && uv run python tests/seed_demo.py ../../harness/fixtures/sherlock-demo

Produces <dir>/diagnoses/<thread_id>.json for a two-cause failure, a single-fault failure and an abstain
(a failed run diagnosed with no prior success named). Needs `langgraph-cli`; no real provider is called.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_g3_live import HARNESS, make_lab  # noqa: E402

from sherlock.checks import load_checks  # noqa: E402
from sherlock.diagnose import diagnose, write_artifact  # noqa: E402
from sherlock.search import Budget  # noqa: E402


class _Factory:
    def mktemp(self, name):
        import tempfile

        return Path(tempfile.mkdtemp(prefix=f"{name}-"))


def main(out: Path) -> None:
    runs = [
        ("two", "vendor_brief", {"vendor": "acme"}, ["retriever.drop_latest", "extractor.legacy_pattern"]),
        ("single", "vendor_brief", {"vendor": "acme"}, ["writer.stale_template"]),
        ("nogood", "vendor_brief", {"vendor": "acme"}, ["extractor.legacy_pattern"]),
        ("good", "vendor_brief", {"vendor": "acme"}, []),
    ]
    lab_gen = make_lab(_Factory(), "seed", runs)
    lab = next(lab_gen)
    try:
        z = load_checks(HARNESS / "sherlock.yaml")
        t = lab["threads"]
        results = [
            diagnose(lab["client"], t["two"], None, z, lab["cassette"], Budget(), good_runs=[t["good"]]),
            diagnose(lab["client"], t["single"], None, z, lab["cassette"], Budget(), good_runs=[t["good"]]),
            diagnose(lab["client"], t["nogood"], None, z, lab["cassette"], Budget()),  # no known-good: abstain
        ]
        for r in results:
            print(write_artifact(r, out), r["status"], r.get("reason_code"))
        print("good run:", t["good"])
    finally:
        try:
            next(lab_gen)
        except StopIteration:
            pass


if __name__ == "__main__":
    main(Path(sys.argv[1]))
