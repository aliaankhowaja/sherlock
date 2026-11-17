"""bench_solver on a reply the test supplies (replay-corpus plan, step 2). No network."""

import pytest

from sherlock_harness.teams import bench_solver as team

QUESTION = "Leon pays for 3 sets at $78 and 2 chairs at $83, plus a 5% fee. What is the total?"
REPLY = "The items cost 234 + 166 = 400 and the fee is 20.\n#### 420\n"


@pytest.fixture
def asked(monkeypatch):
    """The `solve` request contents, in order; every call answers REPLY."""
    seen = []

    def fake(content):
        seen.append(content)
        return REPLY

    monkeypatch.setattr(team, "ask", fake)
    return seen


def run(faults):
    return team.graph.invoke({"question": QUESTION}, context=team.Context(faults=list(faults)))


def test_clean_run_writes_only_the_short_answer(asked):
    assert run([])["final_output"] == "420"
    assert asked == [f"{team.INSTRUCTION}\n\n{QUESTION}"]


@pytest.mark.parametrize("fault", sorted(team.HEADLINE))
def test_every_headline_fault_changes_the_output_and_not_the_request(asked, fault):
    clean, bad = run([]), run([fault])
    assert bad["final_output"] != clean["final_output"]
    assert asked[0] == asked[1]


def test_both_headline_faults_together_still_change_the_output(asked):
    assert run(sorted(team.HEADLINE))["final_output"] not in ("", "420")


def test_the_decoy_changes_its_own_write_and_nothing_the_check_reads(asked):
    clean, bad = run([]), run([team.DECOY])
    assert bad["lean"] != clean["lean"]
    assert bad["final_output"] == clean["final_output"]
    assert asked[0] == asked[1]


@pytest.mark.parametrize("fault", sorted(team.REQUEST))
def test_request_faults_change_the_solve_message(asked, fault):
    run([])
    run([fault])
    assert asked[0] != asked[1]


def test_fault_names_are_owned_by_their_nodes():
    for fault in [*team.HEADLINE, team.DECOY, *team.REQUEST]:
        assert fault.split(".")[0] in team.NODES


def test_texts_sent_besides_the_question_carry_no_digits():
    assert not any(ch.isdigit() for ch in team.INSTRUCTION + team.WORDS + team.PREFACE)


@pytest.mark.parametrize("reply, answer", [
    ("#### 420", "420"),
    ("first #### 1\nthen\n#### 42.\nbye", "42"),
    ("So the answer is B.\n#### B", "b"),
    ("#### Paris", "Paris"),
    ("no marker at all", ""),
    ("####\n", ""),
    ("#### $18.90", "18.90"),
    ("#### **1,200**", "1200"),
    ("#### \\boxed{16}", "16"),
])
def test_short_answer(reply, answer):
    assert team.short_answer(reply) == answer


def test_anthropic_api_sends_messages_and_keeps_only_text_blocks(monkeypatch):
    sent = {}

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"content": [{"type": "thinking", "thinking": "#### 1"}, {"type": "text", "text": "#### 420"}]}

    def post(self, url, json, headers):
        sent.update(url=url, body=json)
        return Resp()

    monkeypatch.setenv("BENCH_URL", "http://model.test/v1/")
    monkeypatch.setenv("BENCH_MODEL", "m")
    monkeypatch.setenv("BENCH_API", "anthropic")
    monkeypatch.setattr(team.httpx.Client, "post", post)
    assert team.ask("q") == "#### 420"
    assert sent["url"] == "http://model.test/v1/messages" and sent["body"]["max_tokens"] > 0
