//! One diagnosis started from the web app, as the page sees it: the command, each progress event
//! `sherlock-rec diagnose --progress` printed (JSON lines on stderr), any plain log line, and how it ended.
//! Pure: the `api` crate feeds lines and the exit code in.

use serde::Serialize;
use serde_json::Value;

/// `sherlock-rec diagnose` exit codes: 0 found, 75 cannot say. Anything else is an error.
const EXIT_FOUND: i32 = 0;
const EXIT_ABSTAIN: i32 = 75;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum JobState {
    Running,
    /// Finished with a verdict (found or cannot say); the artifact was written.
    Done,
    /// Did not produce a verdict: an error, a crash, or a timeout.
    Failed,
}

#[derive(Debug, Clone, Serialize)]
pub struct Job {
    pub id: u64,
    pub graph_id: String,
    pub failed: String,
    pub good: String,
    /// The exact command, for the copy-paste fallback and the record.
    pub command: String,
    pub state: JobState,
    /// Progress events in arrival order, each with `"event"`; `"at_ms"` is added on arrival.
    pub events: Vec<Value>,
    /// Non-JSON stderr lines (errors, the summary line).
    pub log: Vec<String>,
    pub exit_code: Option<i32>,
    /// Why it failed, in plain words.
    pub error: Option<String>,
    pub started_ms: u64,
    pub finished_ms: Option<u64>,
}

const MAX_LOG: usize = 200;
const MAX_EVENTS: usize = 2000;

impl Job {
    pub fn new(id: u64, pick: &crate::runner::Pick, command: String, started_ms: u64) -> Self {
        Self {
            id,
            graph_id: pick.graph_id.clone(),
            failed: pick.failed.clone(),
            good: pick.good.clone(),
            command,
            state: JobState::Running,
            events: Vec::new(),
            log: Vec::new(),
            exit_code: None,
            error: None,
            started_ms,
            finished_ms: None,
        }
    }

    /// One stderr line: a progress event if it is a JSON object with `event`, otherwise a log line.
    pub fn on_line(&mut self, line: &str, now_ms: u64) {
        let line = line.trim_end();
        if line.is_empty() {
            return;
        }
        match serde_json::from_str::<Value>(line) {
            Ok(Value::Object(mut obj)) if obj.get("event").is_some_and(Value::is_string) => {
                if self.events.len() < MAX_EVENTS {
                    obj.insert(
                        "at_ms".into(),
                        Value::from(now_ms.saturating_sub(self.started_ms)),
                    );
                    self.events.push(Value::Object(obj));
                }
            }
            _ => {
                if self.log.len() < MAX_LOG {
                    self.log.push(line.to_string());
                }
            }
        }
    }

    /// The process ended. `None` = killed or no exit code.
    pub fn finish(&mut self, exit_code: Option<i32>, now_ms: u64) {
        self.exit_code = exit_code;
        self.finished_ms = Some(now_ms);
        let said_done = self
            .events
            .iter()
            .any(|e| e["event"].as_str() == Some("done"));
        match exit_code {
            Some(EXIT_FOUND | EXIT_ABSTAIN) if said_done => self.state = JobState::Done,
            _ => {
                self.state = JobState::Failed;
                self.error = Some(match self.log.iter().rev().find(|l| !l.trim().is_empty()) {
                    Some(last) => last.trim_start_matches("sherlock-rec: ").to_string(),
                    None => match exit_code {
                        Some(c) => format!("sherlock-rec diagnose exited with code {c}"),
                        None => "sherlock-rec diagnose was stopped before it finished".into(),
                    },
                });
            }
        }
    }

    /// Could not start the process at all.
    pub fn failed_to_start(&mut self, why: String, now_ms: u64) {
        self.state = JobState::Failed;
        self.error = Some(why);
        self.finished_ms = Some(now_ms);
    }
}
