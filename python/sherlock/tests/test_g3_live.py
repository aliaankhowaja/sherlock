"""Phase 2 exit criterion, live: G3 against a real `langgraph dev` (spec FR-G3.1-G3.8, section 8).

Each lab runs the real workflow:
  1. `sherlock-rec run langgraph dev` records the failed runs (the stub is the only "provider");
  2. the server stops and the stub goes away;
  3. `sherlock-rec run --replay langgraph dev` restarts on the same persisted threads, wrapped in
     a socket trap that forbids every non-loopback connection and the stub's port;
  4. G3 forks the recorded threads over HTTP and resumes them from the cassette.
No real provider is ever called. Skipped when langgraph-cli is not installed.
"""

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from stub_server import StubServer

pytest.importorskip("langgraph_cli")

from sherlock.cassette import Cassette  # noqa: E402
from sherlock.checks import Checks, load_checks  # noqa: E402
from sherlock.diagnose import diagnose  # noqa: E402
from sherlock.g3 import Client, load_known_good, run_g3  # noqa: E402
from sherlock.search import Budget  # noqa: E402

TESTS = Path(__file__).parent
REPO = TESTS.parents[2]
HARNESS = REPO / "harness"
LAUNCHER = "from langgraph_cli.cli import cli; cli()"
QUESTION = "what is the vendor status"
LLM_CHECK = Checks([{"type": "contains", "value": f"ANSWER: echo: {QUESTION}"}], "final_output", TESTS, TESTS / "x.yaml")
LLM_KNOWN_GOOD = {"prep": {"faults": {"$remove": ["prep.truncate"]}}, "ask": {}, "fmt": {"faults": {"$remove": ["fmt.shout"]}}}


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http(base, method, path, body=None):
    req = urllib.request.Request(base + path, method=method, headers={"Content-Type": "application/json"},
                                 data=None if body is None else json.dumps(body).encode())
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read() or b"null")


class Server:
    def __init__(self, work, *, replay, cassette, stub_port, log):
        self.port, self.work = free_port(), work
        self.url = f"http://127.0.0.1:{self.port}"
        inner = [sys.executable, "-c", LAUNCHER, "dev", "--no-browser", "--no-reload", "--port", str(self.port)]
        if replay:  # the socket trap sits inside the replay process: it must never reach the network
            inner = [sys.executable, str(TESTS / "no_net.py"), str(stub_port), str(work / "launcher.py"), *inner[3:]]
        cmd = [sys.executable, "-m", "sherlock", "run", *(["--replay"] if replay else []),
               "--cassette", str(cassette), "--", *inner]
        env = {**os.environ, "LANGGRAPH_CLI_NO_ANALYTICS": "1", "STUB_URL": f"http://127.0.0.1:{stub_port}",
               "NO_NET_MARKER": str(work / "net_attempts.txt"), "PYTHONPATH": str(TESTS.parent / "src")}
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        self.proc = subprocess.Popen(cmd, cwd=work, env=env, stdout=open(log, "w"), stderr=subprocess.STDOUT,
                                     creationflags=flags)
        for _ in range(120):
            try:
                urllib.request.urlopen(self.url + "/ok", timeout=1)
                return
            except Exception:
                if self.proc.poll() is not None:
                    raise RuntimeError(f"server exited early, see {log}")
                time.sleep(1)
        self.stop()
        raise RuntimeError(f"server did not start, see {log}")

    def stop(self):
        if self.proc.poll() is None:  # graceful, so the in-memory server flushes its threads to disk
            self.proc.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
            try:
                self.proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                subprocess.call(["taskkill", "/PID", str(self.proc.pid), "/F", "/T"]) if os.name == "nt" \
                    else self.proc.kill()
                self.proc.wait()
        time.sleep(1)


def make_lab(tmp_path_factory, name, failed_runs):
    """Record `failed_runs` ([(graph, input, faults)]) then restart in replay mode. Returns the lab dict."""
    work = tmp_path_factory.mktemp(name)
    shutil.copytree(HARNESS / "sherlock_harness", work / "sherlock_harness", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(HARNESS / "pyproject.toml", work / "pyproject.toml")
    shutil.copy(TESTS / "g3_team" / "llm_graph.py", work / "llm_graph.py")
    (work / "launcher.py").write_text(LAUNCHER + "\n")
    (work / "langgraph.json").write_text(json.dumps({"dependencies": ["."], "graphs": {
        "vendor_brief": "./sherlock_harness/teams/vendor_brief.py:graph", "llm_brief": "./llm_graph.py:graph"}}))
    cassette = work / ".sherlock" / "cassette.db"
    stub = StubServer().start()
    recorder = Server(work, replay=False, cassette=cassette, stub_port=stub.port, log=work / "record.log")
    threads = {}
    try:
        for key, graph, payload, faults in failed_runs:
            tid = http(recorder.url, "POST", "/threads", {"metadata": {"assistant_id": graph}})["thread_id"]
            http(recorder.url, "POST", f"/threads/{tid}/runs/wait",
                 {"assistant_id": graph, "input": payload, "context": {"faults": faults}, "durability": "sync"})
            threads[key] = tid
    finally:
        recorder.stop()
        stub.stop()  # the provider is gone from here on
    server = Server(work, replay=True, cassette=cassette, stub_port=stub.port, log=work / "replay.log")
    lab = dict(work=work, url=server.url, client=Client(server.url), cassette=cassette, threads=threads)
    yield lab
    server.stop()
    assert not (work / "net_attempts.txt").exists(), "the replay server tried to open a connection"


@pytest.fixture(scope="module")
def team1(tmp_path_factory):
    yield from make_lab(tmp_path_factory, "team1", [
        ("single", "vendor_brief", {"vendor": "acme"}, ["extractor.legacy_pattern"]),
        ("two", "vendor_brief", {"vendor": "acme"}, ["retriever.drop_latest", "extractor.legacy_pattern"]),
        ("llm", "llm_brief", {"question": QUESTION}, ["fmt.shout"]),
        ("harmless", "vendor_brief", {"vendor": "acme"}, ["retriever.reverse_order"]),
        ("writer", "vendor_brief", {"vendor": "acme"}, ["writer.stale_template"]),
    ])


@pytest.fixture(scope="module")
def llm_miss(tmp_path_factory):
    yield from make_lab(tmp_path_factory, "llmmiss", [
        ("both", "llm_brief", {"question": QUESTION}, ["prep.truncate", "fmt.shout"])])


@pytest.fixture(scope="module")
def z1():
    return load_checks(HARNESS / "sherlock.yaml")


@pytest.fixture(scope="module")
def good1():
    return load_known_good(HARNESS / "known_good" / "vendor_brief.json")


def g3(lab, key, restore, known_good, checks):
    return run_g3(lab["client"], lab["threads"][key], restore, known_good, checks, lab["cassette"])


def test_single_fault_restoring_the_faulty_node_passes(team1, z1, good1):
    before = [s["checkpoint"]["checkpoint_id"] for s in http(team1["url"], "POST", f"/threads/{team1['threads']['single']}/history", {"limit": 100})]
    v = g3(team1, "single", ["extractor"], good1, z1)
    assert v.verdict == "pass", v
    assert v.fork_node == "extractor" and v.fork_thread != team1["threads"]["single"]
    assert v.evidence["context"] == {"faults": []} and "extractor" in v.evidence["nodes_rerun"]
    assert "retriever" not in v.evidence["nodes_rerun"]  # upstream nodes are not re-run
    after = [s["checkpoint"]["checkpoint_id"] for s in http(team1["url"], "POST", f"/threads/{team1['threads']['single']}/history", {"limit": 100})]
    assert before == after  # the original thread is untouched


@pytest.mark.parametrize("node", ["router", "retriever", "writer", "reviewer"])
def test_single_fault_restoring_a_non_culprit_fails(team1, z1, good1, node):
    v = g3(team1, "single", [node], good1, z1)
    assert v.verdict == "fail", v
    assert "SOC 2" in v.reason and v.check["pass"] is False


def test_superset_passes_and_trials_are_repeatable(team1, z1, good1):
    assert [g3(team1, "single", ["router", "extractor"], good1, z1).verdict for _ in range(2)] == ["pass", "pass"]


def test_two_cause_run_needs_both_nodes(team1, z1, good1):
    assert g3(team1, "two", ["retriever"], good1, z1).verdict == "fail"
    assert g3(team1, "two", ["extractor"], good1, z1).verdict == "fail"
    both = g3(team1, "two", ["extractor", "retriever"], good1, z1)
    assert both.verdict == "pass" and both.fork_node == "retriever"


def test_llm_node_downstream_is_served_from_the_cassette(team1):
    ok = g3(team1, "llm", ["fmt"], LLM_KNOWN_GOOD, LLM_CHECK)
    assert ok.verdict == "pass", ok
    for _ in range(2):  # re-running the LLM node twice: the recording is handed out afresh each trial
        again = g3(team1, "llm", ["prep"], LLM_KNOWN_GOOD, LLM_CHECK)
        assert again.verdict == "fail" and "nodes_rerun" in again.evidence and "ask" in again.evidence["nodes_rerun"]
    assert Cassette(team1["cassette"]).abstains() == []


def test_cassette_miss_abstains_and_never_goes_live(llm_miss):
    v = g3(llm_miss, "both", ["prep"], LLM_KNOWN_GOOD, LLM_CHECK)
    assert v.verdict == "abstain" and "request changed since recording" in v.reason and v.check is None
    assert any("request changed" in r for r in Cassette(llm_miss["cassette"]).abstains())
    # a restore that leaves the LLM request unchanged is still served and gets a real verdict
    unchanged = g3(llm_miss, "both", ["fmt"], LLM_KNOWN_GOOD, LLM_CHECK)
    assert unchanged.verdict == "fail", unchanged
    assert g3(llm_miss, "both", ["prep", "fmt"], LLM_KNOWN_GOOD, LLM_CHECK).verdict == "abstain"


def test_cli_exit_codes_end_to_end(team1, llm_miss, tmp_path):
    def cli(lab, key, restore, *extra):
        return subprocess.run(
            [sys.executable, "-m", "sherlock", "g3", "--url", lab["url"], "--thread-id", lab["threads"][key],
             "--restore", restore, "--cassette", str(lab["cassette"]), *extra],
            capture_output=True, text=True, cwd=tmp_path)

    z, kg = ["-c", str(HARNESS / "sherlock.yaml")], ["--known-good", str(HARNESS / "known_good" / "vendor_brief.json")]
    ok = cli(team1, "single", "extractor", *z, *kg)
    assert ok.returncode == 0 and json.loads(ok.stdout)["verdict"] == "pass", ok.stderr
    assert cli(team1, "single", "writer", *z, *kg).returncode == 1
    llm_kg = tmp_path / "kg.json"
    llm_kg.write_text(json.dumps(LLM_KNOWN_GOOD))
    llm_z = tmp_path / "sherlock.yaml"
    llm_z.write_text(f"assert:\n  - type: contains\n    value: 'ANSWER: echo: {QUESTION}'\n")
    miss = cli(llm_miss, "both", "prep", "-c", str(llm_z), "--known-good", str(llm_kg))
    assert miss.returncode == 75 and "cannot say" in miss.stderr
    assert cli(team1, "single", "extractor", "-c", str(llm_z), "--known-good", str(tmp_path / "nope.json")).returncode == 2


# --- Phase 3 exit criterion: diagnose on demo team #1 (FR-D1-D9, FR-E3) ----------------------------

def gold(faults):
    """Gold minimal sets from the harness, derived by restoring subsets (FR-E3), never from fault names."""
    sys.path.insert(0, str(HARNESS))
    from sherlock_harness.faults import gold_minimal_sets
    return {frozenset(s) for s in gold_minimal_sets(faults)}


def dx(lab, key, known_good, checks, **budget):
    return diagnose(lab["client"], lab["threads"][key], known_good, checks, lab["cassette"], Budget(**budget))


def found(result):
    return {frozenset(s) for s in result["minimal_sets"]}


def test_diagnose_single_fault_matches_gold(team1, z1, good1):
    r = dx(team1, "single", good1, z1)
    assert r["status"] == "found" and found(r) == gold(["extractor.legacy_pattern"]) == {frozenset({"extractor"})}
    assert r["counts"]["total"] == 1 and r["pruning"]["candidates"] == ["extractor"]
    assert r["trial_reduction"]["exhaustive_trials"] == 31 and r["trial_reduction"]["fewer_pct"] >= 40
    assert r["complete"] is True


def test_diagnose_two_cause_returns_the_pair_and_no_singleton(team1, z1, good1):
    r = dx(team1, "two", good1, z1)
    both = ["retriever.drop_latest", "extractor.legacy_pattern"]
    assert r["status"] == "found" and found(r) == gold(both) == {frozenset({"retriever", "extractor"})}
    by = {tuple(t["restored"]): t["verdict"] for t in r["trials"]}
    assert by[("retriever",)] == by[("extractor",)] == "fail" and by[("retriever", "extractor")] == "pass"
    assert r["counts"]["total"] == 3 and r["trial_reduction"]["fewer_pct"] >= 90
    assert Cassette(team1["cassette"]).abstains() == []


def test_diagnose_single_writer_fault_matches_gold(team1, z1, good1):
    r = dx(team1, "writer", good1, z1)
    assert found(r) == gold(["writer.stale_template"]) == {frozenset({"writer"})}


def test_diagnose_harmless_fault_has_nothing_to_diagnose(team1, z1, good1):
    r = dx(team1, "harmless", good1, z1)
    assert r["status"] == "abstain" and r["reason_code"] == "already_passes" and r["trials"] == []
    assert gold(["retriever.reverse_order"]) == set()


def test_diagnose_llm_node_downstream_is_served_from_the_cassette(team1):
    z = LLM_CHECK
    r = dx(team1, "llm", LLM_KNOWN_GOOD, z)
    assert r["status"] == "found" and found(r) == {frozenset({"fmt"})}


def test_diagnose_cache_miss_abstains_with_a_reason(llm_miss):
    r = dx(llm_miss, "both", LLM_KNOWN_GOOD, LLM_CHECK)
    assert r["status"] == "abstain" and r["reason_code"] == "unrecorded_call" and r["minimal_sets"] == []
    assert "request changed since recording" in r["reason"]
    assert r["counts"]["cannot_say"] >= 1 and r["counts"]["total"] <= 40


def test_diagnose_stays_within_the_trial_budget(team1, z1, good1):
    r = dx(team1, "two", good1, z1, max_trials=2)
    assert r["status"] == "abstain" and r["reason_code"] == "budget_exhausted" and r["counts"]["total"] == 2


def test_diagnose_cli_writes_the_artifact_and_exits_by_result(team1, llm_miss, tmp_path):
    def cli(lab, key, kg, z, *extra):
        out = tmp_path / lab["work"].name
        proc = subprocess.run(
            [sys.executable, "-m", "sherlock", "diagnose", "--url", lab["url"], "--thread-id", lab["threads"][key],
             "--cassette", str(lab["cassette"]), "--known-good", str(kg), "-c", str(z), "--out", str(out), *extra],
            capture_output=True, text=True, cwd=tmp_path)
        return proc, out / "diagnoses" / f"{lab['threads'][key]}.json"

    proc, artifact = cli(team1, "two", HARNESS / "known_good" / "vendor_brief.json", HARNESS / "sherlock.yaml")
    assert proc.returncode == 0, proc.stderr
    assert json.loads(artifact.read_text()) == json.loads(proc.stdout)
    assert json.loads(proc.stdout)["minimal_sets"] == [["retriever", "extractor"]]
    llm_kg, llm_z = tmp_path / "kg.json", tmp_path / "sherlock.yaml"
    llm_kg.write_text(json.dumps(LLM_KNOWN_GOOD))
    llm_z.write_text(f"assert:\n  - type: contains\n    value: 'ANSWER: echo: {QUESTION}'\n")
    miss, artifact = cli(llm_miss, "both", llm_kg, llm_z)
    assert miss.returncode == 75 and artifact.exists(), miss.stderr
    assert json.loads(artifact.read_text())["status"] == "abstain"
    assert cli(team1, "two", tmp_path / "nope.json", HARNESS / "sherlock.yaml")[0].returncode == 2
