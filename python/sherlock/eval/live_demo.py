"""Leave a real, populated demo up for the web app (verification and screenshots).

    cd python/sherlock
    uv run python eval/live_demo.py OUTDIR      # prints the server URL, then waits until Ctrl-C

Same workflow as `run_eval.py` (record on `langgraph dev`, restart under replay in the socket trap, run `diagnose`),
but the replay server stays up so its thread ids exist, and diagnoses are written to OUTDIR/diagnoses/. Then:
    sherlock serve --langgraph-url <URL> --sherlock-dir OUTDIR
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_eval import Budget, Checks, Client, diagnose, write_artifact, _lab, TEAMS, build_cases  # noqa: E402

DIAGNOSE = [("vendor_brief", ["retriever.drop_latest", "extractor.legacy_pattern"]),
            ("vendor_brief", ["writer.stale_template"]),
            ("order_desk", ["stale_inventory", "drops_shipping_line"]),
            ("invoice_pipeline", ["extract.comma_split", "normalize.trust_parsed"]),
            ("support_bot", ["prep.truncate", "ask.terse_instruction"])]
UNDIAGNOSED = [("order_desk", ["qty_off_by_one"])]


def main(out: Path) -> None:
    wanted = DIAGNOSE + UNDIAGNOSED
    cases = [c for c in build_cases() if (c.team, c.faults) in wanted]
    work = Path(out) / "lab"
    work.mkdir(parents=True, exist_ok=True)
    server, good, failed, cassette = _lab(work, cases)
    try:
        client = Client(server.url)
        for c in cases:
            if (c.team, c.faults) in UNDIAGNOSED:
                print("undiagnosed", c.id, failed[c.id])
                continue
            team = TEAMS[c.team]
            checks = Checks(team.check, "final_output", work, work / "sherlock.yaml")
            art = diagnose(client, failed[c.id], None, checks, cassette, Budget(), good_runs=[good[c.team]],
                           node_map=team.node_map)
            print(write_artifact(art, Path(out)), c.id, art["status"], art.get("reason_code"), "good:", good[c.team])
        print("SERVER", server.url, flush=True)
        while True:
            time.sleep(3600)
    finally:
        server.stop()


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
