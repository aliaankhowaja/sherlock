//! Reads and validates the diagnosis artifacts written by `sherlock-rec diagnose`
//! (`.sherlock/diagnoses/<thread_id>.json`, schema 1, additive) and turns them into what the
//! run page shows: a verdict summary and one **verified** status per node.
//!
//! The engine is Python; nothing here decides a cause. This module only refuses to claim more than
//! the artifact proves: a node is a culprit only if it is in a G3-verified minimal set, "cleared"
//! only if it was tested in a complete search, and an abstain colours every node "abstained".

use serde::Serialize;
use serde_json::Value;
use std::fmt;
use std::path::PathBuf;

pub const SUPPORTED_SCHEMA: u64 = 1;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NodeStatus {
    /// In a minimal set whose restoration was run and made the check pass.
    Culprit,
    /// Tested in a complete search and in no minimal set: not needed for the fix.
    Cleared,
    /// Not tested, or tested but not decided. No claim either way.
    Unverified,
    /// The diagnosis abstained ("cannot say"): no node is claimed.
    Abstained,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct NodeVerdict {
    pub node: String,
    pub status: NodeStatus,
    /// Plain-language reason for the status.
    pub reason: String,
    /// Minimal sets that contain this node.
    pub sets: Vec<Vec<String>>,
    /// G0 clue sentences about this node. Hints, never part of the status.
    pub clues: Vec<String>,
    /// Numbers of the trials that restored this node (evidence, in trial order).
    pub trials: Vec<u64>,
    /// What restoring it changes: its entry in the known-good run's per-node context difference.
    pub restore: Option<Value>,
    /// Why it was skipped, when it was pruned (skipped is not cleared).
    pub pruned: Option<String>,
    /// A search candidate, so trials could include it.
    pub tested: bool,
    /// It ran in the diagnosed run (on the recorded path).
    pub on_path: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Summary {
    pub thread_id: String,
    pub graph_id: Option<String>,
    pub created: Option<String>,
    /// `found` or `abstain`.
    pub status: String,
    pub reason_code: Option<String>,
    pub reason: String,
    pub minimal_sets: Vec<Vec<String>>,
    pub complete: bool,
    pub trials_used: Option<u64>,
    pub fewer_pct: Option<f64>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Diagnosis {
    pub summary: Summary,
    pub nodes: Vec<NodeVerdict>,
    /// The artifact as written by the engine, unknown fields preserved.
    pub artifact: Value,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct InvalidFile {
    pub file: String,
    pub error: String,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct DiagnosisList {
    /// Where the artifacts are looked for.
    pub dir: String,
    pub diagnoses: Vec<Summary>,
    /// Files that exist but are not valid artifacts. Listed, never silently dropped.
    pub invalid: Vec<InvalidFile>,
}

#[derive(Debug)]
pub enum DiagnosisError {
    BadId(String),
    NotFound(String),
    Invalid(String),
}

impl fmt::Display for DiagnosisError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::BadId(id) => write!(f, "invalid thread id: {id:?}"),
            Self::NotFound(id) => write!(f, "no diagnosis for thread {id}"),
            Self::Invalid(why) => write!(f, "{why}"),
        }
    }
}

impl std::error::Error for DiagnosisError {}

fn invalid(why: impl Into<String>) -> DiagnosisError {
    DiagnosisError::Invalid(why.into())
}

fn str_list(v: &Value) -> Vec<String> {
    v.as_array()
        .map(|a| {
            a.iter()
                .filter_map(|s| s.as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_default()
}

fn set_list(v: &Value, field: &str) -> Result<Vec<Vec<String>>, DiagnosisError> {
    let Some(arr) = v.get(field) else {
        return Ok(Vec::new());
    };
    let arr = arr
        .as_array()
        .ok_or_else(|| invalid(format!("`{field}` must be a list of node lists")))?;
    arr.iter()
        .map(|s| {
            let set = str_list(s);
            if set.is_empty() || set.len() != s.as_array().map_or(0, Vec::len) {
                Err(invalid(format!(
                    "`{field}` must hold non-empty lists of node names"
                )))
            } else {
                Ok(set)
            }
        })
        .collect()
}

fn braces(set: &[String]) -> String {
    format!("{{{}}}", set.join(", "))
}

/// Parse and validate one artifact. Errors say what is wrong in plain words.
pub fn parse_artifact(raw: &str) -> Result<Diagnosis, DiagnosisError> {
    let artifact: Value =
        serde_json::from_str(raw).map_err(|e| invalid(format!("not valid JSON: {e}")))?;
    if !artifact.is_object() {
        return Err(invalid("not a JSON object"));
    }
    match artifact.get("schema").and_then(Value::as_u64) {
        Some(SUPPORTED_SCHEMA) => {}
        Some(n) => {
            return Err(invalid(format!(
                "unsupported artifact schema {n}; this build reads schema {SUPPORTED_SCHEMA}"
            )));
        }
        None => return Err(invalid("missing `schema` number")),
    }
    let thread_id = artifact
        .get("thread_id")
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
        .ok_or_else(|| invalid("missing `thread_id`"))?
        .to_string();
    let status = artifact
        .get("status")
        .and_then(Value::as_str)
        .filter(|s| matches!(*s, "found" | "abstain"))
        .ok_or_else(|| invalid("`status` must be \"found\" or \"abstain\""))?
        .to_string();
    let minimal_sets = set_list(&artifact, "minimal_sets")?;
    let unverified_sets = set_list(&artifact, "unverified_sets")?;
    if status == "found" && minimal_sets.is_empty() {
        return Err(invalid("status is \"found\" but no minimal set is listed"));
    }
    if status == "abstain" && !minimal_sets.is_empty() {
        return Err(invalid(
            "status is \"abstain\" but minimal sets are listed; refusing to show a cause the engine did not claim",
        ));
    }
    let text = |k: &str| artifact.get(k).and_then(Value::as_str).map(str::to_string);
    let summary = Summary {
        thread_id,
        graph_id: text("graph_id"),
        created: text("created"),
        status,
        reason_code: text("reason_code"),
        reason: text("reason").unwrap_or_default(),
        minimal_sets,
        complete: artifact
            .get("complete")
            .and_then(Value::as_bool)
            .unwrap_or(false),
        trials_used: artifact
            .pointer("/budget/trials_used")
            .and_then(Value::as_u64),
        fewer_pct: artifact
            .pointer("/trial_reduction/fewer_pct")
            .and_then(Value::as_f64),
    };
    let nodes = node_verdicts(&artifact, &summary, &unverified_sets);
    Ok(Diagnosis {
        summary,
        nodes,
        artifact,
    })
}

fn node_verdicts(
    artifact: &Value,
    summary: &Summary,
    unverified_sets: &[Vec<String>],
) -> Vec<NodeVerdict> {
    let pruning = artifact.get("pruning").unwrap_or(&Value::Null);
    let candidates = str_list(&pruning["candidates"]);
    let pruned = pruning["pruned"].as_object();
    let untestable: Vec<String> = pruning["untestable"]
        .as_array()
        .map(|a| {
            a.iter()
                .filter_map(|u| {
                    u.as_str()
                        .or_else(|| u.get("node").and_then(Value::as_str))
                        .map(str::to_string)
                })
                .collect()
        })
        .unwrap_or_default();
    let clue_list = artifact
        .get("clues")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let trial_list = artifact
        .get("trials")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let context_diff = artifact
        .get("known_good_source")
        .and_then(|s| s.get("context_diff"))
        .and_then(Value::as_object);
    let on_path = str_list(&pruning["nodes_on_path"]);

    // Execution order first, then any node only named elsewhere.
    let mut order = str_list(&pruning["nodes_on_path"]);
    let mut extra: Vec<String> = Vec::new();
    extra.extend(summary.minimal_sets.iter().flatten().cloned());
    extra.extend(unverified_sets.iter().flatten().cloned());
    extra.extend(candidates.iter().cloned());
    extra.extend(untestable.iter().cloned());
    extra.extend(
        clue_list
            .iter()
            .filter_map(|c| c["node"].as_str().map(str::to_string)),
    );
    for n in extra {
        if !order.contains(&n) {
            order.push(n);
        }
    }

    order
        .into_iter()
        .map(|node| {
            let sets: Vec<Vec<String>> = summary
                .minimal_sets
                .iter()
                .filter(|s| s.contains(&node))
                .cloned()
                .collect();
            let clues = clue_list
                .iter()
                .filter(|c| c["node"].as_str() == Some(node.as_str()))
                .filter_map(|c| c["detail"].as_str().map(str::to_string))
                .collect();
            let (status, reason) = if summary.status == "abstain" {
                (
                    NodeStatus::Abstained,
                    format!("cannot say: {}", summary.reason),
                )
            } else if let Some(first) = sets.first() {
                let reason = if sets.len() == 1 && first.len() == 1 {
                    "restoring this node alone to known-good makes the run pass".to_string()
                } else {
                    let all: Vec<String> = sets.iter().map(|s| braces(s)).collect();
                    format!(
                        "in the smallest fix{} {}: restoring that set makes the run pass, and no smaller part of it does",
                        if sets.len() == 1 { "" } else { "es" },
                        all.join(" and ")
                    )
                };
                (NodeStatus::Culprit, reason)
            } else if let Some(set) = unverified_sets.iter().find(|s| s.contains(&node)) {
                (
                    NodeStatus::Unverified,
                    format!(
                        "part of {}, which passes but whose minimality could not be certified",
                        braces(set)
                    ),
                )
            } else if let Some(why) = pruned.and_then(|p| p.get(&node)).and_then(Value::as_str) {
                (NodeStatus::Unverified, format!("not tested: {why}"))
            } else if untestable.contains(&node) {
                (
                    NodeStatus::Unverified,
                    "not tested: no known-good behaviour for this node".to_string(),
                )
            } else if candidates.contains(&node) && summary.complete {
                (
                    NodeStatus::Cleared,
                    "tested: in none of the smallest fixes, so not needed".to_string(),
                )
            } else if candidates.contains(&node) {
                (
                    NodeStatus::Unverified,
                    "the search stopped before every set was decided".to_string(),
                )
            } else {
                (NodeStatus::Unverified, "not tested".to_string())
            };
            let trials = trial_list
                .iter()
                .filter(|t| str_list(&t["restored"]).contains(&node))
                .filter_map(|t| t["n"].as_u64())
                .collect();
            NodeVerdict {
                restore: context_diff.and_then(|c| c.get(&node)).cloned(),
                pruned: pruned
                    .and_then(|p| p.get(&node))
                    .and_then(Value::as_str)
                    .map(str::to_string),
                tested: candidates.contains(&node),
                on_path: on_path.contains(&node),
                trials,
                node,
                status,
                reason,
                sets,
                clues,
            }
        })
        .collect()
}

/// Reads artifacts from `<sherlock dir>/diagnoses/`.
pub struct DiagnosisStore {
    sherlock_dir: PathBuf,
}

impl DiagnosisStore {
    pub fn new(sherlock_dir: impl Into<PathBuf>) -> Self {
        Self {
            sherlock_dir: sherlock_dir.into(),
        }
    }

    fn dir(&self) -> PathBuf {
        self.sherlock_dir.join("diagnoses")
    }

    /// Every valid artifact, newest first. A missing directory is an empty list.
    pub fn list(&self) -> DiagnosisList {
        let dir = self.dir();
        let mut diagnoses = Vec::new();
        let mut bad = Vec::new();
        if let Ok(entries) = std::fs::read_dir(&dir) {
            for entry in entries.flatten() {
                let path = entry.path();
                if path.extension().is_none_or(|e| e != "json") {
                    continue;
                }
                let file = entry.file_name().to_string_lossy().into_owned();
                match std::fs::read_to_string(&path)
                    .map_err(|e| invalid(format!("cannot read: {e}")))
                    .and_then(|raw| parse_artifact(&raw))
                {
                    Ok(d) => diagnoses.push(d.summary),
                    Err(e) => bad.push(InvalidFile {
                        file,
                        error: e.to_string(),
                    }),
                }
            }
        }
        diagnoses.sort_by(|a, b| {
            b.created
                .cmp(&a.created)
                .then_with(|| a.thread_id.cmp(&b.thread_id))
        });
        bad.sort_by(|a, b| a.file.cmp(&b.file));
        DiagnosisList {
            dir: dir.display().to_string(),
            diagnoses,
            invalid: bad,
        }
    }

    pub fn get(&self, thread_id: &str) -> Result<Diagnosis, DiagnosisError> {
        let ok = !thread_id.is_empty()
            && thread_id
                .chars()
                .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_');
        if !ok {
            return Err(DiagnosisError::BadId(thread_id.to_string()));
        }
        let path = self.dir().join(format!("{thread_id}.json"));
        let raw = std::fs::read_to_string(path)
            .map_err(|_| DiagnosisError::NotFound(thread_id.to_string()))?;
        let d = parse_artifact(&raw)?;
        if d.summary.thread_id != thread_id {
            return Err(invalid(format!(
                "file is for thread {}, not {thread_id}",
                d.summary.thread_id
            )));
        }
        Ok(d)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    const TWO_CAUSE: &str = include_str!(
        "../../../harness/fixtures/sherlock-demo/diagnoses/01a1371a-f0a7-79f2-bb6e-4b065c36df4b.json"
    );
    const ABSTAIN: &str = include_str!(
        "../../../harness/fixtures/sherlock-demo/diagnoses/01a1371a-f74e-70c3-b4d9-86e2ac13d36e.json"
    );

    fn status_of(d: &Diagnosis, node: &str) -> NodeStatus {
        d.nodes.iter().find(|n| n.node == node).unwrap().status
    }

    fn artifact(extra: Value) -> String {
        let mut base = json!({
            "schema": 1, "thread_id": "t1", "status": "found", "reason": "r",
            "minimal_sets": [["b"]], "unverified_sets": [], "complete": true,
            "pruning": {"nodes_on_path": ["a", "b", "c", "d"], "candidates": ["b", "c"],
                        "pruned": {"a": "same output as the passing run"}, "untestable": ["d"]},
            "clues": [{"kind": "error", "node": "c", "detail": "c raised"}],
        });
        base.as_object_mut()
            .unwrap()
            .extend(extra.as_object().unwrap().clone());
        base.to_string()
    }

    #[test]
    fn real_two_cause_artifact_colours_the_pair_as_culprits() {
        let d = parse_artifact(TWO_CAUSE).unwrap();
        assert_eq!(d.summary.status, "found");
        assert_eq!(d.summary.minimal_sets, vec![vec!["retriever", "extractor"]]);
        assert_eq!(d.summary.trials_used, Some(3));
        assert_eq!(d.summary.fewer_pct, Some(90.3));
        let order: Vec<_> = d.nodes.iter().map(|n| n.node.as_str()).collect();
        assert_eq!(
            order,
            ["router", "retriever", "extractor", "writer", "reviewer"]
        );
        assert_eq!(status_of(&d, "retriever"), NodeStatus::Culprit);
        assert_eq!(status_of(&d, "extractor"), NodeStatus::Culprit);
        // pruned nodes were not tested: no claim, in particular not "cleared"
        assert_eq!(status_of(&d, "router"), NodeStatus::Unverified);
        assert_eq!(status_of(&d, "writer"), NodeStatus::Unverified);
        assert!(d.nodes[1].reason.contains("{retriever, extractor}"));
        // clues are carried as hints only; writer has one but stays unverified
        assert!(!d.nodes[3].clues.is_empty());
    }

    #[test]
    fn each_node_carries_its_trials_restoration_and_pruning_for_the_config_panel() {
        let d = parse_artifact(TWO_CAUSE).unwrap();
        let node = |id: &str| d.nodes.iter().find(|n| n.node == id).unwrap();
        // trial numbers that restored the node, in order
        assert_eq!(node("retriever").trials, vec![1, 2]);
        assert_eq!(node("extractor").trials, vec![1, 3]);
        assert!(node("router").trials.is_empty());
        // what restoring it changes, from the known-good run's context difference
        assert_eq!(
            node("retriever").restore,
            Some(json!({"faults": {"$remove": ["retriever.drop_latest"]}}))
        );
        assert_eq!(node("router").restore, None);
        // pruned nodes say why they were skipped; tested ones say they were tested
        assert!(
            node("router")
                .pruned
                .as_deref()
                .unwrap()
                .contains("same output")
        );
        assert!(node("retriever").tested && !node("router").tested);
        assert!(node("retriever").on_path && node("router").on_path);
    }

    #[test]
    fn real_abstain_artifact_claims_no_node() {
        let d = parse_artifact(ABSTAIN).unwrap();
        assert_eq!(d.summary.status, "abstain");
        assert_eq!(d.summary.reason_code.as_deref(), Some("no_known_good"));
        assert!(!d.nodes.is_empty());
        assert!(d.nodes.iter().all(|n| n.status == NodeStatus::Abstained));
        assert!(d.nodes[0].reason.starts_with("cannot say:"));
    }

    #[test]
    fn cleared_needs_a_tested_candidate_in_a_complete_search() {
        let d = parse_artifact(&artifact(json!({}))).unwrap();
        assert_eq!(status_of(&d, "b"), NodeStatus::Culprit);
        assert_eq!(status_of(&d, "c"), NodeStatus::Cleared);
        assert_eq!(status_of(&d, "a"), NodeStatus::Unverified);
        assert_eq!(status_of(&d, "d"), NodeStatus::Unverified);
        let d = parse_artifact(&artifact(json!({"complete": false}))).unwrap();
        assert_eq!(status_of(&d, "c"), NodeStatus::Unverified);
        assert_eq!(status_of(&d, "b"), NodeStatus::Culprit);
    }

    #[test]
    fn g1_scores_are_accepted_and_never_change_what_the_trials_decided() {
        let g1 = json!({"g1": {
            "backend": "laya", "status": "ok", "order_variant": "A",
            "cache": {"hits": 0, "misses": 2}, "order_changed": true, "ms": 2140,
            "scores": [
                {"node": "c", "score": 0.99, "answers": {"needs_restore": {"yes": 0.99, "no": 0.01}}},
                {"node": "b", "score": 0.01},
                {"node": "a", "score": null},
            ],
        }});
        // `c` is cleared by its trial and `b` is the culprit; G1 says the opposite.
        for base in [
            json!({}),
            json!({"status": "abstain", "minimal_sets": [], "reason_code": "budget_exhausted"}),
        ] {
            let plain = parse_artifact(&artifact(base.clone())).unwrap();
            let mut with = base;
            with.as_object_mut()
                .unwrap()
                .extend(g1.as_object().unwrap().clone());
            let scored = parse_artifact(&artifact(with)).unwrap();
            assert_eq!(scored.summary.status, plain.summary.status);
            assert_eq!(scored.summary.minimal_sets, plain.summary.minimal_sets);
            let view = |d: &Diagnosis| -> Vec<_> {
                d.nodes
                    .iter()
                    .map(|n| (n.node.clone(), n.status, n.reason.clone()))
                    .collect()
            };
            assert_eq!(view(&scored), view(&plain));
            assert!(scored.artifact["g1"]["scores"].is_array());
        }
        let d = parse_artifact(&artifact(g1)).unwrap();
        assert_eq!(status_of(&d, "c"), NodeStatus::Cleared);
        assert_eq!(status_of(&d, "b"), NodeStatus::Culprit);
    }

    #[test]
    fn unverified_set_members_are_not_culprits() {
        let raw = artifact(json!({"unverified_sets": [["c", "x"]]}));
        let d = parse_artifact(&raw).unwrap();
        assert_eq!(status_of(&d, "c"), NodeStatus::Unverified);
        assert_eq!(status_of(&d, "x"), NodeStatus::Unverified);
    }

    #[test]
    fn rejects_artifacts_that_claim_too_much_or_too_little() {
        let cases = [
            ("not json", "not valid JSON"),
            ("[]", "not a JSON object"),
            (
                r#"{"schema": 2, "thread_id": "t", "status": "found"}"#,
                "unsupported artifact schema 2",
            ),
            (
                r#"{"thread_id": "t", "status": "found"}"#,
                "missing `schema`",
            ),
            (r#"{"schema": 1, "status": "found"}"#, "missing `thread_id`"),
            (
                r#"{"schema": 1, "thread_id": "t", "status": "maybe"}"#,
                "`status`",
            ),
            (
                r#"{"schema": 1, "thread_id": "t", "status": "found", "minimal_sets": []}"#,
                "no minimal set",
            ),
            (
                r#"{"schema": 1, "thread_id": "t", "status": "abstain", "minimal_sets": [["a"]]}"#,
                "refusing to show a cause",
            ),
            (
                r#"{"schema": 1, "thread_id": "t", "status": "found", "minimal_sets": [[]]}"#,
                "non-empty",
            ),
        ];
        for (raw, want) in cases {
            let err = parse_artifact(raw).unwrap_err().to_string();
            assert!(err.contains(want), "{raw}: {err}");
        }
    }

    #[test]
    fn store_lists_newest_first_reports_bad_files_and_guards_ids() {
        let tmp = std::env::temp_dir().join(format!("sherlock-diag-{}", std::process::id()));
        let dir = tmp.join("diagnoses");
        std::fs::create_dir_all(&dir).unwrap();
        let mk = |id: &str, created: &str| artifact(json!({"thread_id": id, "created": created}));
        std::fs::write(dir.join("old.json"), mk("old", "2026-10-01T00:00:00+00:00")).unwrap();
        std::fs::write(dir.join("new.json"), mk("new", "2026-10-02T00:00:00+00:00")).unwrap();
        std::fs::write(dir.join("broken.json"), "{").unwrap();
        std::fs::write(dir.join("notes.txt"), "ignored").unwrap();
        std::fs::write(
            dir.join("mismatch.json"),
            mk("other", "2026-10-03T00:00:00+00:00"),
        )
        .unwrap();

        let store = DiagnosisStore::new(&tmp);
        let list = store.list();
        let ids: Vec<_> = list
            .diagnoses
            .iter()
            .map(|s| s.thread_id.as_str())
            .collect();
        assert_eq!(ids, ["other", "new", "old"]);
        assert_eq!(list.invalid.len(), 1);
        assert_eq!(list.invalid[0].file, "broken.json");
        assert_eq!(store.get("new").unwrap().summary.thread_id, "new");
        assert!(matches!(
            store.get("nope"),
            Err(DiagnosisError::NotFound(_))
        ));
        assert!(matches!(store.get("../x"), Err(DiagnosisError::BadId(_))));
        assert!(matches!(
            store.get("broken"),
            Err(DiagnosisError::Invalid(_))
        ));
        assert!(matches!(
            store.get("mismatch"),
            Err(DiagnosisError::Invalid(_))
        ));
        std::fs::remove_dir_all(&tmp).unwrap();

        let missing = DiagnosisStore::new(tmp.join("nowhere")).list();
        assert!(missing.diagnoses.is_empty() && missing.invalid.is_empty());
    }
}
