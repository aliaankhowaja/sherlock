use anyhow::Result;
use axum::{
    Json,
    http::{StatusCode, header},
    response::{Html, IntoResponse},
    routing::get,
};
use rust_embed::RustEmbed;
use std::path::PathBuf;

#[derive(RustEmbed, Clone)]
#[folder = "../../ui/dist/"]
struct Assets;

pub struct ServeOptions {
    pub host: String,
    pub port: u16,
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

pub fn build_router() -> axum::Router {
    axum::Router::new()
        .route("/api/health", get(health))
        .fallback(serve_ui)
}

fn ui_available() -> bool {
    has_ui_assets() || filesystem_dist_dir().is_some()
}

pub async fn serve(opts: ServeOptions) -> Result<()> {
    if !ui_available() {
        return Err(missing_dist_error());
    }
    let listener = tokio::net::TcpListener::bind(opts.addr()).await?;
    println!("Serving sherlock at {}", opts.base_url());
    axum::serve(listener, build_router())
        .with_graceful_shutdown(async {
            let _ = tokio::signal::ctrl_c().await;
        })
        .await?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::body::{Body, to_bytes};
    use axum::http::{Request, StatusCode};
    use tower::ServiceExt;

    #[tokio::test]
    async fn health_endpoint_returns_ok_status() {
        let router = build_router();
        let req = Request::builder()
            .uri("/api/health")
            .body(Body::empty())
            .unwrap();
        let res = router.oneshot(req).await.unwrap();
        assert_eq!(res.status(), StatusCode::OK);
        let body = to_bytes(res.into_body(), 1024).await.unwrap();
        let json: serde_json::Value = serde_json::from_slice(&body).unwrap();
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
        };
        assert_eq!(opts.addr(), "127.0.0.1:3000");
        assert_eq!(opts.base_url(), "http://127.0.0.1:3000");
    }

    #[tokio::test]
    async fn unknown_route_falls_back_to_spa_or_dist_error() {
        let router = build_router();
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
}
