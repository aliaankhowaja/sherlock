//! Live smoke test for the ingestion module against a real LangGraph API.
//!
//! Hermetic by default: does nothing unless `SHERLOCK_LIVE_URL` is set, e.g.
//!
//! ```sh
//! SHERLOCK_LIVE_URL=http://127.0.0.1:2024 \
//!   cargo test -p app-core --test live_langgraph -- --nocapture
//! ```
//!
//! Uses the `curl` binary as HTTP transport so `app-core` gains no new
//! dependencies; the domain logic under test is unchanged.

use app_core::ingestion::{
    LangGraphTransport, RunLogsQuery, TeamRunsQuery, fetch_run_logs, fetch_team_runs, list_teams,
};
use std::process::Command;

/// `LangGraphTransport` backed by the `curl` CLI.
struct CurlTransport {
    base_url: String,
}

impl LangGraphTransport for CurlTransport {
    fn post_json(&self, path: &str, body: serde_json::Value) -> anyhow::Result<serde_json::Value> {
        let url = format!("{}{}", self.base_url, path);
        let out = Command::new("curl")
            .args([
                "-s",
                "-m",
                "30",
                "-X",
                "POST",
                &url,
                "-H",
                "Content-Type: application/json",
                "-d",
                &body.to_string(),
            ])
            .output()?;
        if !out.status.success() {
            anyhow::bail!("curl failed for {url}: {}", out.status);
        }
        let text = String::from_utf8(out.stdout)?;
        serde_json::from_str(&text)
            .map_err(|e| anyhow::anyhow!("non-JSON reply from {url}: {e}\n{text:.500}"))
    }
}

#[test]
fn live_langgraph_ingestion() {
    let base_url = match std::env::var("SHERLOCK_LIVE_URL") {
        Ok(url) => url,
        Err(_) => {
            println!("SHERLOCK_LIVE_URL not set; skipping live test");
            return;
        }
    };
    let transport = CurlTransport { base_url };

    // 1. Teams (assistants).
    let teams = list_teams(&transport).expect("list_teams against live API");
    println!("teams: {}", teams.len());
    for team in &teams {
        println!(
            "  team assistant_id={} graph_id={} name={:?}",
            team.assistant_id, team.graph_id, team.name
        );
    }
    assert!(!teams.is_empty(), "expected at least one assistant");

    // 2. Team runs (threads), unfiltered then filtered by team.
    let all_runs = fetch_team_runs(&transport, &TeamRunsQuery::new(50))
        .expect("fetch_team_runs against live API");
    println!("threads (unfiltered): {}", all_runs.len());
    assert!(!all_runs.is_empty(), "expected at least one thread");
    let first_team = all_runs
        .iter()
        .find_map(|r| r.assistant_id.clone())
        .expect("expected a thread tagged with metadata.assistant_id");
    println!("filtering threads by assistant_id={first_team}");
    let filtered = fetch_team_runs(
        &transport,
        &TeamRunsQuery {
            limit: 50,
            offset: 0,
            assistant_id: Some(first_team.clone()),
        },
    )
    .expect("filtered fetch_team_runs against live API");
    println!("threads (filtered): {}", filtered.len());
    assert!(
        !filtered.is_empty(),
        "expected threads for assistant {first_team}"
    );
    assert!(
        filtered
            .iter()
            .all(|r| r.assistant_id.as_deref() == Some(first_team.as_str())),
        "every filtered thread must carry the requested assistant_id"
    );

    // 3. Run logs: first thread (in listed order) that has checkpoints.
    let with_history = all_runs
        .iter()
        .map(|r| {
            (
                r.thread_id.clone(),
                fetch_run_logs(&transport, &r.thread_id, &RunLogsQuery::new(100)),
            )
        })
        .find(|(_, result)| result.as_ref().is_ok_and(|logs| !logs.events.is_empty()));
    let (thread_id, logs) = match with_history {
        Some((id, Ok(logs))) => (id, logs),
        _ => panic!("expected at least one thread with checkpoint history"),
    };
    println!("thread {thread_id}: {} events", logs.events.len());
    for event in logs.events.iter().take(10) {
        println!(
            "  step={:?} node={} run={:?} error={:?} checkpoint={:?}",
            event.step, event.node, event.run_id, event.error, event.checkpoint_id
        );
    }

    // 4. Run-scoped logs, when attribution is available.
    if let Some(run_id) = logs.events.iter().find_map(|e| e.run_id.clone()) {
        let scoped = fetch_run_logs(
            &transport,
            &thread_id,
            &RunLogsQuery {
                limit: 100,
                run_id: Some(run_id.clone()),
            },
        )
        .expect("run-scoped fetch_run_logs against live API");
        println!(
            "thread {thread_id} run {run_id}: {} events",
            scoped.events.len()
        );
        assert!(!scoped.events.is_empty());
        assert!(
            scoped
                .events
                .iter()
                .all(|e| e.run_id.as_deref() == Some(run_id.as_str()))
        );
    } else {
        println!("no run_id attribution present; skipping run-scoped check");
    }
}
