"""LLM demo team (test target): ask -> count. One LLM node over httpx, one local tool node.

Usage: python llm_team.py <base_url> <question>     (set STREAM=1 for SSE)
Prints one JSON line. Knows nothing about Sherlock.
"""

import json
import os
import sys

import httpx
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict


class State(TypedDict, total=False):
    question: str
    answer: str
    words: int


@tool
def word_count(text: str) -> int:
    """Count the words in a text."""
    return len(text.split())


def build(base_url: str, stream: bool):
    def ask(state: State):
        body = {"model": "stub-1", "stream": stream,
                "messages": [{"role": "user", "content": state["question"]}]}
        url = base_url + "/v1/chat/completions"
        with httpx.Client() as client:
            if not stream:
                return {"answer": client.post(url, json=body).json()["choices"][0]["message"]["content"]}
            parts = []
            with client.stream("POST", url, json=body) as r:
                for line in r.iter_lines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        parts.append(json.loads(line[6:])["choices"][0]["delta"]["content"])
            return {"answer": "".join(parts).strip()}

    def count(state: State):
        return {"words": word_count.invoke({"text": state["answer"]})}

    g = StateGraph(State)
    g.add_node("ask", ask)
    g.add_node("count", count)
    g.add_edge(START, "ask")
    g.add_edge("ask", "count")
    g.add_edge("count", END)
    return g.compile()


if __name__ == "__main__":
    graph = build(sys.argv[1], os.environ.get("STREAM") == "1")
    print(json.dumps(graph.invoke({"question": sys.argv[2]}), sort_keys=True))
