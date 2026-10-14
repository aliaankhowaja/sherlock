//! Read-only views for the redesigned UI: a recorded run step by step, and the team's pipeline
//! graph (plain, or joined to a diagnosis). Thin: the work is in `app_core::{steps, topology}`.

use crate::{ApiError, AppState, Upstream, diagnosis_error};
use app_core::ingestion::LangGraphTransport;
use axum::{
    Json,
    extract::{Path, State},
};
use std::sync::Arc;

type Transport = Arc<dyn LangGraphTransport + Send + Sync>;

fn langgraph(state: &AppState) -> Result<Transport, ApiError> {
    match &state.upstream {
        Upstream::LangGraph(t) => Ok(t.clone()),
        Upstream::LangSmith(_) => Err(ApiError::bad_request(
            "this view needs a LangGraph server (checkpoint history and graph); start serve with --source langgraph",
        )),
    }
}

fn valid(id: &str, what: &str) -> Result<(), ApiError> {
    if app_core::runner::id_ok(id) {
        Ok(())
    } else {
        Err(ApiError::bad_request(format!("not a valid {what} id")))
    }
}

/// `GET /api/runs/{thread_id}/steps`: each node run with its input, output and hand-offs.
pub(crate) async fn run_steps(
    State(state): State<AppState>,
    Path(thread_id): Path<String>,
) -> Result<Json<app_core::steps::RunSteps>, ApiError> {
    valid(&thread_id, "thread")?;
    let t = langgraph(&state)?;
    app_core::steps::fetch_run_steps(t.as_ref(), &thread_id)
        .map(Json)
        .map_err(ApiError::bad_gateway)
}

/// `GET /api/teams/{assistant_id}/graph`: the team's pipeline laid out, no verdict.
pub(crate) async fn team_graph(
    State(state): State<AppState>,
    Path(assistant_id): Path<String>,
) -> Result<Json<app_core::topology::GraphView>, ApiError> {
    valid(&assistant_id, "team")?;
    let t = langgraph(&state)?;
    app_core::topology::graph_for_team(t.as_ref(), &assistant_id)
        .map(Json)
        .map_err(ApiError::bad_gateway)
}

/// `GET /api/diagnoses/{thread_id}/graph`: the diagnosed team's graph with verified statuses and
/// per-node evidence.
pub(crate) async fn diagnosis_graph(
    State(state): State<AppState>,
    Path(thread_id): Path<String>,
) -> Result<Json<app_core::topology::GraphView>, ApiError> {
    let d = app_core::diagnosis::DiagnosisStore::new(&state.sherlock_dir)
        .get(&thread_id)
        .map_err(diagnosis_error)?;
    let t = langgraph(&state)?;
    app_core::topology::graph_for_diagnosis(t.as_ref(), &d)
        .map(Json)
        .map_err(ApiError::bad_gateway)
}
