"""Deterministic G1 model stub: an OpenAI-compatible /chat/completions that answers with a fixed node list.

`python tests/g1_stub.py --port 8765 --nodes retriever,extractor` for the demo (`--g1-url http://127.0.0.1:8765/v1
--g1-model stub`); `ShortlistStub([...], per_sample=[[...], [...]])` in tests. It records every request body
(`hits`) so tests can check the call carried no tools and no secrets.
"""

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        body["_auth"] = self.headers.get("Authorization")
        srv = self.server
        srv.hits.append(body)
        replies = srv.per_sample or [srv.nodes]
        text = srv.raw if srv.raw is not None else json.dumps(replies[min(len(srv.hits) - 1, len(replies) - 1)])
        out = json.dumps({"choices": [{"index": 0, "message": {"role": "assistant", "content": text}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


class ShortlistStub:
    def __init__(self, nodes=(), per_sample=None, raw=None, port=0):
        self._srv = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
        self._srv.hits, self._srv.nodes, self._srv.per_sample, self._srv.raw = [], list(nodes), per_sample, raw
        self.url = f"http://127.0.0.1:{self._srv.server_address[1]}/v1"
        self.hits = self._srv.hits
        self._thread = None

    def __enter__(self):
        self._thread = threading.Thread(target=self._srv.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._srv.shutdown()
        self._srv.server_close()
        self._thread.join(timeout=5)


class _LayaHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        self.server.hits.append({**body, "_auth": self.headers.get("Authorization"), "_path": self.path})
        status, payload, delay = self.server.reply(body)
        time.sleep(delay)
        out = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


class LayaStub(ShortlistStub):
    """A Laya System One stand-in: `reply(body) -> (status, payload, delay_s)` answers each POST."""

    def __init__(self, reply):
        self._srv = ThreadingHTTPServer(("127.0.0.1", 0), _LayaHandler)
        self._srv.hits, self._srv.reply = [], reply
        self.url = f"http://127.0.0.1:{self._srv.server_address[1]}"
        self.hits = self._srv.hits
        self._thread = None


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--nodes", default="", help="comma-separated node names the stub nominates")
    a = ap.parse_args()
    stub = ShortlistStub([n for n in a.nodes.split(",") if n], port=a.port)
    print(f"G1 stub on {stub.url}", flush=True)
    stub._srv.serve_forever()
