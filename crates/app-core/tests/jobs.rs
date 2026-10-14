//! A diagnosis job as the page sees it: events from `--progress`, log lines, and the end state.

use app_core::jobs::{Job, JobState};
use app_core::runner::Pick;

fn job() -> Job {
    let pick = Pick {
        graph_id: "order_desk".into(),
        failed: "f".into(),
        good: "g".into(),
    };
    Job::new(1, &pick, "sherlock-rec diagnose ...".into(), 1000)
}

#[test]
fn json_lines_become_events_and_other_lines_the_log() {
    let mut j = job();
    j.on_line(r#"{"event": "start", "thread_id": "f"}"#, 1200);
    j.on_line("sherlock-rec: something plain", 1300);
    j.on_line(r#"{"no_event": 1}"#, 1300);
    j.on_line("   ", 1300);
    assert_eq!(j.events.len(), 1);
    assert_eq!(j.events[0]["event"], "start");
    assert_eq!(j.events[0]["at_ms"], 200);
    assert_eq!(
        j.log,
        ["sherlock-rec: something plain", r#"{"no_event": 1}"#]
    );
    assert_eq!(j.state, JobState::Running);
}

#[test]
fn found_or_cannot_say_with_a_done_event_is_done() {
    for code in [0, 75] {
        let mut j = job();
        j.on_line(r#"{"event": "done", "status": "found"}"#, 1100);
        j.finish(Some(code), 2000);
        assert_eq!(j.state, JobState::Done, "{code}");
        assert_eq!(j.finished_ms, Some(2000));
    }
}

#[test]
fn an_error_exit_is_failed_with_the_last_log_line_as_the_reason() {
    let mut j = job();
    j.on_line("sherlock-rec: no replay session on this cassette", 1100);
    j.finish(Some(2), 2000);
    assert_eq!(j.state, JobState::Failed);
    assert_eq!(
        j.error.as_deref(),
        Some("no replay session on this cassette")
    );
}

#[test]
fn a_clean_exit_without_a_done_event_is_not_trusted() {
    let mut j = job();
    j.finish(Some(0), 2000);
    assert_eq!(j.state, JobState::Failed);
    assert!(j.error.as_deref().unwrap().contains("code 0"));
    let mut k = job();
    k.finish(None, 2000);
    assert!(k.error.as_deref().unwrap().contains("stopped"));
}

#[test]
fn a_process_that_cannot_start_says_why() {
    let mut j = job();
    j.failed_to_start("program not found".into(), 1001);
    assert_eq!(j.state, JobState::Failed);
    assert_eq!(j.error.as_deref(), Some("program not found"));
}
