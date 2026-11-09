"""Turn AEGIS and Who&When Pro text rows into Sherlock checkpoint history.

    cd python/sherlock
    uv run python eval/convert_public_traces.py --out ../../docs/eval/public_traces/cases.jsonl

One kept trace is one JSON object: newest-first history, gold as a list of one name list,
and the answer string on the terminal snapshot and on the last agent's result. Rows with
fewer than two agents are dropped, including the single-agent Who&When families
(smolagents, alfagent). A count that disagrees with the pinned snapshot stops the run.

The bulk file is gitignored. Tests read tests/fixtures/public_traces/sources.jsonl.
"""

import argparse
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path

AEGIS_REV = "b936269a5143e4450242d8628bff026bdc5bae18"
WHOWHEN_REV = "0bd196c8a040841c4ae167ab33cc8151de246f1f"

# Speakers that are the task prompt, not a node. smoagents then keeps Manager and Searcher.
NOT_NODES = {"User", "System", "user", "human"}
# One model in a tool loop. The structural rule (one speaker, null culprit) already drops
# them; the name is checked so a parser bug cannot invent a second node and keep the family.
SINGLE_AGENT = {"smolagents", "alfagent"}
LABEL_KEYS = {
    "is_injected", "is_replayed", "injection_via", "phase", "error_type",
    "injection_strategy", "malicious_action_description",
}
LABEL_STEP_KEYS = ("step", "round", "position", "stage")

# Measured on the pinned snapshots. A mismatch means the walk changed, so the file is wrong.
EXPECTED = {
    "aegis_rows": 2387,
    "aegis_kept": 2364,
    "aegis_test_kept": 591,
    "aegis_val_kept": 1773,
    "aegis_test_frameworks": {
        "macnet": 156, "agentverse": 143, "llm_debate": 140, "dylan": 85, "smoagents": 48, "magentic_one": 19,
    },
    "aegis_val_frameworks": {
        "agentverse": 485, "macnet": 453, "llm_debate": 444, "dylan": 284, "smoagents": 73, "magentic_one": 34,
    },
    "aegis_gold_sizes": {1: 432, 2: 885, 3: 855, 4: 192},
    "aegis_drops": {("test", "one_speaker", "magentic_one"): 9, ("val", "one_speaker", "magentic_one"): 9,
                    ("val", "empty_answer", "llm_debate"): 4, ("val", "empty_answer", "macnet"): 1},
    "whowhen_rows": 6257,
    "whowhen_kept": 2668,
    "whowhen_headline": 1748,
    "whowhen_two_role": 920,
    "whowhen_frameworks": {
        "mathchat": 920, "magentic-one": 809, "debate": 445, "macnet": 261, "dylan": 152, "metagpt": 81,
    },
    "whowhen_drops": {("smolagents", "single_agent"): 3276, ("alfagent", "single_agent"): 311,
                      ("magentic-one", "one_speaker"): 2},
}


def hf_file(repo: str, rev: str, *parts: str) -> Path:
    """A file inside a Hugging Face dataset snapshot, under the usual hub cache."""
    hub = Path(os.environ.get("HF_HUB_CACHE") or Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub")
    return hub / f"datasets--{repo.replace('/', '--')}" / "snapshots" / rev / Path(*parts)


def default_paths() -> dict[str, Path]:
    return {
        "aegis_test": hf_file("Fancylalala/AEGIS", AEGIS_REV, "Aegis-Bench", "test.jsonl"),
        "aegis_val": hf_file("Fancylalala/AEGIS", AEGIS_REV, "Aegis-Training", "val.jsonl"),
        "whowhen": hf_file("Leoxx/whowhen_pro", WHOWHEN_REV, "data", "text.jsonl"),
    }


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _parse(value):
    """Who&When stores trajectory and ground_truth as JSON strings. A dict is left as it is."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _unique(names) -> list[str]:
    out, seen = [], set()
    for name in names:
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _label_leak(obj) -> bool:
    if isinstance(obj, dict):
        return bool(LABEL_KEYS.intersection(obj)) or any(_label_leak(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_label_leak(v) for v in obj)
    return False


def history_for(run_id: str, query: str, turns: list[tuple[str, str]], answer: str) -> list[dict]:
    """Newest first. `turns` is conversation order. The answer sits on the terminal snapshot and the last agent."""
    n = len(turns)
    snaps = [{
        "checkpoint": {"checkpoint_id": "end"},
        "metadata": {"step": n, "run_id": run_id},
        "values": {"query": query, "final_output": answer},
        "next": [],
        "tasks": [],
    }]
    for i in range(n, 0, -1):
        name, text = turns[i - 1]
        result = {"text": text}
        if i == n:
            result["final_output"] = answer
        snaps.append({
            "checkpoint": {"checkpoint_id": f"s{i}"},
            "metadata": {"step": i, "run_id": run_id},
            "values": {"query": query, "prior": [utterance for _, utterance in turns[: i - 1]]},
            # The fork planner treats `next` as the node that ran from this checkpoint.
            "next": [name],
            "tasks": [{"name": name, "result": result}],
        })
    return snaps


def _reject(turns, gold, answer, reference) -> str | None:
    names = {name for name, _ in turns}
    if len(names) < 2:
        return "one_speaker"
    if not gold or any(g not in names for g in gold):
        return "gold"
    if answer == "":
        return "empty_answer"
    if reference is not None and reference == answer:
        return "already_matches"
    return None


def shape_errors(rec: dict) -> list[str]:
    """The invariants a kept record has to satisfy before it is written or scored."""
    errs = []
    history = rec.get("history")
    if not isinstance(history, list) or not history:
        return ["history is not a non-empty array"]
    terminal = history[0]
    if terminal.get("tasks") != []:
        errs.append("terminal snapshot has tasks")
    answer = (terminal.get("values") or {}).get("final_output")
    if not isinstance(answer, str) or answer == "":
        errs.append("terminal final_output is missing")
    if (terminal.get("metadata") or {}).get("step") != sum(len(s.get("tasks") or []) for s in history):
        errs.append("terminal step is not the number of agent turns")
    tasks = []
    for snap in history:
        values = snap.get("values") or {}
        if _label_leak(values):
            errs.append("label key in values")
        for task in snap.get("tasks") or []:
            tasks.append(task)
            if not isinstance(task.get("name"), str) or not task["name"]:
                errs.append("task missing name")
            result = task.get("result")
            if not isinstance(result, dict) or "text" not in result:
                errs.append("task result has no text")
            elif _label_leak(result):
                errs.append("label key in result")
    names = [t.get("name") for t in tasks]
    distinct = set(names)
    if len(distinct) < 2:
        errs.append("fewer than two agents")
    if distinct & NOT_NODES:
        errs.append("prompt speaker kept as a node")
    hits = [t for t in tasks if isinstance(t.get("result"), dict) and "final_output" in t["result"]]
    if len(hits) != 1 or not tasks or hits[0] is not tasks[0]:
        errs.append("final_output is not on the last agent only")
    elif hits[0]["result"]["final_output"] != answer:
        errs.append("the two copies of the answer differ")
    gold = rec.get("gold")
    if not (isinstance(gold, list) and len(gold) == 1 and isinstance(gold[0], list) and gold[0]):
        errs.append("gold is not one non-empty list")
    elif any(g not in distinct for g in gold[0]):
        errs.append("gold name is not a node")
    if rec.get("framework") == "mathchat":
        if "two_role" not in rec.get("tags", []):
            errs.append("mathchat missing two_role")
    elif "two_role" in rec.get("tags", []):
        errs.append("two_role on a non-mathchat row")
    if rec.get("framework") in SINGLE_AGENT:
        errs.append("single-agent family kept")
    return errs


def _record(row_id, source, framework, gold, reference, label_step, tags, query, turns, answer):
    rec = {
        "id": row_id,
        "source": source,
        "framework": framework,
        "gold": [gold],
        "reference": reference,
        "label_step": label_step,
        "tags": tags,
        "history": history_for(row_id, query, turns, answer),
    }
    errs = shape_errors(rec)
    if errs:
        raise RuntimeError(f"{row_id}: {'; '.join(errs)}")
    return rec


def aegis_reference(correct) -> str | None:
    """The short string an equals-check would use. GSM8K puts it after the last ####."""
    if correct is None:
        return None
    text = _text(correct)
    if "####" in text:
        return text.rsplit("####", 1)[1].strip()
    return text


def convert_aegis(row: dict) -> tuple[dict | None, str | None]:
    """One AEGIS row. `(record, None)` when kept, `(None, reason)` when dropped."""
    turns = []
    for turn in row["input"]["conversation_history"]:
        name = turn.get("agent_name")
        if not isinstance(name, str) or name in NOT_NODES:
            continue
        turns.append((name, _text(turn.get("content"))))
    gold = _unique(item.get("agent_name") if isinstance(item, dict) else item
                   for item in (row.get("ground_truth") or {}).get("injected_agents") or [])
    gold = [g for g in gold if isinstance(g, str)]
    answer = turns[-1][1] if turns else ""
    reference = aegis_reference((row.get("ground_truth") or {}).get("correct_answer"))
    reason = _reject(turns, gold, answer, reference)
    if reason:
        return None, reason
    query = _text((row.get("input") or {}).get("query"))
    framework = (row.get("metadata") or {}).get("framework")
    return _record(row.get("id"), "aegis", framework, gold, reference, None, [], query, turns, answer), None


def _speaker(item: dict) -> str | None:
    """The node name the label uses. `role` is a display string and does not match."""
    for key in ("agent_id", "agent"):
        name = item.get(key)
        if isinstance(name, str) and name and name not in NOT_NODES:
            return name
    return None


def _message(item: dict) -> str:
    """`output` when `content` is null. Debate and MacNet leave the words in `output`."""
    if "content" in item and item["content"] is not None:
        return _text(item["content"])
    return _text(item.get("output"))


def _gold(gt) -> list[str]:
    if not isinstance(gt, dict):
        return []
    agents = gt.get("agents")
    if isinstance(agents, list) and agents:
        return _unique(a for a in agents if isinstance(a, str))
    agent = gt.get("agent")
    if isinstance(agent, str) and agent:
        return [agent]
    return []


def _label_step(gt):
    if not isinstance(gt, dict):
        return None
    step = {k: gt[k] for k in LABEL_STEP_KEYS if k in gt}
    return step or None


def convert_whowhen(row: dict) -> tuple[dict | None, str | None]:
    """One Who&When Pro text row. Nested `turns` are emitted in order. A speakerless final answer is the answer string."""
    framework = row.get("framework")
    if framework in SINGLE_AGENT:
        return None, "single_agent"
    gt = _parse(row.get("ground_truth"))
    traj = _parse(row.get("trajectory"))
    if not isinstance(traj, list):
        return None, "trajectory"
    query, answer, turns = None, None, []
    for item in traj:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        if kind == "user":
            if query is None:
                query = _text(item.get("content"))
            continue
        if kind == "final_answer":
            answer = _text(item.get("content"))
            continue
        seq = item.get("turns") if kind == "round" or isinstance(item.get("turns"), list) else [item]
        for turn in seq or []:
            if not isinstance(turn, dict):
                continue
            name = _speaker(turn)
            if name is None:
                continue
            turns.append((name, _message(turn)))
    if answer is None:
        answer = turns[-1][1] if turns else ""
    if query is None:
        task = _parse(row.get("task"))
        query = _text(task.get("query")) if isinstance(task, dict) else ""
    gold = _gold(gt)
    reason = _reject(turns, gold, answer, None)
    if reason:
        return None, reason
    tags = ["two_role"] if framework == "mathchat" else []
    return _record(row.get("id"), "whowhen", framework, gold, None, _label_step(gt), tags, query, turns, answer), None


def convert_row(row: dict) -> tuple[dict | None, str | None]:
    """AEGIS has `conversation_history`. Who&When Pro text has `trajectory`."""
    if isinstance(row.get("input"), dict) and "conversation_history" in row["input"]:
        return convert_aegis(row)
    if "trajectory" in row:
        return convert_whowhen(row)
    return None, "unknown"


def iter_jsonl(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def _tally():
    return {"rows": 0, "kept": 0, "frameworks": Counter(), "gold_sizes": Counter(),
            "drops": Counter(), "ids": set(), "two_role": 0, "records": 0}


def _add(tally, rec, reason, framework):
    tally["rows"] += 1
    if rec is None:
        tally["drops"][(framework, reason)] += 1
        return
    tally["kept"] += 1
    tally["frameworks"][rec["framework"]] += 1
    tally["gold_sizes"][len(rec["gold"][0])] += 1
    tally["ids"].add(rec["id"])
    if "two_role" in rec["tags"]:
        tally["two_role"] += 1


def check_counts(test, val, ww) -> list[str]:
    """Empty when the pinned snapshots still convert to the measured table."""
    bad = []

    def eq(label, got, want):
        if got != want:
            bad.append(f"{label}: got {got}, expected {want}")

    eq("aegis rows", test["rows"] + val["rows"], EXPECTED["aegis_rows"])
    eq("aegis kept", test["kept"] + val["kept"], EXPECTED["aegis_kept"])
    eq("aegis test kept", test["kept"], EXPECTED["aegis_test_kept"])
    eq("aegis val kept", val["kept"], EXPECTED["aegis_val_kept"])
    eq("aegis test frameworks", dict(test["frameworks"]), EXPECTED["aegis_test_frameworks"])
    eq("aegis val frameworks", dict(val["frameworks"]), EXPECTED["aegis_val_frameworks"])
    gold = Counter(test["gold_sizes"]) + Counter(val["gold_sizes"])
    eq("aegis gold sizes", dict(gold), EXPECTED["aegis_gold_sizes"])
    drops = Counter({(split, reason, fw): n for split, tally in (("test", test), ("val", val))
                     for (fw, reason), n in tally["drops"].items()})
    eq("aegis drops", dict(drops), EXPECTED["aegis_drops"])
    if test["ids"] & val["ids"]:
        bad.append("aegis test and val ids overlap")
    eq("whowhen rows", ww["rows"], EXPECTED["whowhen_rows"])
    eq("whowhen kept", ww["kept"], EXPECTED["whowhen_kept"])
    eq("whowhen two_role", ww["two_role"], EXPECTED["whowhen_two_role"])
    eq("whowhen headline", ww["kept"] - ww["two_role"], EXPECTED["whowhen_headline"])
    eq("whowhen frameworks", dict(ww["frameworks"]), EXPECTED["whowhen_frameworks"])
    eq("whowhen drops", dict(ww["drops"]), EXPECTED["whowhen_drops"])
    if SINGLE_AGENT & set(ww["frameworks"]):
        bad.append("single-agent family was kept")
    return bad


def convert_files(paths: dict[str, Path], out: Path | None) -> list[str]:
    """Convert the three pinned files. Write `out` only when the counts match."""
    tallies = {key: _tally() for key in ("test", "val", "ww")}
    streams = (("test", paths["aegis_test"], convert_aegis, lambda r: (r.get("metadata") or {}).get("framework")),
               ("val", paths["aegis_val"], convert_aegis, lambda r: (r.get("metadata") or {}).get("framework")),
               ("ww", paths["whowhen"], convert_whowhen, lambda r: r.get("framework")))
    tmp = None
    handle = None
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=out.parent, prefix=out.name + ".", delete=False)
        handle = tmp
    try:
        for key, path, convert, framework_of in streams:
            for row in iter_jsonl(path):
                rec, reason = convert(row)
                _add(tallies[key], rec, reason, framework_of(row))
                if rec is not None and handle is not None:
                    handle.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
        bad = check_counts(tallies["test"], tallies["val"], tallies["ww"])
        if handle is not None:
            handle.close()
            if bad:
                Path(tmp.name).unlink(missing_ok=True)
            else:
                Path(tmp.name).replace(out)
        return bad
    except Exception:
        if handle is not None:
            handle.close()
            Path(tmp.name).unlink(missing_ok=True)
        raise


def main():
    defaults = default_paths()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--aegis-test", type=Path, default=defaults["aegis_test"])
    ap.add_argument("--aegis-val", type=Path, default=defaults["aegis_val"])
    ap.add_argument("--whowhen", type=Path, default=defaults["whowhen"])
    ap.add_argument("--out", type=Path, help="write cases.jsonl here when the counts match")
    ap.add_argument("--check", action="store_true", help="check the pinned counts and write nothing")
    args = ap.parse_args()
    paths = {"aegis_test": args.aegis_test, "aegis_val": args.aegis_val, "whowhen": args.whowhen}
    missing = [f"{name}: {path}" for name, path in paths.items() if not path.is_file()]
    if missing:
        sys.exit("pinned JSONL not found:\n" + "\n".join(missing))
    bad = convert_files(paths, None if args.check or args.out is None else args.out)
    if bad:
        sys.exit("convert_public_traces: count mismatch\n" + "\n".join(bad))
    where = args.out if args.out and not args.check else "counts only"
    print(f"kept {EXPECTED['aegis_kept']} AEGIS + {EXPECTED['whowhen_kept']} Who&When "
          f"({EXPECTED['whowhen_headline']} headline, {EXPECTED['whowhen_two_role']} two_role) -> {where}")


if __name__ == "__main__":
    main()
