//! The "Run diagnosis" button. Security, decided: `serve` binds loopback only; every `/api` request
//! must name a loopback Host (DNS rebinding); a state-changing request must also carry the
//! per-process token from `GET /api/info` in `X-Sherlock-Token`, and an Origin (when sent) must be
//! this server. Only the fixed argv from `app_core::runner` is spawned (no shell), for ids the
//! LangGraph server itself lists, one job at a time.

use crate::{ApiError, AppState, fetch_runs, list_teams};
use app_core::jobs::{Board, Job};
use app_core::runner::Project;
use axum::{
    Json,
    extract::{Path, Request, State},
    http::{HeaderMap, Method, StatusCode},
    middleware::Next,
    response::{IntoResponse, Response},
};
use serde::Deserialize;
use std::sync::{Arc, Mutex};

pub const TOKEN_HEADER: &str = "x-sherlock-token";
/// Runs of the chosen team read from the server to validate a pick.
const RUNS_LIMIT: u32 = 1000;
/// A job still running after this is stopped (diagnose's own budget is 10 minutes).
pub(crate) const JOB_TIMEOUT_SECS: u64 = 15 * 60;

/// Everything the run button needs. `project: None` = the button is off.
pub struct RunState {
    pub(crate) project: Option<Project>,
    pub(crate) token: String,
    /// The port `serve` bound; when known, Host and Origin must use it.
    pub(crate) port: Option<u16>,
    pub(crate) board: Arc<Mutex<Board>>,
}

impl RunState {
    pub fn new(project: Option<Project>, port: Option<u16>) -> Self {
        Self {
            project,
            token: random_token(),
            port,
            board: Arc::new(Mutex::new(Board::default())),
        }
    }
}

/// 128 bits from the standard library's OS-seeded hasher keys; no extra dependency.
fn random_token() -> String {
    use std::hash::{BuildHasher, Hasher};
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |d| d.as_nanos());
    (0..2u8)
        .map(|i| {
            let mut h = std::collections::hash_map::RandomState::new().build_hasher();
            h.write_u128(nanos);
            h.write_u8(i);
            h.write_u32(std::process::id());
            format!("{:016x}", h.finish())
        })
        .collect()
}

pub(crate) fn now_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |d| d.as_millis() as u64)
}

/// `host[:port]` (or `[::1]:port`) names this machine, and the port matches when known.
fn loopback_authority(authority: &str, port: Option<u16>) -> bool {
    let (host, given_port) = match authority.rsplit_once(':') {
        Some((h, p)) if !h.ends_with(':') && p.chars().all(|c| c.is_ascii_digit()) => {
            (h, p.parse::<u16>().ok())
        }
        _ => (authority, None),
    };
    let host_ok = matches!(
        host.to_ascii_lowercase().as_str(),
        "127.0.0.1" | "localhost" | "[::1]"
    );
    host_ok && (port.is_none() || given_port.is_none() || given_port == port)
}

fn header<'a>(headers: &'a HeaderMap, name: &str) -> Option<&'a str> {
    headers.get(name).and_then(|v| v.to_str().ok())
}

/// Why a request must be refused, or `None` when it may proceed.
pub(crate) fn refusal(method: &Method, headers: &HeaderMap, run: &RunState) -> Option<String> {
    // Read-only server (may bind any interface): nothing can run, `start` answers 503.
    run.project.as_ref()?;
    if let Some(host) = header(headers, "host")
        && !loopback_authority(host, run.port)
    {
        return Some(format!("refused: Host `{host}` is not this local server"));
    }
    if matches!(*method, Method::GET | Method::HEAD | Method::OPTIONS) {
        return None;
    }
    if let Some(origin) = header(headers, "origin") {
        let ok = origin
            .strip_prefix("http://")
            .is_some_and(|a| loopback_authority(a, run.port));
        if !ok {
            return Some(format!(
                "refused: Origin `{origin}` is not this local server"
            ));
        }
    }
    if header(headers, "sec-fetch-site").is_some_and(|s| s != "same-origin" && s != "none") {
        return Some("refused: cross-site request".into());
    }
    match header(headers, TOKEN_HEADER) {
        Some(t) if t == run.token => None,
        Some(_) => Some("refused: wrong X-Sherlock-Token".into()),
        None => Some("refused: missing X-Sherlock-Token (read it from GET /api/info)".into()),
    }
}

/// Middleware over every route: Host check always, Origin + token on anything that changes state.
pub(crate) async fn guard(State(state): State<AppState>, req: Request, next: Next) -> Response {
    match refusal(req.method(), req.headers(), &state.run) {
        Some(why) => ApiError {
            status: StatusCode::FORBIDDEN,
            message: why,
        }
        .into_response(),
        None => next.run(req).await,
    }
}

#[derive(Deserialize)]
pub(crate) struct DiagnoseRequest {
    #[serde(alias = "team")]
    assistant_id: String,
    failed_thread_id: String,
    good_thread_id: String,
}

fn status(code: StatusCode, message: impl Into<String>) -> ApiError {
    ApiError {
        status: code,
        message: message.into(),
    }
}

/// `POST /api/diagnose`: validate the pick against the server's lists, then start the one fixed
/// command. 202 `{job_id, command}`; 400 bad pick, 409 busy, 422 project incomplete, 503 off.
pub(crate) async fn start(
    State(state): State<AppState>,
    Json(req): Json<DiagnoseRequest>,
) -> Result<(StatusCode, Json<serde_json::Value>), ApiError> {
    let project = state.run.project.clone().ok_or_else(|| {
        status(
            StatusCode::SERVICE_UNAVAILABLE,
            "the run button is off: start `sherlock serve` with --project DIR (a recorded project)",
        )
    })?;
    for id in [
        &req.assistant_id,
        &req.failed_thread_id,
        &req.good_thread_id,
    ] {
        if !app_core::runner::id_ok(id) {
            return Err(ApiError::bad_request(format!("`{id}` is not a valid id")));
        }
    }
    let teams = list_teams(&state).map_err(ApiError::bad_gateway)?;
    let mut query = app_core::ingestion::TeamRunsQuery::new(RUNS_LIMIT);
    query.assistant_id = Some(req.assistant_id.clone());
    let runs = fetch_runs(&state, &query).map_err(ApiError::bad_gateway)?;
    let pick = app_core::runner::validate_pick(
        &teams,
        &runs,
        &req.assistant_id,
        &req.failed_thread_id,
        &req.good_thread_id,
    )
    .map_err(ApiError::bad_request)?;
    let problems = project.problems(&pick.graph_id);
    if !problems.is_empty() {
        return Err(status(
            StatusCode::UNPROCESSABLE_ENTITY,
            problems.join("; "),
        ));
    }
    let argv = project
        .diagnose_argv(&pick)
        .map_err(|e| status(StatusCode::UNPROCESSABLE_ENTITY, e))?;
    let command = app_core::runner::display_command(&argv);
    let id = state
        .run
        .board
        .lock()
        .expect("job board lock")
        .start(&pick, command.clone(), now_ms())
        .map_err(|e| status(StatusCode::CONFLICT, e))?;
    crate::spawn::run_job(state.run.board.clone(), id, argv);
    Ok((
        StatusCode::ACCEPTED,
        Json(serde_json::json!({ "job_id": id, "command": command })),
    ))
}

/// `GET /api/jobs/{id}`: the job so far (poll it).
pub(crate) async fn job(
    State(state): State<AppState>,
    Path(id): Path<String>,
) -> Result<Json<Job>, ApiError> {
    let id: u64 = id
        .parse()
        .map_err(|_| ApiError::bad_request("a job id is a number"))?;
    let board = state.run.board.lock().expect("job board lock");
    board
        .get(id)
        .cloned()
        .map(Json)
        .ok_or_else(|| status(StatusCode::NOT_FOUND, format!("no job {id}")))
}

/// `GET /api/jobs`: every kept job, newest first (to find a running one after a reload).
pub(crate) async fn jobs(State(state): State<AppState>) -> Json<Vec<Job>> {
    let board = state.run.board.lock().expect("job board lock");
    Json(board.list().into_iter().cloned().collect())
}

/// What `GET /api/info` says about the run button.
pub(crate) fn info(run: &RunState) -> serde_json::Value {
    serde_json::json!({
        "enabled": run.project.is_some(),
        "project": run.project.as_ref().map(|p| p.dir.display().to_string()),
        "program": run.project.as_ref().map(|p| p.program.clone()),
        "running_job": run.board.lock().expect("job board lock").running(),
    })
}

#[cfg(test)]
#[path = "run_tests.rs"]
mod tests;
