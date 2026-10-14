//! What the web app may start: validated picks and the fixed `sherlock-rec` argv.

use app_core::ingestion::{Team, TeamRun};
use app_core::runner::{Pick, Project, display_command, validate_pick};
use serde_json::json;
use std::path::PathBuf;

fn teams() -> Vec<Team> {
    vec![Team {
        assistant_id: "a-1".into(),
        graph_id: "order_desk".into(),
        name: None,
    }]
}

fn run(id: &str, meta: serde_json::Value) -> TeamRun {
    TeamRun {
        thread_id: id.into(),
        status: Some("idle".into()),
        assistant_id: Some("a-1".into()),
        created_at: None,
        metadata: meta,
    }
}

fn runs() -> Vec<TeamRun> {
    vec![
        run("f-1", json!({})),
        run("g-1", json!({})),
        run("t-1", json!({"sherlock_fork_of": "f-1"})),
    ]
}

#[test]
fn a_pick_of_two_listed_runs_of_the_team_is_accepted() {
    let p = validate_pick(&teams(), &runs(), "a-1", "f-1", "g-1").unwrap();
    assert_eq!(
        p,
        Pick {
            graph_id: "order_desk".into(),
            failed: "f-1".into(),
            good: "g-1".into()
        }
    );
}

#[test]
fn bad_or_unknown_ids_are_rejected_before_anything_runs() {
    let t = teams();
    let r = runs();
    let rejects = [
        ("a-1", "f-1; rm -rf /", "g-1"),
        ("a-1", "--url=http://evil", "g-1"),
        ("a-1", "../../etc", "g-1"),
        ("a-1", "", "g-1"),
        ("a-2", "f-1", "g-1"),
        ("a-1", "nope", "g-1"),
        ("a-1", "f-1", "f-1"),
        ("a-1", "t-1", "g-1"),
        ("a-1", "f-1", "t-1"),
    ];
    for (team, failed, good) in rejects {
        assert!(
            validate_pick(&t, &r, team, failed, good).is_err(),
            "{team} {failed} {good}"
        );
    }
}

fn project(dir: &std::path::Path) -> Project {
    Project {
        dir: dir.to_path_buf(),
        program: "sherlock-rec".into(),
        langgraph_url: "http://127.0.0.1:2024".into(),
        sherlock_dir: PathBuf::from("out"),
    }
}

fn temp(name: &str) -> PathBuf {
    let d = std::env::temp_dir().join(format!("sherlock-runner-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(d.join("checks")).unwrap();
    std::fs::create_dir_all(d.join(".sherlock")).unwrap();
    d
}

#[test]
fn argv_is_fixed_and_uses_the_team_check_and_node_map() {
    let d = temp("argv");
    std::fs::write(d.join("checks/order_desk.yaml"), "assert: []").unwrap();
    std::fs::write(d.join("checks/order_desk.node-map.json"), "{}").unwrap();
    let p = project(&d);
    let pick = validate_pick(&teams(), &runs(), "a-1", "f-1", "g-1").unwrap();
    let argv = p.diagnose_argv(&pick).unwrap();
    assert_eq!(
        argv[..5],
        [
            "sherlock-rec",
            "diagnose",
            "--progress",
            "--thread-id",
            "f-1"
        ]
    );
    assert_eq!(argv[5..7], ["--good-run", "g-1"]);
    let at = |flag: &str| argv[argv.iter().position(|a| a == flag).unwrap() + 1].clone();
    assert_eq!(at("--url"), "http://127.0.0.1:2024");
    assert!(at("-c").ends_with("order_desk.yaml"));
    assert!(at("--node-map").ends_with("order_desk.node-map.json"));
    assert!(at("--cassette").ends_with("cassette.db"));
    assert_eq!(at("--out"), "out");
    let o = p.outcomes_argv("order_desk").unwrap();
    assert_eq!(
        o[..4],
        ["sherlock-rec", "outcomes", "--graph-id", "order_desk"]
    );
    assert!(p.outcomes_argv("../x").is_err());
}

#[test]
fn a_shared_sherlock_yaml_is_the_fallback_and_missing_files_are_named() {
    let d = temp("fallback");
    let p = project(&d);
    let problems = p.problems("order_desk");
    assert_eq!(problems.len(), 2, "{problems:?}");
    assert!(
        problems[0].contains("no recording") && problems[1].contains("no check for order_desk")
    );
    std::fs::write(d.join("sherlock.yaml"), "assert: []").unwrap();
    std::fs::write(d.join(".sherlock/cassette.db"), "").unwrap();
    assert!(p.problems("order_desk").is_empty());
    assert!(
        p.check_file("order_desk")
            .unwrap()
            .ends_with("sherlock.yaml")
    );
    assert_eq!(p.node_map_file("order_desk"), None);
}

#[test]
fn display_command_quotes_only_what_needs_it() {
    let argv: Vec<String> = [
        "sherlock-rec",
        "-c",
        "C:/My Project/x.yaml",
        "--url",
        "http://h:1",
    ]
    .iter()
    .map(|s| s.to_string())
    .collect();
    assert_eq!(
        display_command(&argv),
        "sherlock-rec -c \"C:/My Project/x.yaml\" --url http://h:1"
    );
}

#[test]
fn the_demo_lab_and_a_plain_project_are_discovered_from_the_sherlock_dir() {
    let demo = temp("discover-demo");
    std::fs::create_dir_all(demo.join("lab").join(".sherlock")).unwrap();
    std::fs::write(demo.join("lab").join(".sherlock").join("cassette.db"), b"").unwrap();
    assert_eq!(Project::discover(&demo), Some(demo.join("lab")));
    let plain = temp("discover-plain");
    std::fs::create_dir_all(plain.join(".sherlock")).unwrap();
    std::fs::write(plain.join(".sherlock").join("cassette.db"), b"").unwrap();
    assert_eq!(
        Project::discover(&plain.join(".sherlock")),
        Some(plain.clone())
    );
    assert_eq!(Project::discover(&temp("discover-none")), None);
}

#[test]
fn the_intake_argv_is_fixed_and_carries_free_text_as_single_arguments() {
    let p = Project {
        dir: PathBuf::from("/p"),
        program: "sherlock-rec".into(),
        langgraph_url: "http://x".into(),
        sherlock_dir: PathBuf::from("/out"),
    };
    let argv = p
        .intake_argv("f-1", Some("a; rm -rf /"), Some("wrong total"))
        .unwrap();
    assert_eq!(
        argv,
        [
            "sherlock-rec",
            "intake",
            "--thread-id",
            "f-1",
            "--dir",
            "/out",
            "--expected",
            "a; rm -rf /",
            "--note",
            "wrong total"
        ]
    );
    assert_eq!(p.intake_argv("f-1", None, None).unwrap().len(), 6);
    assert!(p.intake_argv("../x", None, None).is_err());
    assert!(p.intake_argv("f-1", Some(&"x".repeat(5000)), None).is_err());
}
