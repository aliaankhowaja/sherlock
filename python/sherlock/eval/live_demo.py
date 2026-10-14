"""Leave a real, populated demo up for the web app (verification and screenshots).

    cd python/sherlock
    uv run python eval/live_demo.py OUTDIR      # prints the server URL, then waits until Ctrl-C

Same workflow as `run_eval.py` (record on `langgraph dev`, restart under replay in the socket trap, run `diagnose`),
but the replay server stays up so its thread ids exist, and diagnoses are written to OUTDIR/diagnoses/.
OUTDIR/lab is also a Sherlock project (cassette, one check and node map per team under checks/), so the web app can
run a diagnosis itself. Then:
    sherlock serve --langgraph-url <URL> --sherlock-dir OUTDIR --project OUTDIR/lab --sherlock-rec <path to sherlock-rec>
Only the project files:  uv run python eval/live_demo.py --project-only OUTDIR/lab
"""

import json
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


def write_project(lab: Path) -> None:
    """Per-team check and node map, where `sherlock serve --project` looks for them (checks/<graph_id>.yaml)."""
    import yaml

    (lab / "checks").mkdir(parents=True, exist_ok=True)
    for name, team in TEAMS.items():
        (lab / "checks" / f"{name}.yaml").write_text(
            yaml.safe_dump({"output_key": "final_output", "assert": team.check}, sort_keys=False), encoding="utf-8")
        (lab / "checks" / f"{name}.node-map.json").write_text(json.dumps(team.node_map, indent=2), encoding="utf-8")


def main(out: Path) -> None:
    wanted = DIAGNOSE + UNDIAGNOSED
    cases = [c for c in build_cases() if (c.team, c.faults) in wanted]
    work = Path(out) / "lab"
    work.mkdir(parents=True, exist_ok=True)
    server, good, failed, cassette = _lab(work, cases)
    write_project(work)
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
    if sys.argv[1] == "--project-only":
        write_project(Path(sys.argv[2]).resolve())
    else:
        main(Path(sys.argv[1]).resolve())
