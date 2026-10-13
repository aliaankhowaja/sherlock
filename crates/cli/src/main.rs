use clap::{Args, Parser, Subcommand, ValueEnum};

#[derive(Parser, Debug)]
#[command(name = "sherlock", about = "Multi-agent team debugger")]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand, Debug)]
enum Commands {
    /// Start the API server and serve the embedded React UI
    Serve(ServeArgs),
    /// Ingest data from a LangGraph API server
    Ingest(IngestArgs),
    /// Read diagnoses written by `sherlock-rec diagnose`
    Diagnoses(DiagnosesArgs),
}

#[derive(Args, Debug)]
struct DiagnosesArgs {
    /// Sherlock state directory; diagnoses are read from `<dir>/diagnoses/`
    #[arg(long, global = true, default_value = ".sherlock")]
    sherlock_dir: std::path::PathBuf,

    /// Print JSON instead of text
    #[arg(long, global = true, default_value_t = false)]
    json: bool,

    #[command(subcommand)]
    command: DiagnosesCommands,
}

#[derive(Subcommand, Debug)]
enum DiagnosesCommands {
    /// List diagnoses, newest first
    List,
    /// Show one diagnosis: verdict, per-node status, trial log
    Show {
        /// Thread id of the diagnosed run
        thread_id: String,
    },
}

#[derive(Args, Debug)]
struct ServeArgs {
    /// Interface to bind
    #[arg(long, default_value = "127.0.0.1")]
    host: String,

    /// Port to bind
    #[arg(long, default_value_t = 3000)]
    port: u16,

    /// Do not open a browser window on startup
    #[arg(long, alias = "no-browser", default_value_t = false)]
    no_open: bool,

    /// Base URL of the LangGraph API server proxied by the dashboard
    #[arg(long, default_value = "http://127.0.0.1:2024")]
    langgraph_url: String,

    /// API key for secured LangGraph servers, sent as X-Api-Key
    #[arg(long)]
    langgraph_api_key: Option<String>,

    /// Where teams, runs, and logs come from. `auto` uses LangSmith when a key is set.
    #[arg(long, value_enum, default_value = "auto")]
    source: IngestSource,

    /// LangSmith API key. Falls back to LANGSMITH_API_KEY, then a `.env` file.
    #[arg(long)]
    langsmith_api_key: Option<String>,

    /// LangSmith API origin
    #[arg(long, default_value = "https://api.smith.langchain.com")]
    langsmith_url: String,

    /// Sherlock state directory; diagnoses are read from `<dir>/diagnoses/`
    #[arg(long, default_value = ".sherlock")]
    sherlock_dir: std::path::PathBuf,
}

#[derive(Clone, Debug, ValueEnum)]
enum IngestSource {
    /// LangSmith when a key is available, otherwise the local LangGraph server
    Auto,
    /// LangGraph Agent Server (`--langgraph-url` / `--base-url`)
    Langgraph,
    /// LangSmith traces (`--langsmith-api-key`)
    Langsmith,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let cli = Cli::parse();
    match cli.command {
        Commands::Serve(args) => {
            let url = format!("http://{}:{}", args.host, args.port);
            if !args.no_open
                && let Err(e) = webbrowser::open(&url)
            {
                eprintln!("warning: could not open browser ({e})");
            }
            let langsmith_key = resolve_langsmith_key(args.langsmith_api_key);
            let use_langsmith = match args.source {
                IngestSource::Langsmith => true,
                IngestSource::Langgraph => false,
                IngestSource::Auto => langsmith_key.is_some(),
            };
            let langsmith_api_key = if use_langsmith {
                Some(langsmith_key.ok_or_else(|| {
                    anyhow::anyhow!(
                        "LangSmith source selected but no API key. Set LANGSMITH_API_KEY or pass --langsmith-api-key"
                    )
                })?)
            } else {
                None
            };
            api::serve(api::ServeOptions {
                host: args.host,
                port: args.port,
                langgraph_url: args.langgraph_url,
                langgraph_api_key: args.langgraph_api_key,
                langsmith_api_key,
                langsmith_url: args.langsmith_url,
                sherlock_dir: args.sherlock_dir,
            })
            .await?;
        }
        Commands::Diagnoses(args) => {
            let store = app_core::diagnosis::DiagnosisStore::new(&args.sherlock_dir);
            match args.command {
                DiagnosesCommands::List => {
                    let list = store.list();
                    if args.json {
                        println!("{}", render_json(&list)?);
                    } else {
                        print!("{}", render_diagnosis_list(&list));
                    }
                }
                DiagnosesCommands::Show { thread_id } => {
                    let diagnosis = store.get(&thread_id)?;
                    if args.json {
                        println!("{}", render_json(&diagnosis)?);
                    } else {
                        print!("{}", render_diagnosis(&diagnosis));
                    }
                }
            }
        }
        Commands::Ingest(args) => {
            let langsmith_key = resolve_langsmith_key(args.langsmith_api_key);
            let use_langsmith = match args.source {
                IngestSource::Langsmith => true,
                IngestSource::Langgraph => false,
                IngestSource::Auto => langsmith_key.is_some(),
            };
            if use_langsmith {
                let key = langsmith_key.ok_or_else(|| {
                    anyhow::anyhow!(
                        "LangSmith source selected but no API key. Set LANGSMITH_API_KEY or pass --langsmith-api-key"
                    )
                })?;
                let transport = LangSmithHttp::new(args.langsmith_url, key);
                match args.command {
                    IngestCommands::Teams => {
                        let teams = app_core::langsmith::list_teams(&transport)?;
                        println!("{}", render_json(&teams)?);
                    }
                    IngestCommands::Runs(r) => {
                        let runs = app_core::langsmith::fetch_team_runs(
                            &transport,
                            &app_core::ingestion::TeamRunsQuery {
                                limit: r.limit,
                                offset: r.offset,
                                assistant_id: r.assistant_id,
                            },
                        )?;
                        println!("{}", render_json(&runs)?);
                    }
                    IngestCommands::Logs(l) => {
                        let logs = app_core::langsmith::fetch_run_logs(
                            &transport,
                            &l.thread_id,
                            &app_core::ingestion::RunLogsQuery {
                                limit: l.limit,
                                run_id: l.run_id,
                            },
                        )?;
                        println!("{}", render_json(&logs)?);
                    }
                }
            } else {
                let transport = HttpTransport::new(args.base_url, args.api_key);
                match args.command {
                    IngestCommands::Teams => {
                        let teams = app_core::ingestion::list_teams(&transport)?;
                        println!("{}", render_json(&teams)?);
                    }
                    IngestCommands::Runs(r) => {
                        let runs = app_core::ingestion::fetch_team_runs(
                            &transport,
                            &app_core::ingestion::TeamRunsQuery {
                                limit: r.limit,
                                offset: r.offset,
                                assistant_id: r.assistant_id,
                            },
                        )?;
                        println!("{}", render_json(&runs)?);
                    }
                    IngestCommands::Logs(l) => {
                        let logs = app_core::ingestion::fetch_run_logs(
                            &transport,
                            &l.thread_id,
                            &app_core::ingestion::RunLogsQuery {
                                limit: l.limit,
                                run_id: l.run_id,
                            },
                        )?;
                        println!("{}", render_json(&logs)?);
                    }
                }
            }
        }
    }
    Ok(())
}

fn resolve_langsmith_key(flag: Option<String>) -> Option<String> {
    flag.filter(|value| !value.is_empty())
        .or_else(|| {
            std::env::var("LANGSMITH_API_KEY")
                .ok()
                .filter(|value| !value.is_empty())
        })
        .or_else(|| dotenv_value("LANGSMITH_API_KEY"))
}

fn dotenv_value(key: &str) -> Option<String> {
    let text = std::fs::read_to_string(".env").ok()?;
    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let (name, value) = line.split_once('=')?;
        if name.trim() == key {
            let value = value.trim().trim_matches('"').trim_matches('\'');
            if !value.is_empty() {
                return Some(value.to_string());
            }
        }
    }
    None
}

/// Shared connection options for all `ingest` subcommands.
#[derive(Args, Debug)]
struct IngestArgs {
    /// Base URL of the LangGraph API server
    #[arg(long, default_value = "http://127.0.0.1:2024")]
    base_url: String,

    /// API key for secured servers, sent as X-Api-Key
    #[arg(long)]
    api_key: Option<String>,

    /// Where teams, runs, and logs come from. `auto` uses LangSmith when a key is set.
    #[arg(long, value_enum, default_value = "auto")]
    source: IngestSource,

    /// LangSmith API key. Falls back to LANGSMITH_API_KEY, then a `.env` file.
    #[arg(long)]
    langsmith_api_key: Option<String>,

    /// LangSmith API origin
    #[arg(long, default_value = "https://api.smith.langchain.com")]
    langsmith_url: String,

    #[command(subcommand)]
    command: IngestCommands,
}

#[derive(Subcommand, Debug)]
enum IngestCommands {
    /// List all agentic teams (assistants)
    Teams,
    /// Fetch team runs (threads), optionally filtered by team
    Runs(RunsArgs),
    /// Fetch run logs (checkpoint history) for one team run
    Logs(LogsArgs),
}

#[derive(Args, Debug)]
struct RunsArgs {
    /// Only runs tagged with this team (assistant) id
    #[arg(long)]
    assistant_id: Option<String>,

    /// Maximum number of runs to return
    #[arg(long, default_value_t = 20)]
    limit: u32,

    /// Number of runs to skip
    #[arg(long, default_value_t = 0)]
    offset: u32,
}

#[derive(Args, Debug)]
struct LogsArgs {
    /// Thread id of the team run
    #[arg(long)]
    thread_id: String,

    /// Maximum number of checkpoints to read
    #[arg(long, default_value_t = 50)]
    limit: u32,

    /// Only events from this run id
    #[arg(long)]
    run_id: Option<String>,
}

/// Blocking HTTP transport over the LangGraph API (sync by design: the
/// `LangGraphTransport` trait is runtime-agnostic, and the CLI makes a
/// handful of sequential requests).
struct HttpTransport {
    base_url: String,
    api_key: Option<String>,
}

impl HttpTransport {
    fn new(base_url: String, api_key: Option<String>) -> Self {
        Self { base_url, api_key }
    }
}

struct LangSmithHttp {
    base_url: String,
    api_key: String,
}

impl LangSmithHttp {
    fn new(base_url: String, api_key: String) -> Self {
        Self {
            base_url: base_url.trim_end_matches('/').to_string(),
            api_key,
        }
    }

    fn read_json(
        url: &str,
        result: Result<ureq::http::Response<ureq::Body>, ureq::Error>,
    ) -> anyhow::Result<serde_json::Value> {
        let mut response = result.map_err(|e| anyhow::anyhow!("{url} failed: {e}"))?;
        response
            .body_mut()
            .read_json()
            .map_err(|e| anyhow::anyhow!("invalid JSON from {url}: {e}"))
    }
}

impl app_core::langsmith::LangSmithTransport for LangSmithHttp {
    fn get_json(&self, path: &str) -> anyhow::Result<serde_json::Value> {
        let url = format!("{}{}", self.base_url, path);
        Self::read_json(
            &url,
            ureq::get(&url).header("x-api-key", &self.api_key).call(),
        )
    }

    fn post_json(&self, path: &str, body: serde_json::Value) -> anyhow::Result<serde_json::Value> {
        let url = format!("{}{}", self.base_url, path);
        Self::read_json(
            &url,
            ureq::post(&url)
                .header("x-api-key", &self.api_key)
                .send_json(body),
        )
    }
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
}

/// Render a value as pretty JSON for stdout. Pure for testability.
fn render_json(value: &impl serde::Serialize) -> anyhow::Result<String> {
    Ok(serde_json::to_string_pretty(value)?)
}

fn set_text(sets: &[Vec<String>]) -> String {
    sets.iter()
        .map(|s| format!("{{{}}}", s.join(", ")))
        .collect::<Vec<_>>()
        .join(" and ")
}

/// One line per diagnosis: the verdict in words, not a bare status.
fn render_diagnosis_list(list: &app_core::diagnosis::DiagnosisList) -> String {
    let mut out = String::new();
    if list.diagnoses.is_empty() {
        out.push_str(&format!(
            "No diagnoses in {}.\nCreate one with `sherlock-rec diagnose --thread-id <failed run> --good-run <passing run>`.\n",
            list.dir
        ));
    }
    for d in &list.diagnoses {
        let verdict = if d.status == "found" {
            format!("culprit set {}", set_text(&d.minimal_sets))
        } else {
            format!(
                "cannot say ({})",
                d.reason_code.as_deref().unwrap_or("abstain")
            )
        };
        out.push_str(&format!(
            "{}  {}  {}\n",
            d.thread_id,
            d.graph_id.as_deref().unwrap_or("-"),
            verdict
        ));
    }
    for bad in &list.invalid {
        out.push_str(&format!("INVALID {}: {}\n", bad.file, bad.error));
    }
    out
}

fn render_diagnosis(d: &app_core::diagnosis::Diagnosis) -> String {
    use app_core::diagnosis::NodeStatus;
    let s = &d.summary;
    let mut out = format!("Run {}\n", s.thread_id);
    if s.status == "found" {
        out.push_str(&format!(
            "Verdict: restoring {} to known-good makes the run pass{}.\n",
            set_text(&s.minimal_sets),
            if s.complete {
                ""
            } else {
                " (search incomplete)"
            }
        ));
    } else {
        out.push_str(&format!("Verdict: cannot say. {}\n", s.reason));
    }
    if let (Some(used), Some(fewer)) = (s.trials_used, s.fewer_pct) {
        out.push_str(&format!(
            "Trials: {used} ({fewer}% fewer than trying every subset)\n"
        ));
    }
    out.push_str("\nNodes (verified status only):\n");
    for n in &d.nodes {
        let label = match n.status {
            NodeStatus::Culprit => "CULPRIT   ",
            NodeStatus::Cleared => "cleared   ",
            NodeStatus::Unverified => "unverified",
            NodeStatus::Abstained => "cannot say",
        };
        out.push_str(&format!("  {label}  {}  {}\n", n.node, n.reason));
    }
    if let Some(trials) = d.artifact["trials"].as_array() {
        out.push_str("\nTrial log:\n");
        for t in trials {
            out.push_str(&format!(
                "  #{} restore {{{}}} -> {}: {}\n",
                t["n"],
                t["restored"]
                    .as_array()
                    .map(|a| a
                        .iter()
                        .filter_map(|v| v.as_str())
                        .collect::<Vec<_>>()
                        .join(", "))
                    .unwrap_or_default(),
                t["label"].as_str().unwrap_or("?"),
                t["reason"].as_str().unwrap_or("")
            ));
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    const DEMO: &str = "../../harness/fixtures/sherlock-demo";

    #[test]
    fn diagnoses_commands_parse() {
        let cli = parse(&["sherlock", "diagnoses", "list", "--json"]);
        let Commands::Diagnoses(args) = cli.command else {
            panic!("expected diagnoses");
        };
        assert!(args.json && matches!(args.command, DiagnosesCommands::List));
        assert_eq!(args.sherlock_dir, std::path::PathBuf::from(".sherlock"));
        let cli = parse(&["sherlock", "diagnoses", "show", "t1", "--sherlock-dir", "x"]);
        let Commands::Diagnoses(args) = cli.command else {
            panic!("expected diagnoses");
        };
        assert!(
            matches!(args.command, DiagnosesCommands::Show { ref thread_id } if thread_id == "t1")
        );
        assert_eq!(args.sherlock_dir, std::path::PathBuf::from("x"));
        assert!(Cli::try_parse_from(["sherlock", "diagnoses", "show"]).is_err());
    }

    #[test]
    fn serve_takes_a_sherlock_dir() {
        let cli = parse(&["sherlock", "serve", "--sherlock-dir", "demo"]);
        let Commands::Serve(args) = cli.command else {
            panic!("expected serve");
        };
        assert_eq!(args.sherlock_dir, std::path::PathBuf::from("demo"));
    }

    #[test]
    fn list_text_says_the_verdict_and_the_empty_state_says_what_to_run() {
        let list = app_core::diagnosis::DiagnosisStore::new(DEMO).list();
        let text = render_diagnosis_list(&list);
        assert!(
            text.contains("culprit set {retriever, extractor}"),
            "{text}"
        );
        assert!(text.contains("culprit set {writer}"), "{text}");
        assert!(text.contains("cannot say (no_known_good)"), "{text}");
        let empty = app_core::diagnosis::DiagnosisStore::new("nowhere").list();
        let text = render_diagnosis_list(&empty);
        assert!(text.contains("No diagnoses") && text.contains("sherlock-rec diagnose"));
    }

    #[test]
    fn show_text_has_verdict_verified_nodes_and_trial_log() {
        let list = app_core::diagnosis::DiagnosisStore::new(DEMO).list();
        let id = &list
            .diagnoses
            .iter()
            .find(|d| d.minimal_sets.iter().any(|s| s.len() == 2))
            .unwrap()
            .thread_id;
        let d = app_core::diagnosis::DiagnosisStore::new(DEMO)
            .get(id)
            .unwrap();
        let text = render_diagnosis(&d);
        assert!(text.contains("restoring {retriever, extractor} to known-good makes the run pass"));
        assert!(text.contains("CULPRIT") && text.contains("unverified"));
        assert!(text.contains("Trial log:") && text.contains("#3"));
        assert!(
            !text.contains("cleared"),
            "pruned nodes must not be cleared: {text}"
        );
        let abstain = list
            .diagnoses
            .iter()
            .find(|d| d.status == "abstain")
            .unwrap();
        let d = app_core::diagnosis::DiagnosisStore::new(DEMO)
            .get(&abstain.thread_id)
            .unwrap();
        let text = render_diagnosis(&d);
        assert!(text.contains("Verdict: cannot say.") && !text.contains("CULPRIT"));
    }

    fn parse(args: &[&str]) -> Cli {
        Cli::try_parse_from(args).expect("cli should parse")
    }

    #[test]
    fn serve_defaults_to_localhost_3000_with_browser() {
        let cli = parse(&["sherlock", "serve"]);
        let Commands::Serve(args) = cli.command else {
            panic!("expected serve subcommand");
        };
        assert_eq!(args.host, "127.0.0.1");
        assert_eq!(args.port, 3000);
        assert!(!args.no_open);
    }

    #[test]
    fn serve_accepts_custom_port_host_and_no_open() {
        let cli = parse(&[
            "sherlock",
            "serve",
            "--host",
            "0.0.0.0",
            "--port",
            "4001",
            "--no-open",
        ]);
        let Commands::Serve(args) = cli.command else {
            panic!("expected serve subcommand");
        };
        assert_eq!(args.host, "0.0.0.0");
        assert_eq!(args.port, 4001);
        assert!(args.no_open);
    }

    #[test]
    fn serve_rejects_invalid_port() {
        assert!(Cli::try_parse_from(["sherlock", "serve", "--port", "abc"]).is_err());
    }

    #[test]
    fn serve_defaults_langgraph_to_local_dev_server() {
        let cli = parse(&["sherlock", "serve"]);
        let Commands::Serve(args) = cli.command else {
            panic!("expected serve subcommand");
        };
        assert_eq!(args.langgraph_url, "http://127.0.0.1:2024");
        assert_eq!(args.langgraph_api_key, None);
    }

    #[test]
    fn serve_accepts_langgraph_options() {
        let cli = parse(&[
            "sherlock",
            "serve",
            "--langgraph-url",
            "http://prod:2024",
            "--langgraph-api-key",
            "secret",
        ]);
        let Commands::Serve(args) = cli.command else {
            panic!("expected serve subcommand");
        };
        assert_eq!(args.langgraph_url, "http://prod:2024");
        assert_eq!(args.langgraph_api_key.as_deref(), Some("secret"));
    }

    fn ingest(args: &[&str]) -> IngestArgs {
        let cli = parse(args);
        let Commands::Ingest(ingest) = cli.command else {
            panic!("expected ingest subcommand, got {:?}", cli.command);
        };
        ingest
    }

    #[test]
    fn ingest_teams_defaults_to_local_dev_server() {
        let args = ingest(&["sherlock", "ingest", "teams"]);
        assert_eq!(args.base_url, "http://127.0.0.1:2024");
        assert_eq!(args.api_key, None);
        assert!(matches!(args.command, IngestCommands::Teams));
    }

    #[test]
    fn ingest_accepts_custom_base_url_and_api_key() {
        let args = ingest(&[
            "sherlock",
            "ingest",
            "--base-url",
            "http://prod:2024",
            "--api-key",
            "secret",
            "teams",
        ]);
        assert_eq!(args.base_url, "http://prod:2024");
        assert_eq!(args.api_key.as_deref(), Some("secret"));
    }

    #[test]
    fn ingest_runs_defaults_limit_offset_and_no_team_filter() {
        let args = ingest(&["sherlock", "ingest", "runs"]);
        let IngestCommands::Runs(runs) = args.command else {
            panic!("expected runs subcommand");
        };
        assert_eq!(runs.assistant_id, None);
        assert_eq!(runs.limit, 20);
        assert_eq!(runs.offset, 0);
    }

    #[test]
    fn ingest_runs_accepts_team_filter_and_paging() {
        let args = ingest(&[
            "sherlock",
            "ingest",
            "runs",
            "--assistant-id",
            "a1",
            "--limit",
            "5",
            "--offset",
            "10",
        ]);
        let IngestCommands::Runs(runs) = args.command else {
            panic!("expected runs subcommand");
        };
        assert_eq!(runs.assistant_id.as_deref(), Some("a1"));
        assert_eq!(runs.limit, 5);
        assert_eq!(runs.offset, 10);
    }

    #[test]
    fn ingest_logs_requires_thread_id() {
        assert!(Cli::try_parse_from(["sherlock", "ingest", "logs"]).is_err());
    }

    #[test]
    fn ingest_logs_defaults_limit_and_optional_run_id() {
        let args = ingest(&["sherlock", "ingest", "logs", "--thread-id", "t1"]);
        let IngestCommands::Logs(logs) = args.command else {
            panic!("expected logs subcommand");
        };
        assert_eq!(logs.thread_id, "t1");
        assert_eq!(logs.limit, 50);
        assert_eq!(logs.run_id, None);
    }

    #[test]
    fn ingest_logs_accepts_custom_limit_and_run_id() {
        let args = ingest(&[
            "sherlock",
            "ingest",
            "logs",
            "--thread-id",
            "t1",
            "--limit",
            "5",
            "--run-id",
            "r1",
        ]);
        let IngestCommands::Logs(logs) = args.command else {
            panic!("expected logs subcommand");
        };
        assert_eq!(logs.limit, 5);
        assert_eq!(logs.run_id.as_deref(), Some("r1"));
    }

    #[test]
    fn render_json_round_trips_teams() {
        let teams = vec![app_core::ingestion::Team {
            assistant_id: "a1".to_string(),
            graph_id: "triage".to_string(),
            name: Some("triage-team".to_string()),
        }];
        let out = render_json(&teams).expect("render");
        let back: serde_json::Value = serde_json::from_str(&out).expect("valid JSON");
        assert_eq!(back[0]["assistant_id"], "a1");
        assert_eq!(back[0]["graph_id"], "triage");
        assert_eq!(back[0]["name"], "triage-team");
    }

    #[test]
    fn render_json_round_trips_run_logs() {
        let logs = app_core::ingestion::RunLogs {
            thread_id: "t1".to_string(),
            events: vec![app_core::ingestion::RunEvent {
                checkpoint_id: Some("c1".to_string()),
                step: Some(1),
                node: "nurse".to_string(),
                writes: serde_json::json!({}),
                error: Some("boom".to_string()),
                run_id: Some("r1".to_string()),
                created_at: None,
            }],
        };
        let out = render_json(&logs).expect("render");
        let back: serde_json::Value = serde_json::from_str(&out).expect("valid JSON");
        assert_eq!(back["thread_id"], "t1");
        assert_eq!(back["events"][0]["node"], "nurse");
        assert_eq!(back["events"][0]["error"], "boom");
    }

    /// Single-shot mock LangGraph server over std TCP. Records the raw
    /// request and replies with a canned JSON body.
    fn mock_server(
        status: &'static str,
        body: &'static str,
    ) -> (
        std::net::SocketAddr,
        std::sync::Arc<std::sync::Mutex<String>>,
    ) {
        use std::io::{Read, Write};
        let listener = std::net::TcpListener::bind("127.0.0.1:0").expect("bind mock server");
        let addr = listener.local_addr().expect("local addr");
        let seen = std::sync::Arc::new(std::sync::Mutex::new(String::new()));
        let seen_clone = seen.clone();
        std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept");
            let mut buf = vec![0u8; 8192];
            let mut request = Vec::new();
            // Read headers, then the exact body per Content-Length.
            loop {
                let n = stream.read(&mut buf).expect("read");
                if n == 0 {
                    break;
                }
                request.extend_from_slice(&buf[..n]);
                if let Some(end) = find_headers_end(&request) {
                    let headers = String::from_utf8_lossy(&request[..end]).into_owned();
                    let content_len = headers
                        .lines()
                        .find_map(|line| {
                            line.strip_prefix("Content-Length:")
                                .or_else(|| line.strip_prefix("content-length:"))
                                .and_then(|v| v.trim().parse::<usize>().ok())
                        })
                        .unwrap_or(0);
                    if request.len() >= end + content_len {
                        break;
                    }
                }
            }
            *seen_clone.lock().expect("lock") = String::from_utf8_lossy(&request).into_owned();
            let reply = format!(
                "HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                body.len()
            );
            stream.write_all(reply.as_bytes()).expect("write");
        });
        (addr, seen)
    }

    fn find_headers_end(request: &[u8]) -> Option<usize> {
        request
            .windows(4)
            .position(|w| w == b"\r\n\r\n")
            .map(|pos| pos + 4)
    }

    fn request_body(seen: &std::sync::Arc<std::sync::Mutex<String>>) -> serde_json::Value {
        let raw = seen.lock().expect("lock").clone();
        let body = raw.split("\r\n\r\n").nth(1).unwrap_or("").to_string();
        serde_json::from_str(&body).expect("request body is JSON")
    }

    #[test]
    fn transport_posts_json_to_path_and_returns_parsed_reply() {
        use app_core::ingestion::LangGraphTransport;
        let (addr, seen) = mock_server("200 OK", r#"{"ok":true}"#);
        let transport = HttpTransport::new(format!("http://{addr}"), None);
        let reply = transport
            .post_json("/assistants/search", serde_json::json!({}))
            .expect("post");
        assert_eq!(reply, serde_json::json!({"ok": true}));
        let raw = seen.lock().expect("lock").clone();
        assert!(raw.contains("POST /assistants/search"), "got: {raw}");
        assert!(raw.contains("application/json"), "got: {raw}");
        assert_eq!(request_body(&seen), serde_json::json!({}));
    }

    #[test]
    fn transport_sends_api_key_header_when_set() {
        use app_core::ingestion::LangGraphTransport;
        let (addr, seen) = mock_server("200 OK", "[]");
        let transport = HttpTransport::new(format!("http://{addr}"), Some("secret".to_string()));
        transport
            .post_json("/threads/search", serde_json::json!({"limit": 1}))
            .expect("post");
        let raw = seen.lock().expect("lock").clone();
        assert!(raw.contains("secret"), "api key missing, got: {raw}");
    }

    #[test]
    fn transport_errors_on_server_error() {
        use app_core::ingestion::LangGraphTransport;
        let (addr, _) = mock_server("500 Internal Server Error", r#"{"detail":"bad"}"#);
        let transport = HttpTransport::new(format!("http://{addr}"), None);
        let err = transport
            .post_json("/threads/search", serde_json::json!({}))
            .expect_err("should fail on 500");
        assert!(format!("{err:?}").contains("500"), "got: {err:?}");
    }
}
