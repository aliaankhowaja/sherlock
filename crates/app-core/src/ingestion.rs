//! Ingestion of LangGraph data for the debugger.
//!
//! Maps LangGraph concepts to sherlock terms:
//! - agentic team  -> assistant (`POST /assistants/search`)
//! - team run      -> thread (`POST /threads/search`); a thread holds the
//!   accumulated checkpoints of a group of runs and is the unit of replay.
//!   LangGraph does not index threads by assistant server-side, so team
//!   association uses the `assistant_id` thread-metadata convention (set it
//!   when creating threads); without it, pass no filter and match client-side.
//! - run logs      -> checkpoint history (`POST /threads/{id}/history`),
//!   expanded to one event per writing node so fault isolation can blame a
//!   single agent. Attribution to a single run uses `metadata.run_id`.
//!
//! The module does no I/O itself: callers inject a [`LangGraphTransport`]
//! (real HTTP lives outside `app-core`; tests use a fake). This keeps
//! `app-core` free of CLI/HTTP/UI dependencies per `agents.md`.

use std::collections::HashMap;

/// LangGraph API paths used by this module.
pub const ASSISTANTS_SEARCH_PATH: &str = "/assistants/search";
pub const THREADS_SEARCH_PATH: &str = "/threads/search";

/// Path for checkpoint history of one thread.
pub fn thread_history_path(thread_id: &str) -> String {
    format!("/threads/{thread_id}/history")
}

/// Minimal transport over the LangGraph local API.
///
/// Implemented with real HTTP outside `app-core`; faked in tests.
pub trait LangGraphTransport {
    fn post_json(&self, path: &str, body: serde_json::Value) -> anyhow::Result<serde_json::Value>;
}

/// An agentic team: a configured instance of a graph.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
pub struct Team {
    pub assistant_id: String,
    pub graph_id: String,
    pub name: Option<String>,
}

/// Filter for listing team runs (threads).
#[derive(Debug, Clone, Default)]
pub struct TeamRunsQuery {
    /// Page size for `POST /threads/search`.
    pub limit: u32,
    /// Offset for `POST /threads/search`.
    pub offset: u32,
    /// When set, sent as `metadata.assistant_id` server-side filter
    /// (requires threads created with that metadata key).
    pub assistant_id: Option<String>,
}

impl TeamRunsQuery {
    pub fn new(limit: u32) -> Self {
        Self {
            limit,
            offset: 0,
            assistant_id: None,
        }
    }
}

/// One team run: a thread holding the checkpoints of its runs.
#[derive(Debug, Clone, PartialEq, serde::Serialize)]
pub struct TeamRun {
    pub thread_id: String,
    pub status: Option<String>,
    /// Team association via thread metadata convention; `None` when untagged.
    pub assistant_id: Option<String>,
    pub created_at: Option<String>,
    pub metadata: serde_json::Value,
}

/// Filter for fetching run logs.
#[derive(Debug, Clone, Default)]
pub struct RunLogsQuery {
    /// Page size for `POST /threads/{id}/history`.
    pub limit: u32,
    /// When set, keep only events whose checkpoint `metadata.run_id` matches.
    pub run_id: Option<String>,
}

impl RunLogsQuery {
    pub fn new(limit: u32) -> Self {
        Self {
            limit,
            run_id: None,
        }
    }
}

/// One per-node log event derived from a checkpoint.
#[derive(Debug, Clone, PartialEq, serde::Serialize)]
pub struct RunEvent {
    pub checkpoint_id: Option<String>,
    pub step: Option<i64>,
    pub node: String,
    pub writes: serde_json::Value,
    pub error: Option<String>,
    pub run_id: Option<String>,
    pub created_at: Option<String>,
}

/// Logs for one team run, in server order (most recent checkpoint first).
#[derive(Debug, Clone, PartialEq, serde::Serialize)]
pub struct RunLogs {
    pub thread_id: String,
    pub events: Vec<RunEvent>,
}

/// List all agentic teams (`POST /assistants/search` with `{}`).
pub fn list_teams(transport: &dyn LangGraphTransport) -> anyhow::Result<Vec<Team>> {
    let raw = transport.post_json(ASSISTANTS_SEARCH_PATH, serde_json::json!({}))?;
    parse_teams(&raw)
}

/// Fetch team runs (threads), optionally filtered by team via metadata.
pub fn fetch_team_runs(
    transport: &dyn LangGraphTransport,
    query: &TeamRunsQuery,
) -> anyhow::Result<Vec<TeamRun>> {
    let mut body = serde_json::json!({"limit": query.limit, "offset": query.offset});
    if let Some(team) = &query.assistant_id {
        body["metadata"] = serde_json::json!({"assistant_id": team});
    }
    let raw = transport.post_json(THREADS_SEARCH_PATH, body)?;
    parse_team_runs(&raw)
}

/// Fetch run logs (checkpoint history) for one team run.
pub fn fetch_run_logs(
    transport: &dyn LangGraphTransport,
    thread_id: &str,
    query: &RunLogsQuery,
) -> anyhow::Result<RunLogs> {
    if thread_id.is_empty() {
        anyhow::bail!("thread_id must not be empty");
    }
    let raw = transport.post_json(
        &thread_history_path(thread_id),
        serde_json::json!({"limit": query.limit}),
    )?;
    parse_run_logs(thread_id, &raw, query.run_id.as_deref())
}

fn required_str(value: &serde_json::Value, field: &str) -> anyhow::Result<String> {
    value
        .get(field)
        .and_then(|v| v.as_str())
        .map(str::to_string)
        .ok_or_else(|| anyhow::anyhow!("missing required field '{field}' in: {value}"))
}

fn optional_str(value: &serde_json::Value, field: &str) -> Option<String> {
    value.get(field)?.as_str().map(str::to_string)
}

fn parse_teams(raw: &serde_json::Value) -> anyhow::Result<Vec<Team>> {
    let items = raw
        .as_array()
        .ok_or_else(|| anyhow::anyhow!("expected JSON array for assistants, got: {raw}"))?;
    items
        .iter()
        .map(|item| {
            Ok(Team {
                assistant_id: required_str(item, "assistant_id")?,
                graph_id: required_str(item, "graph_id")?,
                name: optional_str(item, "name"),
            })
        })
        .collect()
}

fn parse_team_runs(raw: &serde_json::Value) -> anyhow::Result<Vec<TeamRun>> {
    let items = raw
        .as_array()
        .ok_or_else(|| anyhow::anyhow!("expected JSON array for threads, got: {raw}"))?;
    items
        .iter()
        .map(|item| {
            let metadata = item.get("metadata").cloned().unwrap_or_default();
            Ok(TeamRun {
                thread_id: required_str(item, "thread_id")?,
                status: optional_str(item, "status"),
                assistant_id: metadata
                    .get("assistant_id")
                    .and_then(|v| v.as_str())
                    .map(str::to_string),
                created_at: optional_str(item, "created_at"),
                metadata,
            })
        })
        .collect()
}

/// Errors recorded against tasks of one checkpoint, keyed by node name.
fn task_errors(state: &serde_json::Value) -> HashMap<String, String> {
    let mut errors = HashMap::new();
    for task in state
        .get("tasks")
        .and_then(|t| t.as_array())
        .into_iter()
        .flatten()
    {
        if let (Some(name), Some(error)) = (
            task.get("name").and_then(|n| n.as_str()),
            task.get("error").and_then(|e| e.as_str()),
        ) {
            errors
                .entry(name.to_string())
                .or_insert_with(|| error.to_string());
        }
    }
    errors
}

fn parse_run_logs(
    thread_id: &str,
    raw: &serde_json::Value,
    run_id_filter: Option<&str>,
) -> anyhow::Result<RunLogs> {
    let states = raw
        .as_array()
        .ok_or_else(|| anyhow::anyhow!("expected JSON array for history, got: {raw}"))?;
    let mut events = Vec::new();
    for state in states {
        let checkpoint_id = state
            .get("checkpoint")
            .and_then(|c| c.get("checkpoint_id"))
            .and_then(|v| v.as_str())
            .map(str::to_string);
        let metadata = state.get("metadata");
        let step = metadata
            .and_then(|m| m.get("step"))
            .and_then(|s| s.as_i64());
        let run_id = metadata
            .and_then(|m| m.get("run_id"))
            .and_then(|v| v.as_str())
            .map(str::to_string);
        if let Some(wanted) = run_id_filter
            && run_id.as_deref() != Some(wanted)
        {
            continue;
        }
        let created_at = optional_str(state, "created_at");
        let errors = task_errors(state);
        let writes = metadata
            .and_then(|m| m.get("writes"))
            .and_then(|w| w.as_object());
        match writes {
            Some(map) if !map.is_empty() => {
                for (node, payload) in map {
                    events.push(RunEvent {
                        checkpoint_id: checkpoint_id.clone(),
                        step,
                        node: node.clone(),
                        writes: payload.clone(),
                        error: errors.get(node).cloned(),
                        run_id: run_id.clone(),
                        created_at: created_at.clone(),
                    });
                }
            }
            _ => {
                // No writes: surface errored tasks, else one placeholder so no
                // checkpoint is silently dropped from the debugger timeline.
                let mut errored: Vec<(&String, &String)> = errors.iter().collect();
                errored.sort_by(|a, b| a.0.cmp(b.0));
                if errored.is_empty() {
                    events.push(RunEvent {
                        checkpoint_id: checkpoint_id.clone(),
                        step,
                        node: "unknown".to_string(),
                        writes: serde_json::Value::Null,
                        error: None,
                        run_id: run_id.clone(),
                        created_at: created_at.clone(),
                    });
                } else {
                    for (node, error) in errored {
                        events.push(RunEvent {
                            checkpoint_id: checkpoint_id.clone(),
                            step,
                            node: node.to_string(),
                            writes: serde_json::Value::Null,
                            error: Some(error.to_string()),
                            run_id: run_id.clone(),
                            created_at: created_at.clone(),
                        });
                    }
                }
            }
        }
    }
    Ok(RunLogs {
        thread_id: thread_id.to_string(),
        events,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::RefCell;

    /// Fake transport returning canned JSON and recording requests.
    struct Fake {
        response: serde_json::Value,
        fail_with: Option<String>,
        seen: RefCell<Vec<(String, serde_json::Value)>>,
    }

    impl Fake {
        fn ok(response: serde_json::Value) -> Self {
            Self {
                response,
                fail_with: None,
                seen: RefCell::new(Vec::new()),
            }
        }

        fn failing(msg: &str) -> Self {
            Self {
                response: serde_json::Value::Null,
                fail_with: Some(msg.to_string()),
                seen: RefCell::new(Vec::new()),
            }
        }
    }

    impl LangGraphTransport for Fake {
        fn post_json(
            &self,
            path: &str,
            body: serde_json::Value,
        ) -> anyhow::Result<serde_json::Value> {
            self.seen
                .borrow_mut()
                .push((path.to_string(), body.clone()));
            if let Some(msg) = &self.fail_with {
                return Err(anyhow::anyhow!("{msg}"));
            }
            Ok(self.response.clone())
        }
    }

    fn assistant_fixture() -> serde_json::Value {
        serde_json::json!([
            {"assistant_id": "a1", "graph_id": "triage", "name": "triage-team",
             "metadata": {}},
            {"assistant_id": "a2", "graph_id": "triage"}
        ])
    }

    fn threads_fixture() -> serde_json::Value {
        serde_json::json!([
            {"thread_id": "t1", "status": "idle",
             "metadata": {"assistant_id": "a1"},
             "created_at": "2026-01-01T00:00:00Z"},
            {"thread_id": "t2", "status": "error",
             "metadata": {},
             "created_at": "2026-01-02T00:00:00Z"}
        ])
    }

    fn history_fixture() -> serde_json::Value {
        serde_json::json!([
            {"values": {}, "next": [],
             "checkpoint": {"thread_id": "t1", "checkpoint_ns": "",
                            "checkpoint_id": "c2"},
             "metadata": {"step": 2, "source": "loop", "run_id": "r2",
                          "writes": {"router": {"route": "nurse"}}},
             "created_at": "2026-01-01T00:02:00Z",
             "tasks": [{"id": "x", "name": "router"}]},
            {"values": {}, "next": ["nurse"],
             "checkpoint": {"thread_id": "t1", "checkpoint_ns": "",
                            "checkpoint_id": "c1"},
             "metadata": {"step": 1, "source": "loop", "run_id": "r1",
                          "writes": {}},
             "created_at": "2026-01-01T00:01:00Z",
             "tasks": [{"id": "y", "name": "nurse", "error": "boom"}]},
            {"values": {}, "next": [],
             "checkpoint": {"thread_id": "t1", "checkpoint_ns": "",
                            "checkpoint_id": "c0"},
             "metadata": {"step": 0, "source": "input", "run_id": "r1"},
             "created_at": "2026-01-01T00:00:00Z",
             "tasks": []}
        ])
    }

    #[test]
    fn list_teams_posts_to_assistants_search_with_empty_body() {
        let fake = Fake::ok(assistant_fixture());
        let teams = list_teams(&fake).expect("list_teams should parse fixture");
        assert_eq!(fake.seen.borrow().len(), 1);
        let (path, body) = &fake.seen.borrow()[0];
        assert_eq!(path, ASSISTANTS_SEARCH_PATH);
        assert_eq!(*body, serde_json::json!({}));
        assert_eq!(teams.len(), 2);
        assert_eq!(teams[0].assistant_id, "a1");
        assert_eq!(teams[0].graph_id, "triage");
        assert_eq!(teams[0].name.as_deref(), Some("triage-team"));
        assert_eq!(teams[1].name, None);
    }

    #[test]
    fn list_teams_errors_on_missing_assistant_id() {
        let fake = Fake::ok(serde_json::json!([{"graph_id": "triage"}]));
        assert!(list_teams(&fake).is_err());
    }

    #[test]
    fn list_teams_propagates_transport_errors() {
        let fake = Fake::failing("server down");
        let err = format!("{:?}", list_teams(&fake).expect_err("should fail"));
        assert!(err.contains("server down"), "got: {err}");
    }

    #[test]
    fn fetch_team_runs_sends_limit_offset_and_metadata_filter() {
        let fake = Fake::ok(threads_fixture());
        let query = TeamRunsQuery {
            limit: 5,
            offset: 10,
            assistant_id: Some("a1".to_string()),
        };
        let runs = fetch_team_runs(&fake, &query).expect("should parse");
        let (path, body) = &fake.seen.borrow()[0];
        assert_eq!(path, THREADS_SEARCH_PATH);
        assert_eq!(body["limit"], 5);
        assert_eq!(body["offset"], 10);
        assert_eq!(body["metadata"]["assistant_id"], "a1");
        assert_eq!(runs.len(), 2);
        assert_eq!(runs[0].thread_id, "t1");
        assert_eq!(runs[0].assistant_id.as_deref(), Some("a1"));
        assert_eq!(runs[0].status.as_deref(), Some("idle"));
        assert_eq!(runs[1].assistant_id, None);
    }

    #[test]
    fn fetch_team_runs_omits_metadata_when_no_team_filter() {
        let fake = Fake::ok(serde_json::json!([]));
        let runs = fetch_team_runs(&fake, &TeamRunsQuery::new(10)).expect("ok");
        assert!(runs.is_empty());
        let (_, body) = &fake.seen.borrow()[0];
        assert!(
            body.get("metadata").is_none(),
            "no metadata filter expected, got: {body}"
        );
    }

    #[test]
    fn fetch_team_runs_errors_on_missing_thread_id() {
        let fake = Fake::ok(serde_json::json!([{"status": "idle"}]));
        assert!(fetch_team_runs(&fake, &TeamRunsQuery::new(10)).is_err());
    }

    #[test]
    fn fetch_run_logs_hits_thread_history_path() {
        let fake = Fake::ok(history_fixture());
        let logs = fetch_run_logs(&fake, "t1", &RunLogsQuery::new(50)).expect("parse");
        let (path, body) = &fake.seen.borrow()[0];
        assert_eq!(path, "/threads/t1/history");
        assert_eq!(body["limit"], 50);
        assert_eq!(logs.thread_id, "t1");
    }

    #[test]
    fn fetch_run_logs_rejects_empty_thread_id_without_request() {
        let fake = Fake::ok(history_fixture());
        assert!(fetch_run_logs(&fake, "", &RunLogsQuery::new(10)).is_err());
        assert!(fake.seen.borrow().is_empty());
    }

    #[test]
    fn fetch_run_logs_expands_writes_to_per_node_events() {
        let fake = Fake::ok(history_fixture());
        let logs = fetch_run_logs(&fake, "t1", &RunLogsQuery::new(50)).expect("parse");
        // c2 -> 1 router event; c1 -> 1 nurse error event;
        // c0 -> 1 synthesized "unknown" event (no writes, no tasks).
        assert_eq!(logs.events.len(), 3);
        assert_eq!(logs.events[0].node, "router");
        assert_eq!(logs.events[0].writes, serde_json::json!({"route": "nurse"}));
        assert_eq!(logs.events[0].step, Some(2));
        assert_eq!(logs.events[0].checkpoint_id.as_deref(), Some("c2"));
        assert_eq!(logs.events[0].error, None);
        assert_eq!(logs.events[1].node, "nurse");
        assert_eq!(logs.events[1].error.as_deref(), Some("boom"));
        assert_eq!(logs.events[2].node, "unknown");
    }

    #[test]
    fn fetch_run_logs_filters_by_run_id() {
        let fake = Fake::ok(history_fixture());
        let query = RunLogsQuery {
            limit: 50,
            run_id: Some("r1".to_string()),
        };
        let logs = fetch_run_logs(&fake, "t1", &query).expect("parse");
        assert_eq!(logs.events.len(), 2);
        assert!(
            logs.events
                .iter()
                .all(|e| e.run_id.as_deref() == Some("r1"))
        );
    }

    #[test]
    fn fetch_run_logs_empty_history_yields_no_events() {
        let fake = Fake::ok(serde_json::json!([]));
        let logs = fetch_run_logs(&fake, "t1", &RunLogsQuery::new(10)).expect("parse");
        assert!(logs.events.is_empty());
    }
}
