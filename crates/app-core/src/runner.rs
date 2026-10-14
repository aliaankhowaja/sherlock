//! What the web app may start, decided here and nowhere else. Pure apart from file-existence checks:
//! no process is spawned in `app-core`.
//!
//! A diagnosis started from the browser runs one fixed argv of `sherlock-rec diagnose` (no shell, no
//! free-form arguments). The run ids must be runs of the chosen team that the LangGraph server lists,
//! and never Sherlock's own trial forks. The project directory says where the recording and the
//! team's check live:
//!
//! - `<project>/.sherlock/cassette.db` — the recording the replay server serves
//! - `<project>/checks/<graph_id>.yaml`, else `<project>/sherlock.yaml` — the check Z
//! - `<project>/checks/<graph_id>.node-map.json` — optional node map

use crate::ingestion::{Team, TeamRun};
use std::path::PathBuf;

/// Where a diagnosis started from the browser reads and writes. Fixed at `serve` startup.
#[derive(Debug, Clone)]
pub struct Project {
    pub dir: PathBuf,
    /// The `sherlock-rec` program (a path, or a name found on `PATH`).
    pub program: String,
    pub langgraph_url: String,
    pub sherlock_dir: PathBuf,
}

/// A validated choice of failed run and known-good run of one team.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Pick {
    pub graph_id: String,
    pub failed: String,
    pub good: String,
}

fn id_ok(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= 64
        && id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.'))
        && !id.starts_with('.')
        && !id.starts_with('-')
}

fn is_trial(run: &TeamRun) -> bool {
    run.metadata.get("sherlock_fork_of").is_some()
}

/// Accept only ids the server listed for this team. `runs` are that team's runs.
pub fn validate_pick(
    teams: &[Team],
    runs: &[TeamRun],
    assistant_id: &str,
    failed: &str,
    good: &str,
) -> Result<Pick, String> {
    for (what, id) in [
        ("team", assistant_id),
        ("failed run", failed),
        ("known-good run", good),
    ] {
        if !id_ok(id) {
            return Err(format!("the {what} id is not a valid id"));
        }
    }
    let team = teams
        .iter()
        .find(|t| t.assistant_id == assistant_id)
        .ok_or("the server lists no such team")?;
    if !id_ok(&team.graph_id) {
        return Err("the team's graph id cannot name a check file".into());
    }
    if failed == good {
        return Err("the failed run and the known-good run must be different runs".into());
    }
    for (what, id) in [("failed run", failed), ("known-good run", good)] {
        let run = runs
            .iter()
            .find(|r| r.thread_id == id)
            .ok_or_else(|| format!("the {what} is not a run of this team on the server"))?;
        if is_trial(run) {
            return Err(format!("the {what} is one of Sherlock's own trial runs"));
        }
    }
    Ok(Pick {
        graph_id: team.graph_id.clone(),
        failed: failed.to_string(),
        good: good.to_string(),
    })
}

fn path_str(p: &std::path::Path) -> String {
    p.display().to_string()
}

impl Project {
    pub fn cassette(&self) -> PathBuf {
        self.dir.join(".sherlock").join("cassette.db")
    }

    pub fn check_file(&self, graph_id: &str) -> Option<PathBuf> {
        let per_team = self.dir.join("checks").join(format!("{graph_id}.yaml"));
        let shared = self.dir.join("sherlock.yaml");
        [per_team, shared].into_iter().find(|p| p.is_file())
    }

    pub fn node_map_file(&self, graph_id: &str) -> Option<PathBuf> {
        let p = self
            .dir
            .join("checks")
            .join(format!("{graph_id}.node-map.json"));
        p.is_file().then_some(p)
    }

    /// What is missing before this team can be diagnosed from the browser, in plain words.
    pub fn problems(&self, graph_id: &str) -> Vec<String> {
        let mut out = Vec::new();
        if !self.cassette().is_file() {
            out.push(format!(
                "no recording at {} (record the team with `sherlock-rec run`, then serve it with `sherlock-rec run --replay`)",
                path_str(&self.cassette())
            ));
        }
        if self.check_file(graph_id).is_none() {
            out.push(format!(
                "no check for {graph_id}: add {} or {}",
                path_str(&self.dir.join("checks").join(format!("{graph_id}.yaml"))),
                path_str(&self.dir.join("sherlock.yaml"))
            ));
        }
        out
    }

    /// The one command the server may run for this pick. Program first; no shell involved.
    pub fn diagnose_argv(&self, pick: &Pick) -> Result<Vec<String>, String> {
        let check = self
            .check_file(&pick.graph_id)
            .ok_or_else(|| format!("no check for {}", pick.graph_id))?;
        let mut argv: Vec<String> = [
            self.program.as_str(),
            "diagnose",
            "--progress",
            "--thread-id",
            &pick.failed,
            "--good-run",
            &pick.good,
            "--url",
            &self.langgraph_url,
            "--cassette",
            &path_str(&self.cassette()),
            "-c",
            &path_str(&check),
            "--out",
            &path_str(&self.sherlock_dir),
        ]
        .iter()
        .map(|s| s.to_string())
        .collect();
        if let Some(map) = self.node_map_file(&pick.graph_id) {
            argv.extend(["--node-map".to_string(), path_str(&map)]);
        }
        Ok(argv)
    }

    /// `sherlock-rec outcomes` for one team: which runs pass or fail the check.
    pub fn outcomes_argv(&self, graph_id: &str) -> Result<Vec<String>, String> {
        if !id_ok(graph_id) {
            return Err("the team's graph id cannot name a check file".into());
        }
        let check = self
            .check_file(graph_id)
            .ok_or_else(|| format!("no check for {graph_id}"))?;
        Ok([
            self.program.as_str(),
            "outcomes",
            "--graph-id",
            graph_id,
            "-c",
            &path_str(&check),
            "--url",
            &self.langgraph_url,
        ]
        .iter()
        .map(|s| s.to_string())
        .collect())
    }
}

/// The argv as one line a person can paste into a terminal (quoted where needed).
pub fn display_command(argv: &[String]) -> String {
    argv.iter()
        .map(|a| {
            if !a.is_empty()
                && a.chars().all(|c| {
                    c.is_ascii_alphanumeric()
                        || matches!(c, '-' | '_' | '.' | '/' | ':' | '=' | ',')
                })
            {
                a.clone()
            } else {
                format!("\"{}\"", a.replace('"', "\\\""))
            }
        })
        .collect::<Vec<_>>()
        .join(" ")
}
