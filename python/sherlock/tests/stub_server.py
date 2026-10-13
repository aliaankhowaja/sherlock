"""In-process OpenAI-compatible stub: deterministic replies, JSON and SSE streaming. No network beyond loopback."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def reply_text(messages):
    last = [m for m in messages if m.get("role") == "user"][-1]["content"]
    return f"echo: {last}"


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"  # close-delimited bodies: each SSE event is flushed on its own

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        self.server.hits.append(body)
        text = reply_text(body["messages"])
        model = body.get("model", "stub-1")
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for word in text.split(" "):
                chunk = {"id": "stub-1", "object": "chat.completion.chunk", "model": model,
                         "choices": [{"index": 0, "delta": {"content": word + " "}}]}
                self.wfile.write(b"data: " + json.dumps(chunk).encode() + b"\n\n")
                self.wfile.flush()
                time.sleep(0.02)
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return
        out = json.dumps({"id": "stub-1", "object": "chat.completion", "model": model,
                          "choices": [{"index": 0, "finish_reason": "stop",
                                       "message": {"role": "assistant", "content": text}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


class StubServer:
    def __init__(self, port=0):
        self._srv = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
        self._srv.hits = []
        self.port = self._srv.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self._thread = None

    @property
    def hits(self):
        return self._srv.hits

    def start(self):
        self._thread = threading.Thread(target=self._srv.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        if self._thread is None:
            return
        self._srv.shutdown()
        self._srv.server_close()
        self._thread.join(timeout=5)
        self._thread = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
