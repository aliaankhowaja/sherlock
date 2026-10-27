> **Working note (tier 3). Not authoritative.** It may be stale or wrong. Facts come from the code and from docs/eval. Never cite this file in anything submitted to the university.

# Web API (contract for the UI)

`sherlock serve [--project DIR] [--sherlock-rec PATH] [--sherlock-dir DIR] [--langgraph-url URL]`. Same-origin `/api/*`,
JSON. Errors are `{"error": "plain words"}` with 400 (bad input/id), 403 (refused by the guard), 404, 409 (busy),
422 (invalid artifact / project incomplete), 502 (LangGraph failed), 503 (run button off). Ids: `[A-Za-z0-9._-]`,
at most 64, no leading `.`/`-`. Views over checkpoints and graphs need the LangGraph source (400 on LangSmith).

Read endpoints:

- `GET /api/info` -> `{source, url, sherlock_dir, token, run: {enabled, project, program, running_job}}`.
  `token` is random per `serve` process; send it back as `X-Sherlock-Token` on `POST`.
- `GET /api/teams` -> `[{assistant_id, graph_id, name}]`; `GET /api/runs?assistant_id=&limit=&offset=` ->
  `[{thread_id, status, assistant_id, created_at, metadata}]` (`metadata.sherlock_fork_of` = Sherlock's own trial run);
  `GET /api/logs?thread_id=` -> `{thread_id, events: [{checkpoint_id, step, node, writes, error, run_id, created_at}]}`.
- `GET /api/runs/{thread_id}/steps` -> a recorded run replayed (`app_core::steps`):
  ```
  {thread_id, graph_id, assistant_id, note,          // note: e.g. graph unavailable -> no kinds, hand-offs by order
   final_state: {key: value},
   steps: [{index, step,                             // step = LangGraph superstep; -1 = run input; parallel nodes share it
            checkpoint_id, node, kind,               // kind: "deterministic" | "llm" | "tool" | null
            input: {key: value},                     // state the node received
            changed: [key],                          // keys just handed over (differ from the previous step)
            input_from: [{node, keys: [key]}],       // which upstream node last wrote which input key
            output: {key: value} | null,             // tasks[].result; becomes later steps' input
            error: string | null, started_at, finished_at, duration_ms,
            log: ["retriever received source=\"compliance_db\"", "retriever produced documents=[2 items] in 3 ms"]}],
   edges: [{source, target, keys: [key]}]}          // hand-offs seen (source ran in the step before target), on the topology
  ```
  Values are size-capped: strings over 400 chars cut (`... (+N chars)`), lists/maps over 20 items shortened
  (`"... (+N more)"`, key `"..."`).
- `GET /api/teams/{assistant_id}/graph` -> `GraphView` with no verdict (the pick step).
- `GET /api/diagnoses` -> `{dir, diagnoses: [summary], invalid: [{file, error}]}`; `GET /api/diagnoses/{thread_id}` ->
  `{summary: {thread_id, graph_id, created, status, reason_code, reason, minimal_sets, complete, trials_used, fewer_pct},
  nodes: [NodeVerdict], artifact}`.
- `GET /api/diagnoses/{thread_id}/graph` -> `GraphView` joined to that verdict:
  ```
  {nodes: [{id, role: "start"|"end"|"node", kind, status: "culprit"|"cleared"|"unverified"|"abstained"|null, reason,
            layer, row,                              // x = layer (column, left to right), y = row (may be fractional)
            verdict: NodeVerdict | null,             // {node, status, reason, sets, clues, trials: [n], restore, pruned,
                                                     //  tested, on_path}; restore = known-good context difference
            faults: [string]}],                      // run-context fault flags attributed to the node
   edges: [{source, target, conditional, back, on_path}], layers, rows, note, known_good_source}  // thread id
  ```

The run button (live diagnosis):

- `POST /api/diagnose`, headers `Content-Type: application/json` + `X-Sherlock-Token: <token>`, body
  `{assistant_id (alias team), failed_thread_id, good_thread_id}` -> 202 `{job_id, command}`. 400 when an id is
  malformed, the team or a run is not on the server's lists, a run is Sherlock's own trial, or failed == good;
  409 while another job runs; 422 when the project lacks the recording or the team's check; 503 when the button is off.
- `GET /api/jobs/{id}` (poll about once a second) -> `{id, graph_id, failed, good, command,
  state: "running"|"done"|"failed", events: [...], log: [string], exit_code, error, artifact_id, started_ms,
  finished_ms}`. `done` = a verdict was written: open `GET /api/diagnoses/{artifact_id}` (and `/graph`). `failed` =
  no verdict; `error` says why. `GET /api/jobs` -> every kept job, newest first (find a running one after a reload).
- `events` are the `sherlock-rec diagnose --progress` JSON lines, each with `event` and `at_ms` (ms since start):
  `start {thread_id, graph_id, nodes_on_path, clues}`, `check {pass, failed: [reason]}`, `sources {sources: [...]}`,
  `plan {source, candidates, pruned: {node: why}, max_trials, max_size, exhaustive_trials}`, then per trial
  `trial_start {n, restored}`, `fork {restored, fork_node, fork_thread}`, `resume {fork_thread}`,
  `rerun {restored, fork_node, fork_thread, steps: [{node, step, restored, input, output, error}]}` (each node that
  ran again, oldest first; `restored` marks the nodes given known-good behaviour; capped like `/steps`),
  `trial {n, restored, verdict, label, reason, fork_node, fork_thread, elapsed_s, ...}`; always last
  `done {status: "found"|"abstain", reason_code, reason, minimal_sets, trials_used}`. Unknown events: ignore.
- Security (decided, see docs/history/status-log.md decision log): `serve` refuses `--project` on a non-loopback `--host`; when the button
  is on, every request must carry a loopback `Host` (127.0.0.1, localhost, [::1]; port = serve's), so a DNS-rebound
  page cannot read the token; `POST` also needs the token, an `Origin` (when sent) of `http://` + loopback + port,
  and no `Sec-Fetch-Site: cross-site`. Only the fixed `sherlock-rec diagnose --progress` argv from `app_core::runner`
  is spawned (no shell), for ids the server lists; one job at a time; stopped after 15 minutes.
- Project layout (`--project DIR`, default `<sherlock-dir>/lab` or the parent of a project's `.sherlock`, whichever
  holds a recording): `DIR/.sherlock/cassette.db`, `DIR/checks/<graph_id>.yaml` (else `DIR/sherlock.yaml`), optional
  `DIR/checks/<graph_id>.node-map.json`; the verdict goes to `<sherlock-dir>/diagnoses/`. The live demo
  (`eval/live_demo.py OUTDIR`) writes exactly this: `sherlock serve --langgraph-url <SERVER> --sherlock-dir OUTDIR
  --sherlock-rec <python/sherlock/.venv/Scripts/sherlock-rec(.exe)>`.
