//! The recording health checklist (FR-U7) and "no usable history" (FR-R9), plus the server version (NFR-23).

use app_core::health::check;
use app_core::ingestion::LangGraphTransport;
use app_core::steps::{fetch_run_steps, parse_steps};
use serde_json::{Value, json};

fn cp(step: i64, values: Value, tasks: Value) -> Value {
    json!({"checkpoint": {"checkpoint_id": format!("c{step}")}, "metadata": {"step": step},
           "values": values, "tasks": tasks})
}

#[test]
fn a_complete_recording_passes_every_item() {
    let h = json!([
        cp(1, json!({"out": "ok"}), json!([])),
        cp(
            0,
            json!({"q": "x"}),
            json!([{"name": "writer", "result": {"out": "ok"}}])
        ),
        cp(
            -1,
            json!({}),
            json!([{"name": "__start__", "result": {"q": "x"}}])
        ),
    ]);
    let r = parse_steps("t", &h, None).unwrap();
    assert!(r.health.usable);
    assert!(r.health.items.iter().all(|i| i.ok), "{:?}", r.health);
}

#[test]
fn an_exit_durability_run_has_no_usable_history() {
    // only the last checkpoint was written: no root, no tasks
    let h = json!([cp(3, json!({"out": "ok"}), json!([]))]);
    let health = check(&h);
    assert!(!health.usable);
    assert_eq!(health.summary, "cannot diagnose: no usable history");
    let by = |id: &str| health.items.iter().find(|i| i.id == id).unwrap();
    assert!(!by("steps").ok && !by("root").ok);
    assert!(by("final_state").ok);
}

#[test]
fn empty_history_fails_everything() {
    let health = check(&json!([]));
    assert!(!health.usable && health.items.iter().all(|i| !i.ok));
}

#[test]
fn redacted_values_are_told_apart_from_missing_ones() {
    let h = json!([
        cp(
            0,
            json!({"key": "[REDACTED]"}),
            json!([{"name": "a", "result": null}])
        ),
        cp(
            -1,
            json!({}),
            json!([{"name": "__start__", "result": {"key": "[REDACTED]"}}])
        ),
    ]);
    let health = check(&h);
    let io = health.items.iter().find(|i| i.id == "io").unwrap();
    assert!(!io.ok);
    assert!(
        io.detail.contains("1 output missing") && io.detail.contains("redacted"),
        "{}",
        io.detail
    );
}

struct Fake(Value);
impl LangGraphTransport for Fake {
    fn post_json(&self, _: &str, _: Value) -> anyhow::Result<Value> {
        Ok(self.0.clone())
    }
    fn get_json(&self, path: &str) -> anyhow::Result<Value> {
        if path == "/info" {
            Ok(json!({"version": "0.4.1"}))
        } else {
            anyhow::bail!("no graph")
        }
    }
}

#[test]
fn the_langgraph_server_version_is_recorded_with_the_run() {
    let h = json!([cp(
        -1,
        json!({}),
        json!([{"name": "__start__", "result": {}}])
    )]);
    let r = fetch_run_steps(&Fake(h), "t-1").unwrap();
    assert_eq!(r.server_version.as_deref(), Some("0.4.1"));
}
