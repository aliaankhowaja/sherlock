"""Which runs of a team passed or failed the check Z. Pure: the caller lists the threads.

Used by `sherlock-rec outcomes` so the web app can label each run "failed" or "passed" before any diagnosis.
Sherlock's own trial forks (`sherlock_fork_of` in the metadata) are not runs of the team and are left out.
"""

from sherlock.checks import Checks, evaluate


def outcomes(threads: list[dict], checks: Checks) -> list[dict]:
    rows = []
    for t in threads:
        meta = t.get("metadata") or {}
        if "sherlock_fork_of" in meta:
            continue
        row = {"thread_id": t.get("thread_id"), "created_at": t.get("created_at"), "failed": []}
        out = (t.get("values") or {}).get(checks.output_key)
        if t.get("status") == "error":
            row["outcome"] = "error"
        elif out is None:
            row["outcome"] = "no_output"
        else:
            report = evaluate(checks.assertions, out, checks.base_dir)  # as `diagnose` judges the original
            row["outcome"] = "pass" if report.passed else "fail"
            row["failed"] = [r.reason for r in report.results if not r.pass_]
        rows.append(row)
    return rows
