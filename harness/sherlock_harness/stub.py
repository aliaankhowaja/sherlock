"""Minimal OpenAI-compatible echo server for the LLM-node demo team. Loopback only, deterministic."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        last = [m for m in body["messages"] if m.get("role") == "user"][-1]["content"]
        out = json.dumps({"id": "stub-1", "object": "chat.completion", "model": body.get("model", "stub-1"),
                          "choices": [{"index": 0, "finish_reason": "stop",
                                       "message": {"role": "assistant", "content": f"echo: {last}"}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


class EchoStub:
    def __init__(self, port=0):
        self._srv = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
        self.port = self._srv.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"

    def start(self):
        threading.Thread(target=self._srv.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
        return self

    def stop(self):
        self._srv.shutdown()
        self._srv.server_close()
