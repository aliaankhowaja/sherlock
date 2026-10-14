//! The run button's API: refusals (token, Origin, Host), id checks, one job at a time, polling.

use super::*;
use crate::tests::state_with;
use axum::body::{Body, to_bytes};
use axum::http::Request;
use serde_json::{Value, json};
use std::path::PathBuf;
use tower::ServiceExt;

fn project_dir(name: &str) -> PathBuf {
    let d = std::env::temp_dir().join(format!("sherlock-api-run-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(d.join(".sherlock")).unwrap();
    std::fs::create_dir_all(d.join("checks")).unwrap();
    std::fs::write(d.join(".sherlock").join("cassette.db"), b"").unwrap();
    std::fs::write(d.join("checks").join("order_desk.yaml"), "assert: []\n").unwrap();
    d
}

fn routes() -> Vec<(&'static str, Value)> {
    let run = |id: &str, meta: Value| json!({"thread_id": id, "status": "idle", "metadata": meta});
    vec![
        (
            "/assistants/search",
            json!([{"assistant_id": "a1", "graph_id": "order_desk"}]),
        ),
        (
            "/threads/search",
            json!([
                run("f-1", json!({"assistant_id": "a1"})),
                run("g-1", json!({"assistant_id": "a1"})),
                run(
                    "t-1",
                    json!({"assistant_id": "a1", "sherlock_fork_of": "f-1"})
                ),
            ]),
        ),
    ]
}

/// A state with the run button on; returns it and its token.
fn on(name: &str) -> (AppState, String) {
    let (state, _) = state_with(&routes());
    let dir = project_dir(name);
    let project = Project {
        program: "sherlock-rec-that-does-not-exist".into(),
        langgraph_url: "http://fake".into(),
        sherlock_dir: dir.join("out"),
        dir,
    };
    let state = state.with_project(Some(project), Some(3000));
    let token = state.run.token.clone();
    (state, token)
}

fn pick(failed: &str, good: &str) -> Value {
    json!({"assistant_id": "a1", "failed_thread_id": failed, "good_thread_id": good})
}

async fn call(
    state: &AppState,
    method: &str,
    uri: &str,
    headers: &[(&str, &str)],
    body: Option<Value>,
) -> (StatusCode, Value) {
    let mut req = Request::builder().method(method).uri(uri);
    for (k, v) in headers {
        req = req.header(*k, *v);
    }
    let body = match body {
        Some(b) => {
            req = req.header("content-type", "application/json");
            Body::from(b.to_string())
        }
        None => Body::empty(),
    };
    let res = crate::build_router(state.clone())
        .oneshot(req.body(body).unwrap())
        .await
        .unwrap();
    let status = res.status();
    let bytes = to_bytes(res.into_body(), 1 << 20).await.unwrap();
    (
        status,
        serde_json::from_slice(&bytes).unwrap_or(Value::Null),
    )
}

async fn post(state: &AppState, headers: &[(&str, &str)], body: Value) -> (StatusCode, Value) {
    call(state, "POST", "/api/diagnose", headers, Some(body)).await
}

#[tokio::test]
async fn info_exposes_the_token_and_whether_the_button_is_on() {
    let (state, token) = on("info");
    let (status, json) = call(&state, "GET", "/api/info", &[], None).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["token"], token.as_str());
    assert_eq!(token.len(), 32);
    assert_eq!(json["run"]["enabled"], true);
    let (off, _) = state_with(&[]);
    let (_, json) = call(&off, "GET", "/api/info", &[], None).await;
    assert_eq!(json["run"]["enabled"], false);
    assert_ne!(json["token"], token.as_str());
}

#[tokio::test]
async fn a_post_without_the_right_token_is_refused() {
    let (state, _) = on("token");
    let (status, json) = post(&state, &[], pick("f-1", "g-1")).await;
    assert_eq!(status, StatusCode::FORBIDDEN);
    assert!(
        json["error"]
            .as_str()
            .unwrap()
            .contains("missing X-Sherlock-Token")
    );
    let (status, json) = post(&state, &[(TOKEN_HEADER, "nope")], pick("f-1", "g-1")).await;
    assert_eq!(status, StatusCode::FORBIDDEN);
    assert!(json["error"].as_str().unwrap().contains("wrong"));
    assert!(state.run.board.lock().unwrap().list().is_empty());
}

#[tokio::test]
async fn a_foreign_origin_host_or_cross_site_request_is_refused() {
    let (state, token) = on("origin");
    let t = token.as_str();
    for headers in [
        vec![(TOKEN_HEADER, t), ("origin", "http://evil.example")],
        vec![(TOKEN_HEADER, t), ("origin", "http://localhost:4000")],
        vec![(TOKEN_HEADER, t), ("origin", "https://127.0.0.1:3000")],
        vec![(TOKEN_HEADER, t), ("host", "evil.example:3000")],
        vec![(TOKEN_HEADER, t), ("sec-fetch-site", "cross-site")],
    ] {
        let (status, _) = post(&state, &headers, pick("f-1", "g-1")).await;
        assert_eq!(status, StatusCode::FORBIDDEN, "{headers:?}");
    }
    // DNS rebinding: a page on another name cannot even read the token.
    let (status, _) = call(
        &state,
        "GET",
        "/api/info",
        &[("host", "evil.example:3000")],
        None,
    )
    .await;
    assert_eq!(status, StatusCode::FORBIDDEN);
    let (status, _) = call(
        &state,
        "GET",
        "/api/info",
        &[("host", "localhost:3000")],
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert!(state.run.board.lock().unwrap().list().is_empty());
}

#[tokio::test]
async fn bad_or_unlisted_ids_are_rejected_before_anything_runs() {
    let (state, token) = on("ids");
    let h = [
        (TOKEN_HEADER, token.as_str()),
        ("origin", "http://127.0.0.1:3000"),
        ("host", "127.0.0.1:3000"),
    ];
    for (body, why) in [
        (pick("../etc", "g-1"), "not a valid id"),
        (pick("f-9", "g-1"), "not a run of this team"),
        (pick("t-1", "g-1"), "Sherlock's own trial"),
        (pick("f-1", "f-1"), "different runs"),
        (
            json!({"assistant_id": "a9", "failed_thread_id": "f-1", "good_thread_id": "g-1"}),
            "no such team",
        ),
    ] {
        let (status, json) = post(&state, &h, body).await;
        assert_eq!(status, StatusCode::BAD_REQUEST);
        assert!(json["error"].as_str().unwrap().contains(why), "{json}");
    }
    assert!(state.run.board.lock().unwrap().list().is_empty());
}

#[tokio::test]
async fn only_one_job_runs_at_a_time() {
    let (state, token) = on("busy");
    let running = app_core::runner::Pick {
        graph_id: "order_desk".into(),
        failed: "f-1".into(),
        good: "g-1".into(),
    };
    state
        .run
        .board
        .lock()
        .unwrap()
        .start(&running, "cmd".into(), 0)
        .unwrap();
    let (status, json) = post(
        &state,
        &[(TOKEN_HEADER, token.as_str())],
        pick("f-1", "g-1"),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT);
    assert!(json["error"].as_str().unwrap().contains("already running"));
}

#[tokio::test]
async fn a_valid_pick_starts_the_fixed_command_and_the_job_can_be_polled() {
    let (state, token) = on("start");
    let (status, json) = post(
        &state,
        &[(TOKEN_HEADER, token.as_str())],
        json!({"team": "a1", "failed_thread_id": "f-1", "good_thread_id": "g-1"}),
    )
    .await;
    assert_eq!(status, StatusCode::ACCEPTED, "{json}");
    assert_eq!(json["job_id"], 1);
    let command = json["command"].as_str().unwrap();
    assert!(
        command.contains("diagnose --progress --thread-id f-1 --good-run g-1"),
        "{command}"
    );
    let (status, job) = call(&state, "GET", "/api/jobs/1", &[], None).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(job["state"], "failed");
    assert!(job["error"].as_str().unwrap().contains("could not start"));
    let (_, all) = call(&state, "GET", "/api/jobs", &[], None).await;
    assert_eq!(all.as_array().unwrap().len(), 1);
    assert_eq!(
        call(&state, "GET", "/api/jobs/7", &[], None).await.0,
        StatusCode::NOT_FOUND
    );
    assert_eq!(
        call(&state, "GET", "/api/jobs/x", &[], None).await.0,
        StatusCode::BAD_REQUEST
    );
}

#[tokio::test]
async fn with_the_button_off_a_post_says_how_to_turn_it_on() {
    let (state, _) = state_with(&routes());
    let (status, json) = post(&state, &[], pick("f-1", "g-1")).await;
    assert_eq!(status, StatusCode::SERVICE_UNAVAILABLE);
    assert!(json["error"].as_str().unwrap().contains("--project"));
}

#[test]
fn loopback_authorities_are_recognised() {
    assert!(loopback_authority("127.0.0.1:3000", Some(3000)));
    assert!(loopback_authority("LOCALHOST:3000", Some(3000)));
    assert!(loopback_authority("[::1]:3000", Some(3000)));
    assert!(!loopback_authority("127.0.0.1:3001", Some(3000)));
    assert!(!loopback_authority(
        "127.0.0.1.evil.example:3000",
        Some(3000)
    ));
    assert!(!loopback_authority("evil.example", None));
}
