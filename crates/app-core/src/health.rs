//! Is a recording usable? A short checklist over the raw checkpoint history, so an empty or broken
//! run says what is missing instead of drawing a hollow graph (FR-U7, FR-R9).

use serde::Serialize;
use serde_json::Value;

pub const NO_HISTORY: &str = "cannot diagnose: no usable history";
const REDACTED: &str = "[REDACTED]";

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Item {
    pub id: &'static str,
    pub label: &'static str,
    pub ok: bool,
    pub detail: String,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Health {
    /// At least one node ran and the run's input checkpoint exists.
    pub usable: bool,
    pub summary: String,
    pub items: Vec<Item>,
}

fn redacted(v: &Value) -> usize {
    match v {
        Value::String(s) => usize::from(s == REDACTED),
        Value::Array(a) => a.iter().map(redacted).sum(),
        Value::Object(m) => m.values().map(redacted).sum(),
        _ => 0,
    }
}

fn tasks(cp: &Value) -> impl Iterator<Item = &Value> {
    cp.get("tasks")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
}

fn item(id: &'static str, label: &'static str, ok: bool, detail: impl Into<String>) -> Item {
    Item {
        id,
        label,
        ok,
        detail: detail.into(),
    }
}

pub fn check(history: &Value) -> Health {
    let cps: Vec<&Value> = history
        .as_array()
        .map(|a| a.iter().collect())
        .unwrap_or_default();
    let step = |cp: &Value| cp.pointer("/metadata/step").and_then(Value::as_i64);
    let node_tasks: Vec<&Value> = cps
        .iter()
        .flat_map(|cp| tasks(cp))
        .filter(|t| t.get("name").and_then(Value::as_str) != Some("__start__"))
        .collect();
    let root = cps.iter().any(|cp| step(cp) == Some(-1));
    let missing = node_tasks
        .iter()
        .filter(|t| {
            t.get("result").is_none_or(Value::is_null) && t.get("error").is_none_or(Value::is_null)
        })
        .count();
    let hidden: usize = cps
        .iter()
        .map(|cp| cp.get("values").map_or(0, redacted))
        .sum::<usize>()
        + node_tasks
            .iter()
            .map(|t| t.get("result").map_or(0, redacted))
            .sum::<usize>();
    let final_ok = cps.iter().any(|cp| {
        cp.get("values")
            .and_then(Value::as_object)
            .is_some_and(|m| !m.is_empty())
    });
    let items = vec![
        item(
            "steps",
            "Node steps were recorded",
            !node_tasks.is_empty(),
            format!(
                "{} node run(s) in {} checkpoint(s)",
                node_tasks.len(),
                cps.len()
            ),
        ),
        item(
            "root",
            "The run's input checkpoint exists",
            root,
            if root {
                "found"
            } else {
                "missing; the run may have used durability=\"exit\" (only the last state is saved)"
            },
        ),
        item(
            "io",
            "Every node has its output",
            !node_tasks.is_empty() && missing == 0,
            format!(
                "{missing} output missing, {hidden} value(s) redacted (redacted is on purpose; missing is not)"
            ),
        ),
        item(
            "final_state",
            "A final state exists",
            final_ok,
            if final_ok {
                "found"
            } else {
                "no checkpoint carries any state"
            },
        ),
    ];
    let usable = !node_tasks.is_empty() && root;
    Health {
        usable,
        summary: if usable {
            "usable history".into()
        } else {
            NO_HISTORY.into()
        },
        items,
    }
}
