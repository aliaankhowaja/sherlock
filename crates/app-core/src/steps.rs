//! A recorded run, replayed step by step for the web app: each node's input (the state it
//! received), its output (`tasks[].result`), and which upstream node handed it which keys.
//!
//! Source: LangGraph checkpoint history (`POST /threads/{id}/history`). A checkpoint's `values`
//! are the state its `tasks` received; each task's `result` is what that node wrote. The next
//! checkpoint is the state after the superstep, so its `created_at` ends the step. Node kinds and
//! hand-off edges come from the team's topology when the server can give it. Pure apart from
//! [`fetch_run_steps`], which reads through the injected transport.

use crate::ingestion::{LangGraphTransport, thread_history_path};
use crate::topology::{GraphView, NodeKind, graph_path, layout};
use serde::Serialize;
use serde_json::{Map, Value};

/// Longest string kept in a step's input or output, in characters.
pub const MAX_CHARS: usize = 400;
/// Most list items or map keys kept.
pub const MAX_ITEMS: usize = 20;
/// Most checkpoints read from the server for one run.
const HISTORY_LIMIT: u32 = 1000;

/// Which upstream node last wrote which of a step's input keys.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Feed {
    pub node: String,
    pub keys: Vec<String>,
}

/// One node execution in a recorded run.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Step {
    /// Position in the replay, from 0.
    pub index: usize,
    /// LangGraph superstep (`-1` = the run input arriving). Parallel nodes share a step.
    pub step: Option<i64>,
    /// The checkpoint the node ran from (the fork point for re-running it).
    pub checkpoint_id: Option<String>,
    pub node: String,
    /// Declared kind from the topology; `None` when undeclared or the topology is unavailable.
    pub kind: Option<NodeKind>,
    /// The state the node received, size-capped.
    pub input: Map<String, Value>,
    /// Input keys that changed since the previous step: what was just handed over.
    pub changed: Vec<String>,
    /// For each upstream node, the input keys it last wrote.
    pub input_from: Vec<Feed>,
    /// What the node wrote (`tasks[].result`), size-capped. `null` when it wrote nothing.
    pub output: Value,
    pub error: Option<String>,
    pub started_at: Option<String>,
    pub finished_at: Option<String>,
    pub duration_ms: Option<i64>,
    /// Human-readable lines: what it received, what it produced, or why it failed.
    pub log: Vec<String>,
}

/// A hand-off seen in this run: `source` ran in the step right before `target`.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct HandOff {
    pub source: String,
    pub target: String,
    /// The keys `source` wrote that `target` received (the edge label).
    pub keys: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct RunSteps {
    pub thread_id: String,
    pub graph_id: Option<String>,
    pub assistant_id: Option<String>,
    pub steps: Vec<Step>,
    pub edges: Vec<HandOff>,
    /// The final state of the run, size-capped.
    pub final_state: Map<String, Value>,
    /// Something the reader should know (e.g. topology unavailable, so no kinds).
    pub note: Option<String>,
    /// Is the recording usable? (FR-U7, FR-R9)
    pub health: crate::health::Health,
    /// The LangGraph server's version from `GET /info` (NFR-23); None when it did not say.
    pub server_version: Option<String>,
}

/// A size-capped copy: long strings cut, long lists and maps shortened (same caps as `--progress`).
pub fn clip(value: &Value) -> Value {
    match value {
        Value::String(s) if s.chars().count() > MAX_CHARS => {
            let head: String = s.chars().take(MAX_CHARS).collect();
            Value::from(format!(
                "{head}... (+{} chars)",
                s.chars().count() - MAX_CHARS
            ))
        }
        Value::Array(items) => {
            let mut out: Vec<Value> = items.iter().take(MAX_ITEMS).map(clip).collect();
            if items.len() > MAX_ITEMS {
                out.push(Value::from(format!(
                    "... (+{} more)",
                    items.len() - MAX_ITEMS
                )));
            }
            Value::Array(out)
        }
        Value::Object(map) => Value::Object(clip_map(map)),
        other => other.clone(),
    }
}

fn clip_map(map: &Map<String, Value>) -> Map<String, Value> {
    let mut out: Map<String, Value> = map
        .iter()
        .take(MAX_ITEMS)
        .map(|(k, v)| (k.clone(), clip(v)))
        .collect();
    if map.len() > MAX_ITEMS {
        out.insert(
            "...".into(),
            Value::from(format!("+{} more keys", map.len() - MAX_ITEMS)),
        );
    }
    out
}

/// Milliseconds since the Unix epoch for an RFC 3339 timestamp (`2026-10-13T17:37:45.807331+00:00`).
pub fn epoch_ms(ts: &str) -> Option<i64> {
    let (date, rest) = ts.split_once('T')?;
    let mut d = date.splitn(3, '-').map(|p| p.parse::<i64>().ok());
    let (y, m, day) = (d.next()??, d.next()??, d.next()??);
    let zone_at = rest.find(['Z', 'z', '+']).or_else(|| rest.rfind('-'))?;
    let (time, zone) = rest.split_at(zone_at);
    let mut t = time.splitn(3, ':');
    let (hh, mm) = (
        t.next()?.parse::<i64>().ok()?,
        t.next()?.parse::<i64>().ok()?,
    );
    let secs: f64 = t.next()?.parse().ok()?;
    let offset_min = match zone.chars().next()? {
        'Z' | 'z' => 0,
        sign => {
            let (oh, om) = zone[1..].split_once(':')?;
            let v = oh.parse::<i64>().ok()? * 60 + om.parse::<i64>().ok()?;
            if sign == '-' { -v } else { v }
        }
    };
    // Days from civil (Howard Hinnant's algorithm).
    let y = if m <= 2 { y - 1 } else { y };
    let era = y.div_euclid(400);
    let yoe = y - era * 400;
    let doy = (153 * (m + if m > 2 { -3 } else { 9 }) + 2) / 5 + day - 1;
    let days = era * 146_097 + yoe * 365 + yoe / 4 - yoe / 100 + doy - 719_468;
    let minutes = days * 1440 + hh * 60 + mm - offset_min;
    Some(minutes * 60_000 + (secs * 1000.0).round() as i64)
}

/// A short form of a value for log lines: strings quoted and cut, lists counted, maps by key.
fn brief(v: &Value) -> String {
    match v {
        Value::String(s) if s.chars().count() > 60 => {
            format!("\"{}...\"", s.chars().take(60).collect::<String>())
        }
        Value::String(s) => format!("\"{s}\""),
        Value::Array(a) if a.is_empty() => "[]".into(),
        Value::Array(a) if a.len() == 1 && brief(&a[0]).len() <= 60 => {
            format!("[{}]", brief(&a[0]))
        }
        Value::Array(a) => format!("[{} items]", a.len()),
        Value::Object(m) => {
            let keys: Vec<&str> = m.keys().take(4).map(String::as_str).collect();
            let more = if m.len() > 4 { ", ..." } else { "" };
            format!("{{{}{more}}}", keys.join(", "))
        }
        other => other.to_string(),
    }
}

fn pairs(map: &Map<String, Value>, keys: &[String]) -> String {
    keys.iter()
        .filter_map(|k| map.get(k).map(|v| format!("{k}={}", brief(v))))
        .collect::<Vec<_>>()
        .join(", ")
}

fn str_at<'a>(v: &'a Value, path: &[&str]) -> Option<&'a str> {
    path.iter().try_fold(v, |v, k| v.get(k))?.as_str()
}

fn log_lines(
    node: &str,
    input: &Map<String, Value>,
    changed: &[String],
    output: &Value,
    error: Option<&str>,
    duration_ms: Option<i64>,
) -> Vec<String> {
    let took = duration_ms
        .map(|ms| format!(" in {ms} ms"))
        .unwrap_or_default();
    let written: Vec<String> = output
        .as_object()
        .map(|m| m.keys().cloned().collect())
        .unwrap_or_default();
    let produced = match output.as_object() {
        Some(m) if !m.is_empty() => format!("{node} produced {}{took}", pairs(m, &written)),
        _ => format!("{node} produced nothing{took}"),
    };
    if node == "__start__" {
        return vec![match output.as_object() {
            Some(m) => format!("run started with {}", pairs(m, &written)),
            None => "run started".into(),
        }];
    }
    let shown: Vec<String> = if changed.is_empty() {
        input.keys().take(6).cloned().collect()
    } else {
        changed.to_vec()
    };
    let received = if input.is_empty() {
        format!("{node} received an empty state")
    } else {
        format!("{node} received {}", pairs(input, &shown))
    };
    match error {
        Some(e) => vec![received, format!("{node} failed{took}: {e}")],
        None => vec![received, produced],
    }
}

fn is_edge(graph: Option<&GraphView>, source: &str, target: &str) -> bool {
    graph.is_none_or(|g| {
        g.edges
            .iter()
            .any(|e| e.source == source && e.target == target)
    })
}

/// Expand checkpoint history (any order the server returns: newest first) into ordered steps.
pub fn parse_steps(
    thread_id: &str,
    history: &Value,
    graph: Option<&GraphView>,
) -> anyhow::Result<RunSteps> {
    let mut chrono: Vec<&Value> = history
        .as_array()
        .ok_or_else(|| anyhow::anyhow!("expected JSON array for history, got: {history}"))?
        .iter()
        .rev()
        .collect();
    // Oldest first; a stable sort keeps server order within a step number.
    chrono.sort_by_key(|cp| cp.pointer("/metadata/step").and_then(Value::as_i64));
    let empty = Map::new();
    let mut writer: Vec<(String, String)> = Vec::new(); // (key, last node that wrote it)
    let mut prev_values: Option<&Map<String, Value>> = None;
    let mut prev_nodes: Vec<(String, Vec<String>)> = Vec::new();
    let (mut steps, mut edges) = (Vec::new(), Vec::<HandOff>::new());
    for (i, cp) in chrono.iter().enumerate() {
        let values = cp
            .get("values")
            .and_then(Value::as_object)
            .unwrap_or(&empty);
        let started_at = str_at(cp, &["created_at"]).map(str::to_string);
        let finished_at = chrono
            .get(i + 1)
            .and_then(|n| str_at(n, &["created_at"]))
            .map(str::to_string);
        let duration_ms = started_at
            .as_deref()
            .and_then(epoch_ms)
            .zip(finished_at.as_deref().and_then(epoch_ms))
            .map(|(a, b)| b - a)
            .filter(|d| *d >= 0);
        let changed: Vec<String> = values
            .iter()
            .filter(|(k, v)| prev_values.is_none_or(|p| p.get(*k) != Some(*v)))
            .map(|(k, _)| k.clone())
            .collect();
        let mut input_from: Vec<Feed> = Vec::new();
        for key in values.keys() {
            if let Some((_, node)) = writer.iter().find(|(k, _)| k == key) {
                match input_from.iter_mut().find(|f| &f.node == node) {
                    Some(f) => f.keys.push(key.clone()),
                    None => input_from.push(Feed {
                        node: node.clone(),
                        keys: vec![key.clone()],
                    }),
                }
            }
        }
        let mut this_nodes = Vec::new();
        for task in cp
            .get("tasks")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
        {
            let Some(node) = str_at(task, &["name"]) else {
                continue;
            };
            let output = task.get("result").cloned().unwrap_or(Value::Null);
            let error = task.get("error").filter(|e| !e.is_null()).map(|e| match e {
                Value::String(s) => s.clone(),
                other => other.to_string(),
            });
            let keys: Vec<String> = output
                .as_object()
                .map(|m| m.keys().cloned().collect())
                .unwrap_or_default();
            for (source, wrote) in &prev_nodes {
                let label: Vec<String> = wrote
                    .iter()
                    .filter(|k| values.contains_key(*k))
                    .cloned()
                    .collect();
                if source != node
                    && is_edge(graph, source, node)
                    && !edges
                        .iter()
                        .any(|e| &e.source == source && e.target == node)
                {
                    edges.push(HandOff {
                        source: source.clone(),
                        target: node.to_string(),
                        keys: label,
                    });
                }
            }
            steps.push(Step {
                index: steps.len(),
                step: cp.pointer("/metadata/step").and_then(Value::as_i64),
                checkpoint_id: str_at(cp, &["checkpoint", "checkpoint_id"]).map(str::to_string),
                node: node.to_string(),
                kind: graph
                    .and_then(|g| g.nodes.iter().find(|n| n.id == node))
                    .and_then(|n| n.kind),
                input: clip_map(values),
                log: log_lines(
                    node,
                    values,
                    &changed,
                    &output,
                    error.as_deref(),
                    duration_ms,
                ),
                changed: changed.clone(),
                input_from: input_from.clone(),
                output: clip(&output),
                error,
                started_at: started_at.clone(),
                finished_at: finished_at.clone(),
                duration_ms,
            });
            this_nodes.push((node.to_string(), keys));
        }
        for (node, keys) in &this_nodes {
            for key in keys {
                writer.retain(|(k, _)| k != key);
                writer.push((key.clone(), node.clone()));
            }
        }
        if !this_nodes.is_empty() {
            prev_nodes = this_nodes;
        }
        prev_values = Some(values);
    }
    let meta = |field: &str| {
        chrono
            .iter()
            .find_map(|cp| str_at(cp, &["metadata", field]).map(str::to_string))
    };
    Ok(RunSteps {
        thread_id: thread_id.to_string(),
        graph_id: meta("graph_id"),
        assistant_id: meta("assistant_id"),
        final_state: chrono
            .last()
            .and_then(|cp| cp.get("values").and_then(Value::as_object))
            .map(clip_map)
            .unwrap_or_default(),
        steps,
        edges,
        note: None,
        health: crate::health::check(history),
        server_version: None,
    })
}

/// `GET /info` -> its `version`, if the server says one.
pub fn server_version(transport: &dyn LangGraphTransport) -> Option<String> {
    let info = transport.get_json("/info").ok()?;
    info.get("version")
        .and_then(Value::as_str)
        .map(str::to_string)
}

/// Read one recorded run's history and the team's topology, then expand it into steps.
/// A missing topology is not fatal: steps come back without kinds and with a `note`.
pub fn fetch_run_steps(
    transport: &dyn LangGraphTransport,
    thread_id: &str,
) -> anyhow::Result<RunSteps> {
    if !crate::runner::id_ok(thread_id) {
        anyhow::bail!("not a valid thread id");
    }
    let history = transport.post_json(
        &thread_history_path(thread_id),
        serde_json::json!({ "limit": HISTORY_LIMIT }),
    )?;
    let version = server_version(transport);
    let with_version = |r: RunSteps| RunSteps {
        server_version: version.clone(),
        ..r
    };
    let first = with_version(parse_steps(thread_id, &history, None)?);
    let Some(assistant_id) = first.assistant_id.clone() else {
        return Ok(RunSteps { note: Some("the run does not name its team, so node kinds and hand-off edges are not from the graph".into()), ..first });
    };
    match transport
        .get_json(&graph_path(&assistant_id))
        .and_then(|raw| layout(&raw))
    {
        Ok(graph) => Ok(with_version(parse_steps(
            thread_id,
            &history,
            Some(&graph),
        )?)),
        Err(e) => Ok(RunSteps {
            note: Some(format!(
                "could not read the team's graph ({e:#}); node kinds are unknown and hand-offs are inferred from step order"
            )),
            ..first
        }),
    }
}
