//! Runs one job's fixed argv (program + arguments, no shell) and feeds its stderr lines into the
//! job board as they arrive. stdout is discarded: `--progress` events and errors come on stderr.

use crate::run::{JOB_TIMEOUT_SECS, now_ms};
use app_core::jobs::Board;
use std::process::Stdio;
use std::sync::{Arc, Mutex};
use tokio::io::{AsyncBufReadExt, BufReader};

fn with_job(board: &Mutex<Board>, id: u64, f: impl FnOnce(&mut app_core::jobs::Job)) {
    if let Some(job) = board.lock().expect("job board lock").get_mut(id) {
        f(job);
    }
}

pub(crate) fn run_job(board: Arc<Mutex<Board>>, id: u64, argv: Vec<String>) {
    let Some((program, args)) = argv.split_first() else {
        with_job(&board, id, |j| {
            j.failed_to_start("empty command".into(), now_ms())
        });
        return;
    };
    let child = tokio::process::Command::new(program)
        .args(args)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::piped())
        .kill_on_drop(true)
        .spawn();
    let mut child = match child {
        Ok(c) => c,
        Err(e) => {
            let why =
                format!("could not start `{program}`: {e} (pass --sherlock-rec PATH to serve)");
            with_job(&board, id, |j| j.failed_to_start(why, now_ms()));
            return;
        }
    };
    let stderr = child.stderr.take();
    tokio::spawn(async move {
        let work = async {
            if let Some(stderr) = stderr {
                let mut lines = BufReader::new(stderr).lines();
                while let Ok(Some(line)) = lines.next_line().await {
                    with_job(&board, id, |j| j.on_line(&line, now_ms()));
                }
            }
            child.wait().await
        };
        let limit = std::time::Duration::from_secs(JOB_TIMEOUT_SECS);
        let code = match tokio::time::timeout(limit, work).await {
            Ok(Ok(status)) => status.code(),
            Ok(Err(_)) | Err(_) => None,
        };
        with_job(&board, id, |j| j.finish(code, now_ms()));
    });
}
