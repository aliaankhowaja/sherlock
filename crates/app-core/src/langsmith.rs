//! LangSmith trace intake.
//!
//! LangGraph checkpoint APIs are not available for traces that only live in
//! LangSmith. This module maps those traces onto the same [`Team`], [`TeamRun`],
//! and [`RunLogs`] types the dashboard already renders:
//! - team ← `metadata.assistant_id` + `metadata.graph_id` on a root run
//! - team run ← `thread_id`
//! - log event ← each run in that thread (one node / model / tool call)

use crate::ingestion::{RunEvent, RunLogs, RunLogsQuery, Team, TeamRun, TeamRunsQuery};

pub const SESSIONS_PATH: &str = "/sessions";
pub const RUNS_QUERY_PATH: &str = "/runs/query";

/// HTTP access to the LangSmith REST API. Implemented outside `app-core`.
pub trait LangSmithTransport {
    fn get_json(&self, path: &str) -> anyhow::Result<serde_json::Value>;
    fn post_json(&self, path: &str, body: serde_json::Value) -> anyhow::Result<serde_json::Value>;
}

/// List teams from recent root traces.
pub fn list_teams(transport: &dyn LangSmithTransport) -> anyhow::Result<Vec<Team>> {
    let roots = fetch_root_runs(transport, 100)?;
    Ok(teams_from_roots(&roots))
}

/// List threads, optionally limited to one assistant.
pub fn fetch_team_runs(
    transport: &dyn LangSmithTransport,
    query: &TeamRunsQuery,
) -> anyhow::Result<Vec<TeamRun>> {
    let roots = fetch_root_runs(transport, 100)?;
    Ok(runs_from_roots(&roots, query))
}

/// Per-node events for one LangGraph thread stored as LangSmith runs.
pub fn fetch_run_logs(
    transport: &dyn LangSmithTransport,
    thread_id: &str,
    query: &RunLogsQuery,
) -> anyhow::Result<RunLogs> {
    if thread_id.is_empty() {
        anyhow::bail!("thread_id must not be empty");
    }
    if thread_id.contains(['"', '\\']) {
        anyhow::bail!("thread_id contains characters that cannot be used in a LangSmith filter");
    }
    let limit = query.limit.clamp(1, 200);
    let filter = format!("eq(thread_id, \"{thread_id}\")");
    let mut events = Vec::new();
    for session_id in session_ids(transport)? {
        let raw = transport.post_json(
            RUNS_QUERY_PATH,
            serde_json::json!({
                "session": [session_id],
                "filter": filter,
                "limit": limit,
            }),
        )?;
        events.extend(events_from_runs(&runs_of(&raw)?, query.run_id.as_deref()));
    }
    Ok(RunLogs {
        thread_id: thread_id.to_string(),
        events,
    })
}

fn fetch_root_runs(
    transport: &dyn LangSmithTransport,
    limit: u32,
) -> anyhow::Result<Vec<serde_json::Value>> {
    let mut roots = Vec::new();
    for session_id in session_ids(transport)? {
        let raw = transport.post_json(
            RUNS_QUERY_PATH,
            serde_json::json!({
                "session": [session_id],
                "is_root": true,
                "limit": limit,
            }),
        )?;
        roots.extend(runs_of(&raw)?);
    }
    Ok(roots)
}

fn session_ids(transport: &dyn LangSmithTransport) -> anyhow::Result<Vec<String>> {
    let raw = transport.get_json(SESSIONS_PATH)?;
    let items = if let Some(items) = raw.as_array() {
        items
    } else if let Some(items) = raw.get("sessions").and_then(|v| v.as_array()) {
        items
    } else {
        anyhow::bail!("expected a JSON array of LangSmith sessions, got: {raw}");
    };
    items
        .iter()
        .map(|item| {
            item.get("id")
                .and_then(|v| v.as_str())
                .map(str::to_string)
                .ok_or_else(|| anyhow::anyhow!("session missing id: {item}"))
        })
        .collect()
}

fn runs_of(raw: &serde_json::Value) -> anyhow::Result<Vec<serde_json::Value>> {
    raw.get("runs")
        .and_then(|v| v.as_array())
        .cloned()
        .ok_or_else(|| anyhow::anyhow!("expected runs array, got: {raw}"))
}

fn meta(run: &serde_json::Value) -> Option<&serde_json::Value> {
    run.pointer("/extra/metadata")
}

fn assistant_id_of(run: &serde_json::Value) -> Option<String> {
    meta(run)
        .and_then(|m| m.get("assistant_id"))
        .and_then(|v| v.as_str())
        .map(str::to_string)
}

fn graph_id_of(run: &serde_json::Value) -> Option<String> {
    meta(run)
        .and_then(|m| m.get("graph_id"))
        .and_then(|v| v.as_str())
        .map(str::to_string)
        .or_else(|| run.get("name").and_then(|v| v.as_str()).map(str::to_string))
}

fn thread_id_of(run: &serde_json::Value) -> Option<String> {
    run.get("thread_id")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .map(str::to_string)
        .or_else(|| {
            meta(run)
                .and_then(|m| m.get("thread_id"))
                .and_then(|v| v.as_str())
                .filter(|s| !s.is_empty())
                .map(str::to_string)
        })
}

/// Unique assistants, first-seen order (LangSmith returns newest roots first).
fn teams_from_roots(roots: &[serde_json::Value]) -> Vec<Team> {
    let mut teams = Vec::new();
    let mut seen = std::collections::HashSet::new();
    for run in roots {
        let Some(graph_id) = graph_id_of(run) else {
            continue;
        };
        let assistant_id = assistant_id_of(run).unwrap_or_else(|| graph_id.clone());
        if !seen.insert(assistant_id.clone()) {
            continue;
        }
        teams.push(Team {
            assistant_id,
            name: Some(graph_id.clone()),
            graph_id,
        });
    }
    teams
}

fn runs_from_roots(roots: &[serde_json::Value], query: &TeamRunsQuery) -> Vec<TeamRun> {
    let mut runs = Vec::new();
    let mut seen = std::collections::HashSet::new();
    for run in roots {
        let assistant_id = assistant_id_of(run);
        if let Some(wanted) = &query.assistant_id
            && assistant_id.as_deref() != Some(wanted.as_str())
        {
            continue;
        }
        let Some(thread_id) = thread_id_of(run) else {
            continue;
        };
        if !seen.insert(thread_id.clone()) {
            continue;
        }
        runs.push(TeamRun {
            thread_id,
            status: run
                .get("status")
                .and_then(|v| v.as_str())
                .map(str::to_string),
            assistant_id,
            created_at: run
                .get("start_time")
                .and_then(|v| v.as_str())
                .map(str::to_string),
            metadata: meta(run).cloned().unwrap_or(serde_json::Value::Null),
        });
    }
    let start = query.offset as usize;
    runs.into_iter()
        .skip(start)
        .take(query.limit as usize)
        .collect()
}

fn events_from_runs(runs: &[serde_json::Value], run_id_filter: Option<&str>) -> Vec<RunEvent> {
    let mut events = Vec::new();
    for run in runs {
        let run_id = run
            .pointer("/extra/metadata/run_id")
            .and_then(|v| v.as_str())
            .map(str::to_string)
            .or_else(|| {
                run.get("trace_id")
                    .and_then(|v| v.as_str())
                    .map(str::to_string)
            });
        if let Some(wanted) = run_id_filter
            && run_id.as_deref() != Some(wanted)
        {
            continue;
        }
        let status = run.get("status").and_then(|v| v.as_str());
        events.push(RunEvent {
            checkpoint_id: run.get("id").and_then(|v| v.as_str()).map(str::to_string),
            step: run.get("execution_order").and_then(|v| v.as_i64()),
            node: run
                .get("name")
                .and_then(|v| v.as_str())
                .unwrap_or("unknown")
                .to_string(),
            writes: writes_of(run),
            error: (status == Some("error")).then(|| error_line(run)).flatten(),
            run_id,
            created_at: run
                .get("start_time")
                .and_then(|v| v.as_str())
                .map(str::to_string),
        });
    }
    events
}

fn writes_of(run: &serde_json::Value) -> serde_json::Value {
    match run.get("outputs_preview") {
        Some(value) if !value.is_null() => serde_json::json!({ "preview": clip(value) }),
        _ => serde_json::Value::Null,
    }
}

fn clip(value: &serde_json::Value) -> String {
    let text = value
        .as_str()
        .map(str::to_string)
        .unwrap_or_else(|| value.to_string());
    text.chars().take(500).collect()
}

fn error_line(run: &serde_json::Value) -> Option<String> {
    let raw = run.get("error")?.as_str()?;
    let line = raw.lines().next().unwrap_or(raw).trim();
    if line.is_empty() {
        None
    } else {
        Some(line.chars().take(400).collect())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::RefCell;

    struct Fake {
        sessions: serde_json::Value,
        roots: serde_json::Value,
        thread_runs: serde_json::Value,
        seen: RefCell<Vec<(String, serde_json::Value)>>,
    }

    impl LangSmithTransport for Fake {
        fn get_json(&self, path: &str) -> anyhow::Result<serde_json::Value> {
            self.seen
                .borrow_mut()
                .push((format!("GET {path}"), serde_json::Value::Null));
            if path == SESSIONS_PATH {
                Ok(self.sessions.clone())
            } else {
                anyhow::bail!("unexpected GET {path}");
            }
        }

        fn post_json(
            &self,
            path: &str,
            body: serde_json::Value,
        ) -> anyhow::Result<serde_json::Value> {
            self.seen
                .borrow_mut()
                .push((format!("POST {path}"), body.clone()));
            if path != RUNS_QUERY_PATH {
                anyhow::bail!("unexpected POST {path}");
            }
            if body.get("is_root") == Some(&serde_json::Value::Bool(true)) {
                Ok(self.roots.clone())
            } else {
                Ok(self.thread_runs.clone())
            }
        }
    }

    fn sample() -> Fake {
        Fake {
            sessions: serde_json::json!([{"id": "sess-1", "name": "default"}]),
            roots: serde_json::json!({"runs": [
                {
                    "id": "run-new",
                    "name": "open_deep_research_multi_agent",
                    "status": "error",
                    "start_time": "2026-10-07T08:50:11Z",
                    "thread_id": "thread-1",
                    "trace_id": "run-new",
                    "extra": {"metadata": {
                        "assistant_id": "asst-1",
                        "graph_id": "open_deep_research_multi_agent",
                        "thread_id": "thread-1",
                        "run_id": "run-new"
                    }}
                },
                {
                    "id": "run-old",
                    "name": "open_deep_research_multi_agent",
                    "status": "success",
                    "start_time": "2026-10-06T17:20:23Z",
                    "thread_id": "thread-2",
                    "trace_id": "run-old",
                    "extra": {"metadata": {
                        "assistant_id": "asst-1",
                        "graph_id": "open_deep_research_multi_agent",
                        "thread_id": "thread-2",
                        "run_id": "run-old"
                    }}
                }
            ]}),
            thread_runs: serde_json::json!({"runs": [
                {
                    "id": "child-1",
                    "name": "supervisor",
                    "status": "error",
                    "start_time": "2026-10-07T08:50:11Z",
                    "thread_id": "thread-1",
                    "trace_id": "run-new",
                    "execution_order": 2,
                    "error": "OpenAIError('Missing credentials')\nTraceback...",
                    "outputs_preview": "failed",
                    "extra": {"metadata": {"run_id": "run-new"}}
                },
                {
                    "id": "child-2",
                    "name": "research_agent",
                    "status": "success",
                    "start_time": "2026-10-07T08:50:10Z",
                    "thread_id": "thread-1",
                    "trace_id": "run-new",
                    "execution_order": 1,
                    "outputs_preview": "notes",
                    "extra": {"metadata": {"run_id": "run-new"}}
                }
            ]}),
            seen: RefCell::new(Vec::new()),
        }
    }

    #[test]
    fn list_teams_groups_root_traces_by_assistant() {
        let fake = sample();
        let teams = list_teams(&fake).unwrap();
        assert_eq!(teams.len(), 1);
        assert_eq!(teams[0].assistant_id, "asst-1");
        assert_eq!(teams[0].graph_id, "open_deep_research_multi_agent");
        assert_eq!(
            teams[0].name.as_deref(),
            Some("open_deep_research_multi_agent")
        );
    }

    #[test]
    fn fetch_team_runs_filters_by_assistant_and_pages() {
        let fake = sample();
        let runs = fetch_team_runs(
            &fake,
            &TeamRunsQuery {
                limit: 1,
                offset: 0,
                assistant_id: Some("asst-1".to_string()),
            },
        )
        .unwrap();
        assert_eq!(runs.len(), 1);
        assert_eq!(runs[0].thread_id, "thread-1");
        assert_eq!(runs[0].status.as_deref(), Some("error"));
        assert_eq!(runs[0].assistant_id.as_deref(), Some("asst-1"));
    }

    #[test]
    fn fetch_run_logs_maps_child_runs_to_node_events() {
        let fake = sample();
        let logs = fetch_run_logs(&fake, "thread-1", &RunLogsQuery::new(50)).unwrap();
        assert_eq!(logs.thread_id, "thread-1");
        assert_eq!(logs.events.len(), 2);
        assert_eq!(logs.events[0].node, "supervisor");
        assert_eq!(
            logs.events[0].error.as_deref(),
            Some("OpenAIError('Missing credentials')")
        );
        assert_eq!(logs.events[1].node, "research_agent");
        assert!(logs.events[1].error.is_none());
        assert_eq!(logs.events[0].run_id.as_deref(), Some("run-new"));
    }
}
