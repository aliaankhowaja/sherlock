"""Converted AEGIS and Who&When Pro traces match the history Sherlock already parses.

The five source rows are real lines from the pinned snapshots. `histories.jsonl` is what
`parse_run_logs` reads in the app-core test `fetch_run_logs_reads_converted_public_traces`.
Single-speaker traces, including smolagents and alfagent, are not records.
"""

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

import convert_public_traces as convert
import public_g1
from g1_eval import Oracle
from sherlock.cassette import Cassette
from sherlock.checks import Checks
from sherlock.diagnose import diagnose
from sherlock.g1 import node_card
from sherlock.g3 import history_usable
from sherlock.search import Budget

FIXTURE = Path(__file__).parent / "fixtures" / "public_traces"
SOURCES = FIXTURE / "sources.jsonl"
HISTORIES = FIXTURE / "histories.jsonl"


def _names(record):
    return [task["name"] for snap in reversed(record["history"]) for task in snap["tasks"]]


def _load():
    sources = list(convert.iter_jsonl(SOURCES))
    records = []
    for row in sources:
        record, reason = convert.convert_row(row)
        assert reason is None, reason
        assert convert.shape_errors(record) == []
        records.append(record)
    golden = [json.loads(line) for line in HISTORIES.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert records == golden
    return sources, records


def test_fixture_keeps_five_multi_agent_pipelines():
    sources, records = _load()
    assert [row["id"] for row in sources] == [record["id"] for record in records]
    assert len(records) == 5
    for record in records:
        assert Oracle(record["gold"]).planted == [frozenset(record["gold"][0])]
        assert len(set(_names(record))) >= 2
        assert not set(_names(record)) & convert.NOT_NODES
        assert record["history"][0]["next"] == []
        for snap in record["history"][1:]:
            assert snap["next"] == [snap["tasks"][0]["name"]]
        assert history_usable(record["history"]) is None


def test_agentverse_answer_is_the_last_utterance():
    sources, records = _load()
    record = records[0]
    assert record["source"] == "aegis" and record["framework"] == "agentverse"
    assert record["gold"] == [["Evaluator", "RoleAssigner", "Solver"]]
    assert record["reference"] == "420"
    assert record["label_step"] is None and record["tags"] == []
    names = _names(record)
    assert names[0] == "RoleAssigner" and names[-1] == "Evaluator"
    last = record["history"][1]["tasks"][0]["result"]
    assert last["text"] == last["final_output"] == record["history"][0]["values"]["final_output"]
    assert "num_agents" not in record


def test_smoagents_drops_user_and_system():
    _sources, records = _load()
    record = records[1]
    names = _names(record)
    assert record["framework"] == "smoagents"
    assert record["gold"] == [["Searcher"]]
    assert names[0] == "Manager"
    assert set(names) == {"Manager", "Searcher"}
    assert "User" not in names and "System" not in names


def test_debate_gold_comes_from_agents_and_final_answer_differs():
    sources, records = _load()
    row, record = sources[2], records[2]
    ground = json.loads(row["ground_truth"])
    trajectory = json.loads(row["trajectory"])
    assert record["framework"] == "debate" and record["tags"] == []
    assert record["gold"] == [ground["agents"]] == [["agent_1"]]
    assert record["label_step"] == {"round": ground["round"]}
    assert "mode" not in record["label_step"]
    final = next(item["content"] for item in trajectory if item.get("kind") == "final_answer")
    last_text = next(item["turns"][-1]["output"] for item in reversed(trajectory) if item.get("turns"))
    assert final == "D" and last_text != final
    last = record["history"][1]["tasks"][0]["result"]
    assert last["text"] == last_text
    assert last["final_output"] == record["history"][0]["values"]["final_output"] == final
    assert all(item.get("kind") != "round" or "agent" not in item for item in trajectory)


def test_macnet_keeps_one_node_for_critic_and_rewriter():
    sources, records = _load()
    row, record = sources[3], records[3]
    trajectory = json.loads(row["trajectory"])
    roles = [item.get("role") for item in trajectory if item.get("agent_id") == "node_1"]
    assert roles == ["critic", "rewriter"]
    names = _names(record)
    assert names.count("node_1") == 2
    assert "critic" not in names and "rewriter" not in names
    assert record["gold"] == [["node_0"]]
    assert record["label_step"] == {"round": 0, "position": 0}
    assert "node_out" in names


def test_mathchat_is_tagged_two_role_and_left_out_of_the_means():
    _sources, records = _load()
    record = records[4]
    assert record["framework"] == "mathchat" and record["tags"] == ["two_role"]
    assert set(_names(record)) == {"user_proxy", "assistant"}
    assert record["gold"] == [["assistant"]]
    headline = [row for row in records if "two_role" not in row["tags"]]
    appendix = [row for row in records if "two_role" in row["tags"]]
    report = public_g1.evaluate(headline, appendix, "fake", 1)
    assert report["methods"]["path"]["rows"] == 4
    assert all(row["framework"] != "mathchat" for row in report["rows"])
    assert report["two_role"] == {"rows": 1, "node_names": ["assistant", "user_proxy"]}
    assert report["g0_only"]["one name"]["rows"] == 3
    assert report["g0_only"]["several names"]["rows"] == 1
    text = public_g1.render(report)
    assert text.startswith("# Public-trace ordering")
    assert report["intro"] in text
    for word in ("rank", "reciprocal rank", "recall@3", "ndcg@3", "trials_to_label", "name in label", "Jaccard"):
        assert word in text
    for method in report["methods"].values():
        assert method["trials_to_label"] is not None and method["no_trial"] == 0


def test_cards_do_not_see_a_passing_run_or_the_culprit_names():
    _sources, records = _load()
    record = records[0]
    card, _truncated = node_card("Solver", record["history"], None, public_g1._checks(record))
    assert "output_same_as_good=unknown" in card
    assert "input_same_as_good=unknown" in card
    assert "DIFF:" not in card
    assert "is_injected" not in card and "injected_agents" not in card


def test_scoring_script_does_not_grade_a_restored_set():
    text = (ROOT / "eval" / "public_g1.py").read_text(encoding="utf-8")
    assert "evaluation.score" not in text
    assert "minimal_sets" not in text


def test_single_agent_transcripts_are_dropped():
    smol = {
        "id": "solo", "framework": "smolagents",
        "ground_truth": json.dumps({"agent": None, "step": 2}),
        "trajectory": json.dumps([
            {"kind": "user", "content": "question"},
            {"kind": "action", "reasoning": "think", "observation": "saw"},
            {"kind": "action", "reasoning": "again", "observation": "done"},
        ]),
    }
    record, reason = convert.convert_whowhen(smol)
    assert record is None and reason == "single_agent"
    alf = dict(smol, id="alf", framework="alfagent")
    record, reason = convert.convert_whowhen(alf)
    assert record is None and reason == "single_agent"
    one = {
        "id": "one", "framework": "magentic-one",
        "ground_truth": json.dumps({"agent": "coder", "step": 1}),
        "trajectory": json.dumps([
            {"kind": "user", "content": "question"},
            {"kind": "agent", "agent": "coder", "role": "Coder", "output": "42"},
            {"kind": "agent", "agent": "coder", "role": "Coder", "output": "42"},
        ]),
    }
    record, reason = convert.convert_whowhen(one)
    assert record is None and reason == "one_speaker"


def test_num_agents_is_ignored_and_a_matching_answer_is_dropped():
    kept = {
        "id": "dylan-1",
        "metadata": {"framework": "dylan", "num_agents": 1},
        "input": {"query": "2+2", "conversation_history": [
            {"agent_name": "Assistant1", "content": "maybe 4", "phase": "reasoning", "step": 1},
            {"agent_name": "Assistant2", "content": "I agree it is 4", "phase": "reasoning", "step": 2,
             "is_injected": True},
        ]},
        "ground_truth": {"correct_answer": "#### 5", "injected_agents": [
            {"agent_name": "Assistant2", "error_type": "x", "injection_strategy": "y",
             "malicious_action_description": "hide"},
        ]},
    }
    record, reason = convert.convert_aegis(kept)
    assert reason is None
    assert _names(record) == ["Assistant1", "Assistant2"]
    assert record["reference"] == "5"
    assert convert.shape_errors(record) == []
    blob = json.dumps(record["history"])
    assert "is_injected" not in blob and "error_type" not in blob and "hide" not in blob
    dropped = json.loads(json.dumps(kept))
    dropped["input"]["conversation_history"][1]["content"] = "5"
    record, reason = convert.convert_aegis(dropped)
    assert record is None and reason == "already_matches"


class _Replay:
    """The trial passes when the restored names cover the published label. There is no graph to resume."""

    def __init__(self, history, gold, reference):
        self.original, self.gold, self.reference = history, set(gold), reference
        self.wrong = history[0]["values"]["final_output"]
        self.steps, self.ran, self.context = None, False, None

    def _fork_history(self):
        chrono = copy.deepcopy(list(reversed(self.original)))
        for snap in chrono:
            snap["checkpoint"]["checkpoint_id"] += "-fork"
        keep = len(self.steps) + 1 if not self.ran else len(chrono)
        return list(reversed(chrono[:keep]))

    def request(self, method, path, body=None):
        if path == "/threads/T":
            return {"metadata": {"graph_id": "public"}}
        if path == "/threads/T/history":
            return self.original
        if path.startswith("/threads/T/runs/"):
            return {"kwargs": {"context": {"seen": []}}}
        if (method, path) == ("POST", "/threads"):
            self.steps, self.ran = body["supersteps"], False
            return {"thread_id": "F"}
        if path == "/threads/F/history":
            return self._fork_history()
        if path == "/threads/F/runs/wait":
            self.ran, self.context = True, body["context"]
            seen = set(self.context.get("seen") or [])
            return {"final_output": self.reference if self.gold <= seen else self.wrong}
        if path == "/threads/F/runs":
            return [{"kwargs": {"context": self.context}}]
        raise AssertionError(f"unexpected {method} {path}")


def _diagnose(record, cassette, checks, known_good=None):
    server = _Replay(record["history"], record["gold"][0], record.get("reference"))
    return diagnose(server, "T", known_good, checks, cassette, Budget(auto=True, max_size=4))


def test_debugger_reads_two_converted_traces(tmp_path):
    _sources, records = _load()
    cassette = tmp_path / "cassette.db"
    Cassette(cassette).mark_replay(1)
    debate = records[2]
    passed = _diagnose(debate, cassette, Checks(
        [{"type": "equals", "value": debate["history"][0]["values"]["final_output"]}],
        "final_output", tmp_path, tmp_path / "check"))
    assert passed["status"] == "abstain" and passed["reason_code"] == "already_passes"
    assert passed["pruning"]["nodes_on_path"] == list(dict.fromkeys(_names(debate)))

    for record in (records[0], records[1]):
        checks = Checks([{"type": "equals", "value": record["reference"]}],
                        "final_output", tmp_path, tmp_path / "check")
        nodes = list(dict.fromkeys(_names(record)))
        known_good = {name: {"seen": {"$add": [name]}} for name in nodes}
        art = _diagnose(record, cassette, checks, known_good)
        assert art["status"] == "found", art.get("reason")
        assert {frozenset(s) for s in art["minimal_sets"]} == {frozenset(record["gold"][0])}
        assert art["counts"]["fixes"] >= 1 and art["trials"]


def test_speakerless_final_answer_is_the_only_answer_string():
    row = {
        "id": "debate-1", "framework": "debate",
        "ground_truth": {"agents": ["agent_1"], "round": 0, "mode": "R.4"},
        "trajectory": [
            {"kind": "user", "content": "pick a letter"},
            {"kind": "round", "round": 0, "turns": [
                {"agent_id": "agent_0", "output": "I like A"},
                {"agent_id": "agent_1", "output": "a long argument"},
            ]},
            {"kind": "final_answer", "content": "D"},
        ],
    }
    record, reason = convert.convert_whowhen(row)
    assert reason is None
    assert record["gold"] == [["agent_1"]]
    last = record["history"][1]["tasks"][0]
    assert last["name"] == "agent_1"
    assert last["result"]["text"] == "a long argument"
    assert last["result"]["final_output"] == "D"
    assert record["history"][0]["values"]["final_output"] == "D"
    assert record["history"][1]["values"]["prior"] == ["I like A"]
    assert record["history"][2]["values"]["prior"] == []
    assert "mode" not in (record["label_step"] or {})
