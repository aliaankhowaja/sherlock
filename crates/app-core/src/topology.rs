//! Graph view: the team's LangGraph topology (nodes, handoffs, parallel branches,
//! conditional routes) joined to the verified status of each node.
//!
//! Topology comes from `GET /assistants/{id}/graph`; status comes only from
//! [`crate::diagnosis`]. This module lays the graph out in layers (left to right)
//! and never decides a status itself: a node the verdict does not mention gets no claim.
//! Without a diagnosis ([`layout`]) every node is drawn with no status at all.
//! A node's kind (deterministic / LLM / tool) is what the team declared in LangGraph node
//! metadata (`add_node(..., metadata={"kind": "llm"})`); nothing is inferred.

use crate::diagnosis::{Diagnosis, NodeStatus};
use crate::ingestion::LangGraphTransport;
use serde::Serialize;
use serde_json::Value;

const START: &str = "__start__";
const END: &str = "__end__";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NodeRole {
    Start,
    End,
    Node,
}

/// What a node does, as declared by the team (LangGraph node metadata `kind`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NodeKind {
    Deterministic,
    Llm,
    Tool,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct GraphNode {
    pub id: String,
    pub role: NodeRole,
    /// Declared kind; `None` when the team did not declare one.
    pub kind: Option<NodeKind>,
    /// Verified status. `None` for the start/end markers and when there is no diagnosis.
    pub status: Option<NodeStatus>,
    pub reason: String,
    /// Column, left to right.
    pub layer: usize,
    /// Vertical position within the whole drawing (centred per column; may be fractional).
    pub row: f64,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct GraphEdge {
    pub source: String,
    pub target: String,
    /// A conditional route: taken only when the router picks it.
    pub conditional: bool,
    /// Points backwards (a loop); drawn as an arc.
    pub back: bool,
    /// Both ends ran in the diagnosed run: a handoff on the recorded path that pruning reasoned over.
    pub on_path: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct GraphView {
    pub nodes: Vec<GraphNode>,
    pub edges: Vec<GraphEdge>,
    pub layers: usize,
    pub rows: f64,
    /// Something the reader should know about how the graph and verdict were joined.
    pub note: Option<String>,
}

pub fn graph_path(assistant_id: &str) -> String {
    format!("/assistants/{assistant_id}/graph")
}

/// Fetch the topology of the team that ran `d` (matched by `graph_id`) and join it to the verdict.
pub fn graph_for_diagnosis(
    transport: &dyn LangGraphTransport,
    d: &Diagnosis,
) -> anyhow::Result<GraphView> {
    let graph_id =
        d.summary.graph_id.as_deref().ok_or_else(|| {
            anyhow::anyhow!("this diagnosis does not name its team (no graph_id)")
        })?;
    let team = crate::ingestion::list_teams(transport)?
        .into_iter()
        .find(|t| t.graph_id == graph_id)
        .ok_or_else(|| anyhow::anyhow!("the server has no team for graph `{graph_id}`"))?;
    build_view(&transport.get_json(&graph_path(&team.assistant_id))?, d)
}

/// Topology only, no verdict: every node is drawn without a status (the pick step).
pub fn graph_for_team(
    transport: &dyn LangGraphTransport,
    assistant_id: &str,
) -> anyhow::Result<GraphView> {
    layout(&transport.get_json(&graph_path(assistant_id))?)
}

fn role_of(id: &str) -> NodeRole {
    match id {
        START => NodeRole::Start,
        END => NodeRole::End,
        _ => NodeRole::Node,
    }
}

fn declared_kind(node: &Value) -> Option<NodeKind> {
    match node.get("metadata")?.get("kind")?.as_str()? {
        "deterministic" => Some(NodeKind::Deterministic),
        "llm" => Some(NodeKind::Llm),
        "tool" => Some(NodeKind::Tool),
        _ => None,
    }
}

/// Depth-first walk that marks edges pointing at a node still on the stack (loops).
fn mark_back_edges(at: usize, out: &[Vec<(usize, usize)>], state: &mut [u8], back: &mut [bool]) {
    state[at] = 1;
    for &(to, edge) in &out[at] {
        match state[to] {
            0 => mark_back_edges(to, out, state, back),
            1 => back[edge] = true,
            _ => {}
        }
    }
    state[at] = 2;
}

/// Lay out a LangGraph drawable graph with no verdict attached.
pub fn layout(raw: &Value) -> anyhow::Result<GraphView> {
    build(raw, None)
}

/// Lay out a LangGraph drawable graph and attach verified statuses.
pub fn build_view(raw: &Value, d: &Diagnosis) -> anyhow::Result<GraphView> {
    build(raw, Some(d))
}

fn build(raw: &Value, d: Option<&Diagnosis>) -> anyhow::Result<GraphView> {
    let listed = raw
        .get("nodes")
        .and_then(Value::as_array)
        .ok_or_else(|| anyhow::anyhow!("the graph has no `nodes` list"))?;
    let mut ids: Vec<String> = Vec::new();
    let push = |ids: &mut Vec<String>, id: &str| {
        if !ids.iter().any(|i| i == id) {
            ids.push(id.to_string());
        }
    };
    for n in listed {
        if let Some(id) = n.get("id").and_then(Value::as_str) {
            push(&mut ids, id);
        }
    }
    let mut raw_edges: Vec<(String, String, bool)> = Vec::new();
    for e in raw
        .get("edges")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
    {
        if let (Some(s), Some(t)) = (
            e.get("source").and_then(Value::as_str),
            e.get("target").and_then(Value::as_str),
        ) {
            push(&mut ids, s);
            push(&mut ids, t);
            let conditional = e
                .get("conditional")
                .and_then(Value::as_bool)
                .unwrap_or(false);
            raw_edges.push((s.to_string(), t.to_string(), conditional));
        }
    }
    if !ids.iter().any(|i| role_of(i) == NodeRole::Node) {
        anyhow::bail!("the graph has no nodes to draw");
    }
    // Nodes the verdict names that the server's graph no longer has: keep them, say so.
    let verdicts: &[crate::diagnosis::NodeVerdict] = d.map_or(&[], |d| &d.nodes);
    let missing: Vec<String> = verdicts
        .iter()
        .filter(|n| !ids.contains(&n.node))
        .map(|n| n.node.clone())
        .collect();
    ids.extend(missing.iter().cloned());
    let n = ids.len();
    let at = |id: &str| ids.iter().position(|i| i == id).expect("registered above");

    let mut out: Vec<Vec<(usize, usize)>> = vec![Vec::new(); n];
    for (k, (s, t, _)) in raw_edges.iter().enumerate() {
        out[at(s)].push((at(t), k));
    }
    let mut back = vec![false; raw_edges.len()];
    let mut state = vec![0u8; n];
    let roots = ids
        .iter()
        .position(|i| i == START)
        .into_iter()
        .chain(0..n)
        .collect::<Vec<_>>();
    for r in roots {
        if state[r] == 0 {
            mark_back_edges(r, &out, &mut state, &mut back);
        }
    }

    // Longest path from the sources, over forward edges only.
    let forward: Vec<(usize, usize)> = raw_edges
        .iter()
        .enumerate()
        .filter(|(k, _)| !back[*k])
        .map(|(_, (s, t, _))| (at(s), at(t)))
        .collect();
    let mut layer = vec![0usize; n];
    for _ in 0..n {
        for &(s, t) in &forward {
            layer[t] = layer[t].max(layer[s] + 1);
        }
    }
    if let Some(end) = ids.iter().position(|i| i == END) {
        let deepest = (0..n)
            .filter(|&i| i != end)
            .map(|i| layer[i])
            .max()
            .unwrap_or(0);
        layer[end] = layer[end].max(deepest + 1);
    }
    let layers = layer.iter().max().map_or(0, |m| m + 1);

    // Order each column by the average position of its predecessors (fewer crossings).
    let mut pos = vec![0f64; n];
    let mut rows = 0usize;
    let mut row = vec![0f64; n];
    for l in 0..layers {
        let mut col: Vec<usize> = (0..n).filter(|&i| layer[i] == l).collect();
        let key = |i: usize| -> f64 {
            let preds: Vec<f64> = forward
                .iter()
                .filter(|e| e.1 == i)
                .map(|e| pos[e.0])
                .collect();
            if preds.is_empty() {
                f64::MAX
            } else {
                preds.iter().sum::<f64>() / preds.len() as f64
            }
        };
        col.sort_by(|&a, &b| key(a).total_cmp(&key(b)).then(a.cmp(&b)));
        for (p, &i) in col.iter().enumerate() {
            pos[i] = p as f64;
        }
        rows = rows.max(col.len());
    }
    for l in 0..layers {
        let count = (0..n).filter(|&i| layer[i] == l).count();
        for i in (0..n).filter(|&i| layer[i] == l) {
            row[i] = (rows - count) as f64 / 2.0 + pos[i];
        }
    }

    let nodes = ids
        .iter()
        .enumerate()
        .map(|(i, id)| {
            let role = role_of(id);
            let (status, reason) = match (role, d, verdicts.iter().find(|v| &v.node == id)) {
                (_, None, _) => (None, String::new()),
                (NodeRole::Node, _, Some(v)) => (Some(v.status), v.reason.clone()),
                (NodeRole::Node, Some(d), None) if d.summary.status == "abstain" => (
                    Some(NodeStatus::Abstained),
                    "no verdict for this run, so no claim about this node".to_string(),
                ),
                (NodeRole::Node, _, None) => (
                    Some(NodeStatus::Unverified),
                    "not on the path this diagnosis looked at, so no claim about this node"
                        .to_string(),
                ),
                _ => (None, String::new()),
            };
            GraphNode {
                id: id.clone(),
                role,
                kind: listed
                    .iter()
                    .find(|n| n.get("id").and_then(Value::as_str) == Some(id))
                    .and_then(declared_kind),
                status,
                reason,
                layer: layer[i],
                row: row[i],
            }
        })
        .collect();
    let ran = |id: &str| {
        d.is_some()
            && (role_of(id) != NodeRole::Node || verdicts.iter().any(|v| v.node == id && v.on_path))
    };
    let edges = raw_edges
        .into_iter()
        .enumerate()
        .map(|(k, (source, target, conditional))| GraphEdge {
            on_path: ran(&source) && ran(&target),
            source,
            target,
            conditional,
            back: back[k],
        })
        .collect();
    let note = (!missing.is_empty()).then(|| {
        format!(
            "The server's current graph has no node {}. It is shown unlinked, so the team may have changed since this run was diagnosed.",
            missing.join(", ")
        )
    });
    Ok(GraphView {
        nodes,
        edges,
        layers,
        rows: rows as f64,
        note,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::diagnosis::parse_artifact;
    use serde_json::json;
    use std::cell::RefCell;

    const TWO_CAUSE: &str = include_str!(
        "../../../harness/fixtures/sherlock-demo/diagnoses/01a1371a-f0a7-79f2-bb6e-4b065c36df4b.json"
    );
    const ABSTAIN: &str = include_str!(
        "../../../harness/fixtures/sherlock-demo/diagnoses/01a1371a-f74e-70c3-b4d9-86e2ac13d36e.json"
    );

    fn edges(pairs: &[(&str, &str)]) -> Vec<Value> {
        pairs
            .iter()
            .map(|(s, t)| json!({"source": s, "target": t}))
            .collect()
    }

    fn graph(ids: &[&str], pairs: &[(&str, &str)]) -> Value {
        let mut nodes: Vec<Value> = vec![json!({"id": START})];
        nodes.extend(ids.iter().map(|i| json!({"id": i, "type": "runnable"})));
        nodes.push(json!({"id": END}));
        json!({"nodes": nodes, "edges": edges(pairs)})
    }

    fn vendor_graph() -> Value {
        graph(
            &["router", "retriever", "extractor", "writer", "reviewer"],
            &[
                (START, "router"),
                ("router", "retriever"),
                ("retriever", "extractor"),
                ("extractor", "writer"),
                ("writer", "reviewer"),
                ("reviewer", END),
            ],
        )
    }

    fn node<'a>(v: &'a GraphView, id: &str) -> &'a GraphNode {
        v.nodes.iter().find(|n| n.id == id).unwrap()
    }

    #[test]
    fn linear_team_gets_one_column_per_node_and_the_verified_colours() {
        let d = parse_artifact(TWO_CAUSE).unwrap();
        let v = build_view(&vendor_graph(), &d).unwrap();
        let layers: Vec<_> = [
            "__start__",
            "router",
            "retriever",
            "extractor",
            "writer",
            "reviewer",
            "__end__",
        ]
        .iter()
        .map(|id| node(&v, id).layer)
        .collect();
        assert_eq!(layers, [0, 1, 2, 3, 4, 5, 6]);
        assert_eq!(v.layers, 7);
        assert_eq!(node(&v, "retriever").status, Some(NodeStatus::Culprit));
        assert_eq!(node(&v, "extractor").status, Some(NodeStatus::Culprit));
        assert_eq!(node(&v, "router").status, Some(NodeStatus::Unverified));
        assert_eq!(node(&v, "writer").status, Some(NodeStatus::Unverified));
        // the status text is the verdict's own reason, not new wording
        assert!(
            node(&v, "retriever")
                .reason
                .contains("{retriever, extractor}")
        );
        assert_eq!(node(&v, "__start__").role, NodeRole::Start);
        assert_eq!(node(&v, "__start__").status, None);
        assert_eq!(node(&v, "__end__").role, NodeRole::End);
        assert_eq!(v.note, None);
    }

    #[test]
    fn parallel_branches_share_a_column_and_get_different_rows() {
        let g = graph(
            &["parse", "stock", "pricing", "assemble"],
            &[
                (START, "parse"),
                ("parse", "pricing"),
                ("parse", "stock"),
                ("pricing", "assemble"),
                ("stock", "assemble"),
                ("assemble", END),
            ],
        );
        let d = parse_artifact(
            &json!({
                "schema": 1, "thread_id": "t", "status": "found", "reason": "r",
                "minimal_sets": [["stock"]], "complete": true,
                "pruning": {"nodes_on_path": ["parse", "stock", "pricing", "assemble"],
                            "candidates": ["stock", "pricing"], "pruned": {}, "untestable": []},
            })
            .to_string(),
        )
        .unwrap();
        let v = build_view(&g, &d).unwrap();
        assert_eq!(node(&v, "stock").layer, node(&v, "pricing").layer);
        assert_eq!(node(&v, "stock").layer, 2);
        assert_ne!(node(&v, "stock").row, node(&v, "pricing").row);
        assert_eq!(node(&v, "assemble").layer, 3);
        assert_eq!(node(&v, "__end__").layer, 4);
        assert_eq!(v.rows, 2.0);
        // single-node columns are centred between the two branches
        assert_eq!(node(&v, "parse").row, 0.5);
    }

    #[test]
    fn conditional_routes_are_kept_and_back_edges_do_not_hang_the_layout() {
        let g = json!({
            "nodes": [{"id": START}, {"id": "a"}, {"id": "b"}, {"id": END}],
            "edges": [
                {"source": START, "target": "a"},
                {"source": "a", "target": "b"},
                {"source": "b", "target": "a", "conditional": true, "data": "retry"},
                {"source": "b", "target": END, "conditional": true},
            ]
        });
        let d = parse_artifact(TWO_CAUSE).unwrap();
        let v = build_view(&g, &d).unwrap();
        let back = v
            .edges
            .iter()
            .find(|e| e.source == "b" && e.target == "a")
            .unwrap();
        assert!(back.back && back.conditional);
        let fwd = v
            .edges
            .iter()
            .find(|e| e.source == "b" && e.target == END)
            .unwrap();
        assert!(!fwd.back && fwd.conditional);
        assert!(node(&v, "a").layer < node(&v, "b").layer);
        assert!(node(&v, "b").layer < node(&v, "__end__").layer);
    }

    #[test]
    fn abstain_claims_no_node() {
        let d = parse_artifact(ABSTAIN).unwrap();
        assert_eq!(d.summary.status, "abstain");
        let g = graph(
            &["prep", "ask", "fmt"],
            &[
                (START, "prep"),
                ("prep", "ask"),
                ("ask", "fmt"),
                ("fmt", END),
            ],
        );
        let v = build_view(&g, &d).unwrap();
        for n in v.nodes.iter().filter(|n| n.role == NodeRole::Node) {
            assert_eq!(n.status, Some(NodeStatus::Abstained), "{}", n.id);
        }
    }

    #[test]
    fn a_node_the_verdict_never_mentions_gets_no_claim() {
        let d = parse_artifact(TWO_CAUSE).unwrap();
        let g = graph(
            &[
                "router",
                "retriever",
                "extractor",
                "writer",
                "reviewer",
                "fallback",
            ],
            &[
                (START, "router"),
                ("router", "retriever"),
                ("retriever", "extractor"),
                ("extractor", "writer"),
                ("writer", "reviewer"),
                ("reviewer", END),
                ("router", "fallback"),
                ("fallback", END),
            ],
        );
        let v = build_view(&g, &d).unwrap();
        let f = node(&v, "fallback");
        assert_eq!(f.status, Some(NodeStatus::Unverified));
        assert!(f.reason.contains("not on the path"), "{}", f.reason);
    }

    #[test]
    fn a_verdict_node_missing_from_the_current_graph_is_kept_and_flagged() {
        let d = parse_artifact(TWO_CAUSE).unwrap();
        let g = graph(
            &["router", "retriever", "writer", "reviewer"],
            &[
                (START, "router"),
                ("router", "retriever"),
                ("retriever", "writer"),
                ("writer", "reviewer"),
                ("reviewer", END),
            ],
        );
        let v = build_view(&g, &d).unwrap();
        assert_eq!(node(&v, "extractor").status, Some(NodeStatus::Culprit));
        assert!(v.note.as_deref().unwrap().contains("extractor"));
    }

    #[test]
    fn layout_without_a_diagnosis_claims_nothing_and_reads_declared_kinds() {
        let mut g = vendor_graph();
        g["nodes"][1]["metadata"] = json!({"kind": "llm"});
        g["nodes"][2]["metadata"] = json!({"kind": "deterministic"});
        g["nodes"][3]["metadata"] = json!({"kind": "something else"});
        let v = layout(&g).unwrap();
        assert!(v.nodes.iter().all(|n| n.status.is_none()));
        assert!(v.edges.iter().all(|e| !e.on_path));
        assert_eq!(node(&v, "router").kind, Some(NodeKind::Llm));
        assert_eq!(node(&v, "retriever").kind, Some(NodeKind::Deterministic));
        assert_eq!(node(&v, "extractor").kind, None);
        assert_eq!(node(&v, "writer").kind, None);
        assert_eq!(node(&v, "writer").layer, 4);
    }

    #[test]
    fn handoffs_on_the_recorded_path_are_marked_and_untaken_ones_are_not() {
        let d = parse_artifact(TWO_CAUSE).unwrap();
        let g = graph(
            &[
                "router",
                "retriever",
                "extractor",
                "writer",
                "reviewer",
                "fallback",
            ],
            &[
                (START, "router"),
                ("router", "retriever"),
                ("retriever", "extractor"),
                ("extractor", "writer"),
                ("writer", "reviewer"),
                ("reviewer", END),
                ("router", "fallback"),
                ("fallback", END),
            ],
        );
        let v = build_view(&g, &d).unwrap();
        let on = |s: &str, t: &str| {
            v.edges
                .iter()
                .find(|e| e.source == s && e.target == t)
                .unwrap()
                .on_path
        };
        assert!(on(START, "router") && on("retriever", "extractor") && on("reviewer", END));
        assert!(!on("router", "fallback") && !on("fallback", END));
    }

    #[test]
    fn graph_for_team_fetches_the_assistant_graph_without_a_verdict() {
        let t = Fake {
            seen: RefCell::new(vec![]),
            graph: vendor_graph(),
        };
        let v = graph_for_team(&t, "a-vendor").unwrap();
        assert_eq!(t.seen.borrow().as_slice(), ["/assistants/a-vendor/graph"]);
        assert!(v.nodes.iter().all(|n| n.status.is_none()));
    }

    #[test]
    fn malformed_graph_is_an_error_not_an_empty_picture() {
        let d = parse_artifact(TWO_CAUSE).unwrap();
        assert!(build_view(&json!({"nodes": "x"}), &d).is_err());
        assert!(build_view(&json!({"nodes": [], "edges": []}), &d).is_err());
    }

    struct Fake {
        seen: RefCell<Vec<String>>,
        graph: Value,
    }

    impl LangGraphTransport for Fake {
        fn post_json(&self, path: &str, _body: Value) -> anyhow::Result<Value> {
            self.seen.borrow_mut().push(path.to_string());
            Ok(json!([
                {"assistant_id": "a-other", "graph_id": "invoice_pipeline"},
                {"assistant_id": "a-vendor", "graph_id": "vendor_brief"},
            ]))
        }
        fn get_json(&self, path: &str) -> anyhow::Result<Value> {
            self.seen.borrow_mut().push(path.to_string());
            Ok(self.graph.clone())
        }
    }

    #[test]
    fn fetches_the_graph_of_the_assistant_whose_graph_id_matches() {
        let d = parse_artifact(TWO_CAUSE).unwrap();
        assert_eq!(d.summary.graph_id.as_deref(), Some("vendor_brief"));
        let t = Fake {
            seen: RefCell::new(vec![]),
            graph: vendor_graph(),
        };
        let v = graph_for_diagnosis(&t, &d).unwrap();
        assert_eq!(node(&v, "retriever").status, Some(NodeStatus::Culprit));
        assert_eq!(
            t.seen.borrow().last().unwrap(),
            "/assistants/a-vendor/graph"
        );
    }

    #[test]
    fn no_matching_team_says_so() {
        let d = parse_artifact(&TWO_CAUSE.replace("vendor_brief", "gone_team")).unwrap();
        let t = Fake {
            seen: RefCell::new(vec![]),
            graph: vendor_graph(),
        };
        let err = graph_for_diagnosis(&t, &d).unwrap_err().to_string();
        assert!(err.contains("gone_team"), "{err}");
    }
}
