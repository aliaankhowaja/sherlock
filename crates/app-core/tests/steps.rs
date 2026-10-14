//! A recorded run replayed step by step, from the real two-cause vendor_brief history.

use app_core::ingestion::LangGraphTransport;
use app_core::steps::{Feed, clip, epoch_ms, fetch_run_steps, parse_steps};
use app_core::topology::{NodeKind, layout};
use serde_json::{Value, json};

fn history() -> Value {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../harness/fixtures/vendor_brief_two_cause_history.json"
    );
    serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap()
}

/// The vendor_brief topology as `GET /assistants/{id}/graph` returns it.
fn graph() -> Value {
    let chain = [
        "__start__",
        "router",
        "retriever",
        "extractor",
        "writer",
        "reviewer",
        "__end__",
    ];
    let kind = |id: &str| {
        if id == "writer" {
            "llm"
        } else {
            "deterministic"
        }
    };
    json!({
        "nodes": chain.iter().map(|id| json!({"id": id, "metadata": {"kind": kind(id)}})).collect::<Vec<_>>(),
        "edges": chain.windows(2).map(|w| json!({"source": w[0], "target": w[1]})).collect::<Vec<_>>(),
    })
}

#[test]
fn steps_come_oldest_first_one_per_node_run() {
    let r = parse_steps("t", &history(), None).unwrap();
    let nodes: Vec<&str> = r.steps.iter().map(|s| s.node.as_str()).collect();
    assert_eq!(
        nodes,
        [
            "__start__",
            "router",
            "retriever",
            "extractor",
            "writer",
            "reviewer"
        ]
    );
    let numbers: Vec<Option<i64>> = r.steps.iter().map(|s| s.step).collect();
    assert_eq!(numbers, (-1..=4).map(Some).collect::<Vec<_>>());
    assert_eq!(r.graph_id.as_deref(), Some("vendor_brief"));
    assert!(r.assistant_id.is_some() && r.final_state.contains_key("final_output"));
    assert!(
        r.steps
            .iter()
            .all(|s| s.checkpoint_id.is_some() && s.error.is_none())
    );
}

#[test]
fn each_output_becomes_the_next_step_input_and_names_who_fed_it() {
    let r = parse_steps("t", &history(), None).unwrap();
    let step = |n: &str| r.steps.iter().find(|s| s.node == n).unwrap();
    let (retriever, extractor) = (step("retriever"), step("extractor"));
    assert_eq!(retriever.output["documents"], extractor.input["documents"]);
    assert!(extractor.changed.contains(&"documents".to_string()));
    assert!(!extractor.changed.contains(&"vendor".to_string()));
    assert!(extractor.input_from.contains(&Feed {
        node: "__start__".into(),
        keys: vec!["vendor".into()]
    }));
    let from_retriever = extractor
        .input_from
        .iter()
        .find(|f| f.node == "retriever")
        .unwrap();
    assert!(from_retriever.keys.contains(&"documents".to_string()));
    assert!(step("router").input.contains_key("vendor"));
}

#[test]
fn log_lines_say_what_each_node_received_and_produced() {
    let r = parse_steps("t", &history(), None).unwrap();
    let retriever = r.steps.iter().find(|s| s.node == "retriever").unwrap();
    assert!(retriever.log[0].starts_with("retriever received "));
    assert!(retriever.log[0].contains("source=\"compliance_db\""));
    assert!(retriever.log[1].starts_with("retriever produced documents=[2 items]"));
    assert_eq!(r.steps[0].log, ["run started with vendor=\"acme\""]);
    assert!(
        r.steps
            .iter()
            .all(|s| s.duration_ms.is_some_and(|d| d >= 0))
    );
    assert!(retriever.started_at.is_some() && retriever.finished_at.is_some());
}

#[test]
fn with_the_topology_steps_carry_kinds_and_labelled_hand_offs() {
    let g = layout(&graph()).unwrap();
    let r = parse_steps("t", &history(), Some(&g)).unwrap();
    let writer = r.steps.iter().find(|s| s.node == "writer").unwrap();
    assert_eq!(writer.kind, Some(NodeKind::Llm));
    let pairs: Vec<(&str, &str)> = r
        .edges
        .iter()
        .map(|e| (e.source.as_str(), e.target.as_str()))
        .collect();
    assert_eq!(
        pairs,
        [
            ("__start__", "router"),
            ("router", "retriever"),
            ("retriever", "extractor"),
            ("extractor", "writer"),
            ("writer", "reviewer")
        ]
    );
    let handoff = r.edges.iter().find(|e| e.source == "retriever").unwrap();
    assert!(handoff.keys.contains(&"documents".to_string()));
}

#[test]
fn a_failed_node_shows_its_error_and_no_output() {
    let h = json!([
        {"values": {"q": "hi"}, "next": ["nurse"], "created_at": "2026-01-01T00:00:01Z",
         "checkpoint": {"checkpoint_id": "c1"}, "metadata": {"step": 1},
         "tasks": [{"name": "nurse", "error": "ValueError('boom')", "result": null}]}
    ]);
    let r = parse_steps("t", &h, None).unwrap();
    let s = &r.steps[0];
    assert_eq!(s.error.as_deref(), Some("ValueError('boom')"));
    assert!(s.output.is_null() && s.duration_ms.is_none());
    assert_eq!(s.log[1], "nurse failed: ValueError('boom')");
}

#[test]
fn long_values_are_capped_and_keep_their_shape() {
    let v = clip(&json!({"text": "x".repeat(1000), "docs": (0..50).collect::<Vec<_>>(), "n": 3}));
    assert_eq!(v["n"], 3);
    assert!(v["text"].as_str().unwrap().len() < 500);
    assert_eq!(v["docs"].as_array().unwrap().len(), 21);
    assert_eq!(v["docs"][20], "... (+30 more)");
}

#[test]
fn timestamps_parse_to_epoch_milliseconds() {
    assert_eq!(epoch_ms("1970-01-01T00:00:01Z"), Some(1000));
    assert_eq!(epoch_ms("1970-01-02T00:00:00+01:00"), Some(23 * 3_600_000));
    let a = epoch_ms("2026-10-13T17:37:45.790453+00:00").unwrap();
    let b = epoch_ms("2026-10-13T17:37:45.807331+00:00").unwrap();
    assert_eq!(b - a, 17);
    assert_eq!(epoch_ms("not a time"), None);
}

struct Fake {
    graph: Option<Value>,
}

impl LangGraphTransport for Fake {
    fn post_json(&self, path: &str, body: Value) -> anyhow::Result<Value> {
        assert!(path.ends_with("/history") && body["limit"].as_u64() >= Some(100));
        Ok(history())
    }
    fn get_json(&self, path: &str) -> anyhow::Result<Value> {
        assert!(path.starts_with("/assistants/") && path.ends_with("/graph"));
        self.graph
            .clone()
            .ok_or_else(|| anyhow::anyhow!("no graph"))
    }
}

#[test]
fn fetch_reads_the_topology_and_survives_without_it() {
    let with = fetch_run_steps(
        &Fake {
            graph: Some(graph()),
        },
        "t-1",
    )
    .unwrap();
    assert!(with.note.is_none() && with.steps.iter().any(|s| s.kind == Some(NodeKind::Llm)));
    let without = fetch_run_steps(&Fake { graph: None }, "t-1").unwrap();
    assert!(
        without
            .note
            .unwrap()
            .contains("could not read the team's graph")
    );
    assert!(without.steps.iter().all(|s| s.kind.is_none()) && without.steps.len() == 6);
    assert!(fetch_run_steps(&Fake { graph: None }, "../etc").is_err());
}
