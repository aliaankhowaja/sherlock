use anyhow::Result;
use axum::{
    Json,
    extract::{Query, State},
    http::{StatusCode, header},
    response::{Html, IntoResponse, Response},
    routing::get,
};
use rust_embed::RustEmbed;
use serde::Deserialize;
use std::path::PathBuf;

mod run;
mod spawn;
mod views;

pub use app_core::runner::Project;

#[derive(RustEmbed, Clone)]
#[folder = "../../ui/dist/"]
struct Assets;

pub struct ServeOptions {
    pub host: String,
    pub port: u16,
    /// Base URL of the LangGraph API server proxied by `/api/*`.
    pub langgraph_url: String,
    /// Sent as X-Api-Key; only needed by secured LangGraph servers.
    pub langgraph_api_key: Option<String>,
    /// When set, `/api/teams|runs|logs` read LangSmith traces instead of LangGraph.
    pub langsmith_api_key: Option<String>,
    /// LangSmith API origin. Ignored when `langsmith_api_key` is absent.
    pub langsmith_url: String,
    /// Sherlock's local state directory; diagnoses are read from `<dir>/diagnoses/`.
    pub sherlock_dir: PathBuf,
    /// The recorded project the run button diagnoses (`.sherlock/cassette.db`, `checks/`).
    /// `None`: discovered next to `sherlock_dir`, else the button is off.
    pub project: Option<PathBuf>,
    /// The `sherlock-rec` program the run button starts.
    pub sherlock_rec: String,
}

impl ServeOptions {
    pub fn addr(&self) -> String {
        format!("{}:{}", self.host, self.port)
    }

    pub fn base_url(&self) -> String {
        format!("http://{}:{}", self.host, self.port)
    }
}

/// True when the compile-time embedded `ui/dist` contains real built files.
/// Ignores the `.gitkeep` placeholder that keeps the folder present for builds.
pub fn has_ui_assets() -> bool {
    has_real_assets(Assets::iter().map(|n| n.to_string()))
}

fn has_real_assets(mut names: impl Iterator<Item = String>) -> bool {
    names.any(|name| name != ".gitkeep")
}

pub fn missing_dist_error() -> anyhow::Error {
    anyhow::anyhow!(
        "UI dist not found (ui/dist is empty or missing). \
         Build the frontend first: cd ui && npm install && npm run build"
    )
}

/// Filesystem fallback for dev (`cargo run` before rebuild): look for
/// `ui/dist` relative to CWD and relative to the crate manifest dir.
fn filesystem_dist_dir() -> Option<PathBuf> {
    let candidates = [
        PathBuf::from("ui/dist"),
        PathBuf::from("../ui/dist"),
        PathBuf::from("../../ui/dist"),
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../ui/dist"),
    ];
    candidates
        .into_iter()
        .find(|p| p.join("index.html").is_file())
}

fn content_type(path: &str) -> String {
    mime_guess::from_path(path)
        .first_or_octet_stream()
        .to_string()
}

fn embedded_file(path: &str) -> Option<(String, Vec<u8>)> {
    Assets::get(path)
        .filter(|_| path != ".gitkeep")
        .map(|f| (content_type(path), f.data.to_vec()))
}

fn disk_file(path: &str) -> Option<(String, Vec<u8>)> {
    let dir = filesystem_dist_dir()?;
    // Guard against path traversal: only serve paths inside dist.
    if path.contains("..") {
        return None;
    }
    let full = dir.join(path.trim_start_matches('/'));
    std::fs::read(full)
        .ok()
        .map(|bytes| (content_type(path), bytes))
}

fn ui_file(path: &str) -> Option<(String, Vec<u8>)> {
    embedded_file(path).or_else(|| disk_file(path))
}

async fn health() -> impl IntoResponse {
    Json(serde_json::json!({ "status": "ok" }))
}

/// Which upstream the dashboard reads. Built live in `serve`, faked in tests.
#[derive(Clone)]
enum Upstream {
    LangGraph(std::sync::Arc<dyn app_core::ingestion::LangGraphTransport + Send + Sync>),
    LangSmith(std::sync::Arc<dyn app_core::langsmith::LangSmithTransport + Send + Sync>),
}

/// Shared state for `/api/*`. Handlers stay thin controllers over `app-core`.
#[derive(Clone)]
pub struct AppState {
    upstream: Upstream,
    /// Where runs are read from, shown to the user in the guided steps.
    source: (&'static str, String),
    sherlock_dir: PathBuf,
    run: std::sync::Arc<run::RunState>,
}

impl AppState {
    pub fn new(langgraph_url: String, langgraph_api_key: Option<String>) -> Self {
        Self {
            source: ("langgraph", langgraph_url.clone()),
            upstream: Upstream::LangGraph(std::sync::Arc::new(HttpTransport {
                base_url: langgraph_url,
                api_key: langgraph_api_key,
            })),
            sherlock_dir: PathBuf::from(".sherlock"),
            run: std::sync::Arc::new(run::RunState::new(None, None)),
        }
    }

    pub fn with_sherlock_dir(mut self, dir: PathBuf) -> Self {
        self.sherlock_dir = dir;
        self
    }

    /// Turn the run button on for `project` (LangGraph source only); `port` is the bound port.
    pub fn with_project(mut self, project: Option<Project>, port: Option<u16>) -> Self {
        self.run = std::sync::Arc::new(run::RunState::new(project, port));
        self
    }

    pub fn langsmith(langsmith_url: String, langsmith_api_key: String) -> Self {
        Self {
            source: ("langsmith", langsmith_url.clone()),
            upstream: Upstream::LangSmith(std::sync::Arc::new(LangSmithHttp::new(
                langsmith_url.trim_end_matches('/').to_string(),
                langsmith_api_key,
            ))),
            sherlock_dir: PathBuf::from(".sherlock"),
            run: std::sync::Arc::new(run::RunState::new(None, None)),
        }
    }
}

/// Blocking HTTP transport over the LangGraph API. The trait is sync by
/// design (runtime-agnostic `app-core`); the few sequential requests of a
/// local debugger do not justify a second async client.
struct HttpTransport {
    base_url: String,
    api_key: Option<String>,
}

impl app_core::ingestion::LangGraphTransport for HttpTransport {
    fn post_json(&self, path: &str, body: serde_json::Value) -> anyhow::Result<serde_json::Value> {
        let url = format!("{}{}", self.base_url, path);
        let mut request = ureq::post(&url);
        if let Some(key) = &self.api_key {
            request = request.header("X-Api-Key", key);
        }
        let mut response = request
            .send_json(body)
            .map_err(|e| anyhow::anyhow!("POST {url} failed: {e}"))?;
        response
            .body_mut()
            .read_json()
            .map_err(|e| anyhow::anyhow!("invalid JSON from {url}: {e}"))
    }

    fn get_json(&self, path: &str) -> anyhow::Result<serde_json::Value> {
        let url = format!("{}{}", self.base_url, path);
        let mut request = ureq::get(&url);
        if let Some(key) = &self.api_key {
            request = request.header("X-Api-Key", key);
        }
        let mut response = request
            .call()
            .map_err(|e| anyhow::anyhow!("GET {url} failed: {e}"))?;
        response
            .body_mut()
            .read_json()
            .map_err(|e| anyhow::anyhow!("invalid JSON from {url}: {e}"))
    }
}

/// Blocking HTTP transport over the LangSmith REST API (`x-api-key`).
///
/// The dashboard asks for teams and then runs back to back. Both read the same
/// root traces, so replies are cached briefly. HTTP 429 is retried.
struct LangSmithHttp {
    base_url: String,
    api_key: String,
    agent: ureq::Agent,
    cache: std::sync::Mutex<
        std::collections::HashMap<String, (std::time::Instant, serde_json::Value)>,
    >,
}

impl LangSmithHttp {
    fn new(base_url: String, api_key: String) -> Self {
        let config = ureq::Agent::config_builder()
            .http_status_as_error(false)
            .build();
        Self {
            base_url,
            api_key,
            agent: config.into(),
            cache: std::sync::Mutex::new(std::collections::HashMap::new()),
        }
    }

    fn cached(
        &self,
        key: &str,
        fetch: impl FnOnce() -> anyhow::Result<serde_json::Value>,
    ) -> anyhow::Result<serde_json::Value> {
        const TTL: std::time::Duration = std::time::Duration::from_secs(45);
        if let Ok(cache) = self.cache.lock()
            && let Some((at, value)) = cache.get(key)
            && at.elapsed() < TTL
        {
            return Ok(value.clone());
        }
        match fetch() {
            Ok(value) => {
                if let Ok(mut cache) = self.cache.lock() {
                    cache.insert(key.to_string(), (std::time::Instant::now(), value.clone()));
                }
                Ok(value)
            }
            Err(err) => {
                if let Ok(cache) = self.cache.lock()
                    && let Some((_, value)) = cache.get(key)
                {
                    eprintln!("LangSmith request failed ({err}); using cached reply");
                    return Ok(value.clone());
                }
                Err(err)
            }
        }
    }

    fn send(
        &self,
        url: &str,
        body: Option<&serde_json::Value>,
    ) -> anyhow::Result<serde_json::Value> {
        let mut wait = std::time::Duration::from_secs(2);
        for attempt in 0..5 {
            let call = match body {
                None => self
                    .agent
                    .get(url)
                    .header("x-api-key", &self.api_key)
                    .call(),
                Some(body) => self
                    .agent
                    .post(url)
                    .header("x-api-key", &self.api_key)
                    .send_json(body),
            };
            let mut response = call.map_err(|e| anyhow::anyhow!("{url} failed: {e}"))?;
            let status = response.status().as_u16();
            if status == 429 && attempt < 4 {
                let pause = response
                    .headers()
                    .get("retry-after")
                    .and_then(|v| v.to_str().ok())
                    .and_then(|v| v.parse::<u64>().ok())
                    .map(|secs| std::time::Duration::from_secs(secs.clamp(1, 20)))
                    .unwrap_or(wait);
                eprintln!(
                    "LangSmith rate limit (429) on {url}; retrying in {}s",
                    pause.as_secs()
                );
                std::thread::sleep(pause);
                wait = (wait * 2).min(std::time::Duration::from_secs(20));
                continue;
            }
            if status == 429 {
                anyhow::bail!(
                    "{url} failed: http status: 429. LangSmith is rate limiting this key. Wait about a minute, then press Refresh."
                );
            }
            if !(200..300).contains(&status) {
                anyhow::bail!("{url} failed: http status: {status}");
            }
            return response
                .body_mut()
                .read_json()
                .map_err(|e| anyhow::anyhow!("invalid JSON from {url}: {e}"));
        }
        anyhow::bail!("{url} failed: http status: 429")
    }
}

impl app_core::langsmith::LangSmithTransport for LangSmithHttp {
    fn get_json(&self, path: &str) -> anyhow::Result<serde_json::Value> {
        let url = format!("{}{}", self.base_url, path);
        self.cached(&format!("GET {path}"), || self.send(&url, None))
    }

    fn post_json(&self, path: &str, body: serde_json::Value) -> anyhow::Result<serde_json::Value> {
        let url = format!("{}{}", self.base_url, path);
        let key = format!("POST {path} {body}");
        self.cached(&key, || self.send(&url, Some(&body)))
    }
}

/// JSON error envelope. LangGraph failures surface as 502 (bad gateway:
/// sherlock is up, the upstream is not), client mistakes as 400.
struct ApiError {
    status: StatusCode,
    message: String,
}

impl ApiError {
    fn bad_request(message: impl Into<String>) -> Self {
        Self {
            status: StatusCode::BAD_REQUEST,
            message: message.into(),
        }
    }

    fn bad_gateway(err: anyhow::Error) -> Self {
        Self {
            status: StatusCode::BAD_GATEWAY,
            message: format!("{err:#}"),
        }
    }
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        (
            self.status,
            Json(serde_json::json!({ "error": self.message })),
        )
            .into_response()
    }
}

fn default_runs_limit() -> u32 {
    20
}

fn default_logs_limit() -> u32 {
    50
}

#[derive(Deserialize)]
struct RunsParams {
    assistant_id: Option<String>,
    #[serde(default = "default_runs_limit")]
    limit: u32,
    #[serde(default)]
    offset: u32,
}

#[derive(Deserialize)]
struct LogsParams {
    thread_id: Option<String>,
    #[serde(default = "default_logs_limit")]
    limit: u32,
    run_id: Option<String>,
}

fn list_teams(state: &AppState) -> anyhow::Result<Vec<app_core::ingestion::Team>> {
    match &state.upstream {
        Upstream::LangGraph(transport) => app_core::ingestion::list_teams(transport.as_ref()),
        Upstream::LangSmith(transport) => app_core::langsmith::list_teams(transport.as_ref()),
    }
}

fn fetch_runs(
    state: &AppState,
    query: &app_core::ingestion::TeamRunsQuery,
) -> anyhow::Result<Vec<app_core::ingestion::TeamRun>> {
    match &state.upstream {
        Upstream::LangGraph(transport) => {
            app_core::ingestion::fetch_team_runs(transport.as_ref(), query)
        }
        Upstream::LangSmith(transport) => {
            app_core::langsmith::fetch_team_runs(transport.as_ref(), query)
        }
    }
}

fn fetch_logs(
    state: &AppState,
    thread_id: &str,
    query: &app_core::ingestion::RunLogsQuery,
) -> anyhow::Result<app_core::ingestion::RunLogs> {
    match &state.upstream {
        Upstream::LangGraph(transport) => {
            app_core::ingestion::fetch_run_logs(transport.as_ref(), thread_id, query)
        }
        Upstream::LangSmith(transport) => {
            app_core::langsmith::fetch_run_logs(transport.as_ref(), thread_id, query)
        }
    }
}

async fn teams(
    State(state): State<AppState>,
) -> Result<Json<Vec<app_core::ingestion::Team>>, ApiError> {
    list_teams(&state).map(Json).map_err(ApiError::bad_gateway)
}

async fn runs(
    State(state): State<AppState>,
    Query(params): Query<RunsParams>,
) -> Result<Json<Vec<app_core::ingestion::TeamRun>>, ApiError> {
    fetch_runs(
        &state,
        &app_core::ingestion::TeamRunsQuery {
            limit: params.limit,
            offset: params.offset,
            assistant_id: params.assistant_id,
        },
    )
    .map(Json)
    .map_err(ApiError::bad_gateway)
}

async fn logs(
    State(state): State<AppState>,
    Query(params): Query<LogsParams>,
) -> Result<Json<app_core::ingestion::RunLogs>, ApiError> {
    let thread_id = params
        .thread_id
        .filter(|id| !id.is_empty())
        .ok_or_else(|| ApiError::bad_request("missing required query param: thread_id"))?;
    fetch_logs(
        &state,
        &thread_id,
        &app_core::ingestion::RunLogsQuery {
            limit: params.limit,
            run_id: params.run_id,
        },
    )
    .map(Json)
    .map_err(ApiError::bad_gateway)
}

/// What the guided steps need to build a runnable command: which server the
/// runs come from and where diagnoses are read.
async fn info(State(state): State<AppState>) -> impl IntoResponse {
    let server_version = match &state.upstream {
        Upstream::LangGraph(t) => app_core::steps::server_version(t.as_ref()),
        Upstream::LangSmith(_) => None,
    };
    Json(serde_json::json!({
        "server_version": server_version,
        "source": state.source.0,
        "url": state.source.1,
        "sherlock_dir": state.sherlock_dir.display().to_string(),
        "token": state.run.token,
        "run": run::info(&state.run),
    }))
}

async fn diagnoses(State(state): State<AppState>) -> Json<app_core::diagnosis::DiagnosisList> {
    Json(app_core::diagnosis::DiagnosisStore::new(&state.sherlock_dir).list())
}

async fn diagnosis(
    State(state): State<AppState>,
    axum::extract::Path(thread_id): axum::extract::Path<String>,
) -> Result<Json<app_core::diagnosis::Diagnosis>, ApiError> {
    app_core::diagnosis::DiagnosisStore::new(&state.sherlock_dir)
        .get(&thread_id)
        .map(Json)
        .map_err(diagnosis_error)
}

fn diagnosis_error(e: app_core::diagnosis::DiagnosisError) -> ApiError {
    use app_core::diagnosis::DiagnosisError;
    ApiError {
        status: match e {
            DiagnosisError::BadId(_) => StatusCode::BAD_REQUEST,
            DiagnosisError::NotFound(_) => StatusCode::NOT_FOUND,
            DiagnosisError::Invalid(_) => StatusCode::UNPROCESSABLE_ENTITY,
        },
        message: e.to_string(),
    }
}

async fn serve_ui(uri: axum::http::Uri) -> impl IntoResponse {
    let raw_path = uri.path().trim_start_matches('/');
    let path = if raw_path.is_empty() {
        "index.html"
    } else {
        raw_path
    };

    if let Some((mime, bytes)) = ui_file(path) {
        return (StatusCode::OK, [(header::CONTENT_TYPE, mime)], bytes).into_response();
    }

    // SPA fallback: client-side routes resolve to index.html.
    if let Some((_, bytes)) = ui_file("index.html") {
        return Html(bytes).into_response();
    }

    // Dist was never built: actionable error, not an empty 404.
    let msg = format!("{:#}", missing_dist_error());
    (StatusCode::SERVICE_UNAVAILABLE, msg).into_response()
}

pub fn build_router(state: AppState) -> axum::Router {
    axum::Router::new()
        .route("/api/health", get(health))
        .route("/api/teams", get(teams))
        .route("/api/runs", get(runs))
        .route("/api/logs", get(logs))
        .route("/api/info", get(info))
        .route("/api/diagnoses", get(diagnoses))
        .route("/api/diagnoses/{thread_id}", get(diagnosis))
        .route(
            "/api/diagnoses/{thread_id}/graph",
            get(views::diagnosis_graph),
        )
        .route("/api/runs/{thread_id}/steps", get(views::run_steps))
        .route("/api/teams/{assistant_id}/graph", get(views::team_graph))
        .route("/api/diagnose", axum::routing::post(run::start))
        .route("/api/intake", axum::routing::post(run::intake))
        .route("/api/jobs", get(run::jobs))
        .route("/api/jobs/{id}", get(run::job))
        .fallback(serve_ui)
        .layer(axum::middleware::from_fn_with_state(
            state.clone(),
            run::guard,
        ))
        .with_state(state)
}

fn ui_available() -> bool {
    has_ui_assets() || filesystem_dist_dir().is_some()
}

fn is_loopback(host: &str) -> bool {
    matches!(host, "127.0.0.1" | "localhost" | "::1" | "[::1]")
}

/// The project the run button may diagnose: `--project`, else discovered next to the diagnoses.
/// Off for a LangSmith source; refused outright on a non-loopback interface.
fn run_project(opts: &ServeOptions) -> Result<Option<Project>> {
    if opts.langsmith_api_key.is_some() {
        return Ok(None);
    }
    let Some(dir) = opts
        .project
        .clone()
        .or_else(|| Project::discover(&opts.sherlock_dir))
    else {
        return Ok(None);
    };
    if !is_loopback(&opts.host) {
        anyhow::bail!(
            "the run button only listens on this machine: use --host 127.0.0.1 (or drop --project)"
        );
    }
    Ok(Some(Project {
        dir: std::path::absolute(&dir)?,
        program: opts.sherlock_rec.clone(),
        langgraph_url: opts.langgraph_url.clone(),
        sherlock_dir: std::path::absolute(&opts.sherlock_dir)?,
    }))
}

pub async fn serve(opts: ServeOptions) -> Result<()> {
    if !ui_available() {
        return Err(missing_dist_error());
    }
    let project = run_project(&opts)?;
    let listener = tokio::net::TcpListener::bind(opts.addr()).await?;
    println!("Serving sherlock at {}", opts.base_url());
    let state = if let Some(key) = opts.langsmith_api_key.clone() {
        println!("Ingestion source: LangSmith ({})", opts.langsmith_url);
        AppState::langsmith(opts.langsmith_url.clone(), key)
    } else {
        println!("Ingestion source: LangGraph ({})", opts.langgraph_url);
        AppState::new(opts.langgraph_url.clone(), opts.langgraph_api_key.clone())
    }
    .with_sherlock_dir(opts.sherlock_dir.clone());
    println!(
        "Diagnoses: {}",
        opts.sherlock_dir.join("diagnoses").display()
    );
    match &project {
        Some(p) => println!(
            "Run button: on (project {}, program {})",
            p.dir.display(),
            p.program
        ),
        None => println!("Run button: off (no recorded project; pass --project DIR)"),
    }
    let state = state.with_project(project, Some(opts.port));
    axum::serve(listener, build_router(state))
        .with_graceful_shutdown(async {
            let _ = tokio::signal::ctrl_c().await;
        })
        .await?;
    Ok(())
}

#[cfg(test)]
pub(crate) mod tests {
    use super::*;
    use axum::body::{Body, to_bytes};
    use axum::http::{Request, StatusCode};
    use std::collections::HashMap;
    use std::sync::{Arc, Mutex};
    use tower::ServiceExt;

    /// Fake LangGraph transport: canned JSON per path, records requests.
    pub(crate) type SeenRequests = Arc<Mutex<Vec<(String, serde_json::Value)>>>;

    struct FakeTransport {
        routes: HashMap<String, serde_json::Value>,
        seen: SeenRequests,
    }

    impl app_core::ingestion::LangGraphTransport for FakeTransport {
        fn post_json(
            &self,
            path: &str,
            body: serde_json::Value,
        ) -> anyhow::Result<serde_json::Value> {
            self.seen
                .lock()
                .expect("lock")
                .push((path.to_string(), body));
            self.routes
                .get(path)
                .cloned()
                .ok_or_else(|| anyhow::anyhow!("no LangGraph route for {path}"))
        }

        fn get_json(&self, path: &str) -> anyhow::Result<serde_json::Value> {
            self.post_json(path, serde_json::Value::Null)
        }
    }

    pub(crate) fn state_with(routes: &[(&str, serde_json::Value)]) -> (AppState, SeenRequests) {
        let seen = Arc::new(Mutex::new(Vec::new()));
        let fake = FakeTransport {
            routes: routes
                .iter()
                .map(|(p, v)| (p.to_string(), v.clone()))
                .collect(),
            seen: seen.clone(),
        };
        (
            AppState {
                upstream: Upstream::LangGraph(Arc::new(fake)),
                source: ("langgraph", "http://fake".to_string()),
                sherlock_dir: PathBuf::from("does-not-exist"),
                run: Arc::new(run::RunState::new(None, None)),
            },
            seen,
        )
    }

    fn assistant_fixture() -> serde_json::Value {
        serde_json::json!([
            {"assistant_id": "a1", "graph_id": "triage", "name": "triage-team"},
            {"assistant_id": "a2", "graph_id": "triage"}
        ])
    }

    fn threads_fixture() -> serde_json::Value {
        serde_json::json!([
            {"thread_id": "t1", "status": "idle",
             "metadata": {"assistant_id": "a1"},
             "created_at": "2026-01-01T00:00:00Z"}
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
            {"values": {}, "next": [],
             "checkpoint": {"thread_id": "t1", "checkpoint_ns": "",
                            "checkpoint_id": "c1"},
             "metadata": {"step": 1, "source": "loop", "run_id": "r1",
                          "writes": {}},
             "created_at": "2026-01-01T00:01:00Z",
             "tasks": [{"id": "y", "name": "nurse", "error": "boom"}]}
        ])
    }

    async fn get(router: axum::Router, uri: &str) -> (StatusCode, serde_json::Value) {
        let req = Request::builder().uri(uri).body(Body::empty()).unwrap();
        let res = router.oneshot(req).await.unwrap();
        let status = res.status();
        let body = to_bytes(res.into_body(), 65536).await.unwrap();
        let json: serde_json::Value =
            serde_json::from_slice(&body).unwrap_or(serde_json::Value::Null);
        (status, json)
    }

    #[tokio::test]
    async fn health_endpoint_returns_ok_status() {
        let (state, _) = state_with(&[]);
        let (status, json) = get(build_router(state), "/api/health").await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(json["status"], "ok");
    }

    #[test]
    fn reports_missing_ui_dist_with_actionable_message() {
        let err = missing_dist_error();
        let msg = format!("{err:#}");
        assert!(
            msg.contains("ui/dist"),
            "error should mention ui/dist, got: {msg}"
        );
        assert!(
            msg.contains("npm run build"),
            "error should tell user to build UI, got: {msg}"
        );
    }

    #[test]
    fn ignores_gitkeep_placeholder_when_detecting_dist() {
        assert!(!has_real_assets(Vec::<String>::new().into_iter()));
        assert!(!has_real_assets(vec![".gitkeep".to_string()].into_iter()));
        assert!(has_real_assets(vec!["index.html".to_string()].into_iter()));
        assert!(has_real_assets(
            vec![".gitkeep".to_string(), "assets/app.js".to_string()].into_iter()
        ));
    }

    #[test]
    fn serve_options_format_addr_and_url() {
        let opts = ServeOptions {
            host: "127.0.0.1".to_string(),
            port: 3000,
            langgraph_url: "http://127.0.0.1:2024".to_string(),
            langgraph_api_key: None,
            langsmith_api_key: None,
            langsmith_url: "https://api.smith.langchain.com".to_string(),
            sherlock_dir: PathBuf::from(".sherlock"),
            project: None,
            sherlock_rec: "sherlock-rec".to_string(),
        };
        assert_eq!(opts.addr(), "127.0.0.1:3000");
        assert_eq!(opts.base_url(), "http://127.0.0.1:3000");
    }

    #[test]
    fn the_run_button_needs_loopback_and_a_langgraph_source() {
        let opts = |host: &str, project: Option<PathBuf>, langsmith: Option<String>| ServeOptions {
            host: host.to_string(),
            port: 3000,
            langgraph_url: "http://127.0.0.1:2024".to_string(),
            langgraph_api_key: None,
            langsmith_api_key: langsmith,
            langsmith_url: String::new(),
            sherlock_dir: PathBuf::from("does-not-exist"),
            project,
            sherlock_rec: "sherlock-rec".to_string(),
        };
        let lab = Some(PathBuf::from("lab"));
        let p = run_project(&opts("127.0.0.1", lab.clone(), None))
            .unwrap()
            .unwrap();
        assert!(p.dir.is_absolute() && p.dir.ends_with("lab"));
        assert_eq!(p.program, "sherlock-rec");
        let err = run_project(&opts("0.0.0.0", lab.clone(), None)).unwrap_err();
        assert!(err.to_string().contains("--host 127.0.0.1"));
        assert!(run_project(&opts("0.0.0.0", None, None)).unwrap().is_none());
        assert!(
            run_project(&opts("127.0.0.1", lab, Some("k".into())))
                .unwrap()
                .is_none()
        );
    }

    #[tokio::test]
    async fn teams_endpoint_returns_assistants_as_json() {
        let (state, seen) = state_with(&[("/assistants/search", assistant_fixture())]);
        let (status, json) = get(build_router(state), "/api/teams").await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(json.as_array().expect("array").len(), 2);
        assert_eq!(json[0]["assistant_id"], "a1");
        assert_eq!(json[0]["graph_id"], "triage");
        let (path, body) = &seen.lock().expect("lock")[0];
        assert_eq!(path, "/assistants/search");
        assert_eq!(*body, serde_json::json!({}));
    }

    #[tokio::test]
    async fn runs_endpoint_forwards_filter_and_paging() {
        let (state, seen) = state_with(&[("/threads/search", threads_fixture())]);
        let (status, json) = get(
            build_router(state),
            "/api/runs?assistant_id=a1&limit=5&offset=10",
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(json[0]["thread_id"], "t1");
        assert_eq!(json[0]["assistant_id"], "a1");
        let (path, body) = &seen.lock().expect("lock")[0];
        assert_eq!(path, "/threads/search");
        assert_eq!(body["limit"], 5);
        assert_eq!(body["offset"], 10);
        assert_eq!(body["metadata"]["assistant_id"], "a1");
    }

    #[tokio::test]
    async fn runs_endpoint_defaults_limit_and_no_team_filter() {
        let (state, seen) = state_with(&[("/threads/search", serde_json::json!([]))]);
        let (status, json) = get(build_router(state), "/api/runs").await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(json, serde_json::json!([]));
        let (_, body) = &seen.lock().expect("lock")[0];
        assert_eq!(body["limit"], 20);
        assert_eq!(body["offset"], 0);
        assert!(
            body.get("metadata").is_none(),
            "no metadata filter expected, got: {body}"
        );
    }

    #[tokio::test]
    async fn logs_endpoint_requires_thread_id() {
        let (state, seen) = state_with(&[]);
        let (status, json) = get(build_router(state), "/api/logs").await;
        assert_eq!(status, StatusCode::BAD_REQUEST);
        assert!(
            json["error"].as_str().unwrap_or("").contains("thread_id"),
            "got: {json}"
        );
        assert!(seen.lock().expect("lock").is_empty());
    }

    #[tokio::test]
    async fn logs_endpoint_returns_events_and_forwards_run_filter() {
        let (state, seen) = state_with(&[("/threads/t1/history", history_fixture())]);
        let (status, json) = get(
            build_router(state),
            "/api/logs?thread_id=t1&limit=7&run_id=r1",
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(json["thread_id"], "t1");
        assert_eq!(json["events"].as_array().unwrap().len(), 1);
        assert_eq!(json["events"][0]["node"], "nurse");
        assert_eq!(json["events"][0]["error"], "boom");
        let (path, body) = &seen.lock().expect("lock")[0];
        assert_eq!(path, "/threads/t1/history");
        assert_eq!(body["limit"], 7);
    }

    #[tokio::test]
    async fn langgraph_failure_maps_to_502_json() {
        let (state, _) = state_with(&[]);
        let (status, json) = get(build_router(state), "/api/teams").await;
        assert_eq!(status, StatusCode::BAD_GATEWAY);
        assert!(
            !json["error"].as_str().unwrap_or("").is_empty(),
            "got: {json}"
        );
    }

    fn demo_state() -> AppState {
        let dir =
            PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../harness/fixtures/sherlock-demo");
        state_with(&[]).0.with_sherlock_dir(dir)
    }

    #[tokio::test]
    async fn info_endpoint_tells_the_ui_where_runs_and_diagnoses_live() {
        let (status, json) = get(build_router(demo_state()), "/api/info").await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(json["source"], "langgraph");
        assert_eq!(json["url"], "http://fake");
        assert!(
            json["sherlock_dir"]
                .as_str()
                .unwrap()
                .contains("sherlock-demo")
        );
    }

    #[tokio::test]
    async fn info_records_the_langgraph_server_version() {
        let (state, _) = state_with(&[("/info", serde_json::json!({"version": "0.4.1"}))]);
        let (_, json) = get(build_router(state), "/api/info").await;
        assert_eq!(json["server_version"], "0.4.1");
        let (_, json) = get(build_router(demo_state()), "/api/info").await;
        assert!(json["server_version"].is_null());
    }

    #[tokio::test]
    async fn diagnoses_endpoint_lists_the_seeded_artifacts() {
        let (status, json) = get(build_router(demo_state()), "/api/diagnoses").await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(json["diagnoses"].as_array().unwrap().len(), 3);
        assert_eq!(json["invalid"].as_array().unwrap().len(), 0);
    }

    #[tokio::test]
    async fn diagnoses_endpoint_is_empty_not_an_error_without_a_directory() {
        let (state, _) = state_with(&[]);
        let (status, json) = get(build_router(state), "/api/diagnoses").await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(json["diagnoses"], serde_json::json!([]));
        assert!(json["dir"].as_str().unwrap().contains("diagnoses"));
    }

    #[tokio::test]
    async fn diagnosis_endpoint_returns_verdict_nodes_and_artifact() {
        let router = build_router(demo_state());
        let (_, list) = get(router.clone(), "/api/diagnoses").await;
        let id = list["diagnoses"]
            .as_array()
            .unwrap()
            .iter()
            .find(|d| {
                d["minimal_sets"][0]
                    .as_array()
                    .is_some_and(|s| s.len() == 2)
            })
            .unwrap()["thread_id"]
            .as_str()
            .unwrap()
            .to_string();
        let (status, json) = get(router, &format!("/api/diagnoses/{id}")).await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(json["summary"]["status"], "found");
        let statuses: Vec<_> = json["nodes"]
            .as_array()
            .unwrap()
            .iter()
            .map(|n| n["status"].as_str().unwrap())
            .collect();
        assert_eq!(
            statuses,
            [
                "unverified",
                "culprit",
                "culprit",
                "unverified",
                "unverified"
            ]
        );
        assert_eq!(json["artifact"]["trials"].as_array().unwrap().len(), 3);
    }

    #[tokio::test]
    async fn diagnosis_endpoint_maps_errors_to_status_codes() {
        let router = build_router(demo_state());
        let (status, json) = get(router.clone(), "/api/diagnoses/no-such-thread").await;
        assert_eq!(status, StatusCode::NOT_FOUND);
        assert!(json["error"].as_str().unwrap().contains("no-such-thread"));
        let (status, _) = get(router, "/api/diagnoses/bad.id").await;
        assert_eq!(status, StatusCode::BAD_REQUEST);

        let tmp = std::env::temp_dir().join(format!("sherlock-api-{}", std::process::id()));
        std::fs::create_dir_all(tmp.join("diagnoses")).unwrap();
        std::fs::write(tmp.join("diagnoses/broken.json"), r#"{"schema": 9}"#).unwrap();
        let state = state_with(&[]).0.with_sherlock_dir(tmp.clone());
        let (status, json) = get(build_router(state), "/api/diagnoses/broken").await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
        assert!(json["error"].as_str().unwrap().contains("schema"));
        std::fs::remove_dir_all(tmp).unwrap();
    }

    #[tokio::test]
    async fn unknown_route_falls_back_to_spa_or_dist_error() {
        let (state, _) = state_with(&[]);
        let router = build_router(state);
        let req = Request::builder()
            .uri("/some/client/route")
            .body(Body::empty())
            .unwrap();
        let res = router.oneshot(req).await.unwrap();
        // Either index.html (200) when dist is built, or 503 with build hint when not.
        assert!(
            res.status() == StatusCode::OK || res.status() == StatusCode::SERVICE_UNAVAILABLE,
            "unexpected status: {}",
            res.status()
        );
        if res.status() == StatusCode::SERVICE_UNAVAILABLE {
            let body = to_bytes(res.into_body(), 4096).await.unwrap();
            let text = String::from_utf8_lossy(&body);
            assert!(text.contains("ui/dist"), "got: {text}");
        }
    }

    const VENDOR_HISTORY: &str =
        include_str!("../../../harness/fixtures/vendor_brief_two_cause_history.json");
    const VENDOR_AID: &str = "ceebe086-90b2-5890-9347-b737e3a4e9d4";

    fn vendor_graph() -> serde_json::Value {
        let chain = [
            "__start__",
            "router",
            "retriever",
            "extractor",
            "writer",
            "reviewer",
            "__end__",
        ];
        serde_json::json!({
            "nodes": chain.iter().map(|id| serde_json::json!({"id": id, "metadata": {"kind": "deterministic"}})).collect::<Vec<_>>(),
            "edges": chain.windows(2).map(|w| serde_json::json!({"source": w[0], "target": w[1]})).collect::<Vec<_>>(),
        })
    }

    #[tokio::test]
    async fn steps_endpoint_returns_each_node_run_with_input_output_and_hand_offs() {
        let history: serde_json::Value = serde_json::from_str(VENDOR_HISTORY).unwrap();
        let graph_path = format!("/assistants/{VENDOR_AID}/graph");
        let (state, _) = state_with(&[
            ("/threads/t1/history", history),
            (graph_path.as_str(), vendor_graph()),
        ]);
        let (status, json) = get(build_router(state), "/api/runs/t1/steps").await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(json["thread_id"], "t1");
        assert_eq!(json["graph_id"], "vendor_brief");
        let steps = json["steps"].as_array().unwrap();
        assert_eq!(steps.len(), 6);
        let retriever = &steps[2];
        assert_eq!(retriever["node"], "retriever");
        assert_eq!(retriever["kind"], "deterministic");
        for key in [
            "index",
            "step",
            "checkpoint_id",
            "input",
            "changed",
            "input_from",
            "output",
            "error",
            "started_at",
            "finished_at",
            "duration_ms",
            "log",
        ] {
            assert!(retriever.get(key).is_some(), "missing {key}");
        }
        assert_eq!(
            steps[3]["input"]["documents"],
            retriever["output"]["documents"]
        );
        assert!(
            retriever["log"][0]
                .as_str()
                .unwrap()
                .starts_with("retriever received")
        );
        assert_eq!(json["edges"].as_array().unwrap().len(), 5);
        assert!(json["note"].is_null());
    }

    #[tokio::test]
    async fn steps_and_graph_reject_bad_ids_and_report_a_down_server() {
        let (state, seen) = state_with(&[]);
        let router = build_router(state);
        let (status, _) = get(router.clone(), "/api/runs/..%2Fetc/steps").await;
        assert_eq!(status, StatusCode::BAD_REQUEST);
        let (status, _) = get(router.clone(), "/api/teams/bad%20id/graph").await;
        assert_eq!(status, StatusCode::BAD_REQUEST);
        assert!(seen.lock().unwrap().is_empty());
        let (status, json) = get(router, "/api/runs/t9/steps").await;
        assert_eq!(status, StatusCode::BAD_GATEWAY);
        assert!(
            json["error"]
                .as_str()
                .unwrap()
                .contains("no LangGraph route")
        );
    }

    #[tokio::test]
    async fn team_graph_is_laid_out_without_a_verdict() {
        let (state, _) = state_with(&[("/assistants/a1/graph", vendor_graph())]);
        let (status, json) = get(build_router(state), "/api/teams/a1/graph").await;
        assert_eq!(status, StatusCode::OK);
        let nodes = json["nodes"].as_array().unwrap();
        assert_eq!(nodes.len(), 7);
        assert!(
            nodes
                .iter()
                .all(|n| n["status"].is_null() && n["layer"].is_u64())
        );
        assert_eq!(json["edges"].as_array().unwrap().len(), 6);
    }

    #[tokio::test]
    async fn diagnosis_graph_carries_verdict_evidence_per_node() {
        let teams = serde_json::json!([{"assistant_id": "a1", "graph_id": "vendor_brief"}]);
        let (mut state, _) = state_with(&[
            ("/assistants/search", teams),
            ("/assistants/a1/graph", vendor_graph()),
        ]);
        state.sherlock_dir = PathBuf::from(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../harness/fixtures/sherlock-demo"
        ));
        let router = build_router(state);
        let uri = "/api/diagnoses/01a1371a-f0a7-79f2-bb6e-4b065c36df4b/graph";
        let (status, json) = get(router.clone(), uri).await;
        assert_eq!(status, StatusCode::OK);
        let retriever = json["nodes"]
            .as_array()
            .unwrap()
            .iter()
            .find(|n| n["id"] == "retriever")
            .unwrap();
        assert_eq!(retriever["status"], "culprit");
        assert_eq!(retriever["faults"][0], "retriever.drop_latest");
        assert!(
            !retriever["verdict"]["trials"]
                .as_array()
                .unwrap()
                .is_empty()
        );
        assert!(json["known_good_source"].is_string());
        let (status, _) = get(router, "/api/diagnoses/missing-run/graph").await;
        assert_eq!(status, StatusCode::NOT_FOUND);
    }
}
