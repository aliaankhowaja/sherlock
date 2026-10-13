"""SQLite cassette store under .sherlock/ (spec 4.2, 9.3).

One row per intercepted call (HTTP request or local tool call) plus its
response as an ordered list of chunks. Matching key = hash of the request;
`next_by_name` is the sequential-order fallback.
"""

import hashlib
import json
import sqlite3
import time
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  name TEXT NOT NULL,
  key TEXT NOT NULL,
  request BLOB NOT NULL,
  status INTEGER,
  headers TEXT,
  is_sse INTEGER NOT NULL DEFAULT 0,
  started REAL NOT NULL,
  duration_ms REAL,
  complete INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS calls_key ON calls(kind, key);
CREATE TABLE IF NOT EXISTS chunks (
  call_id INTEGER NOT NULL, seq INTEGER NOT NULL, data BLOB NOT NULL,
  PRIMARY KEY (call_id, seq)
);
CREATE TABLE IF NOT EXISTS abstains (
  id INTEGER PRIMARY KEY AUTOINCREMENT, reason TEXT NOT NULL, at REAL NOT NULL
);
"""
# calls.kind: 'http' | 'tool'.  calls.name: 'POST <url>' or the tool name.
# calls.status: HTTP status; for tools 0 = returned, 1 = raised.
# calls.headers: JSON list of [name, value].


def request_key(kind: str, name: str, body: bytes) -> str:
    try:
        canon = json.dumps(json.loads(body), sort_keys=True, separators=(",", ":")).encode()
    except (ValueError, UnicodeDecodeError):
        canon = body
    h = hashlib.sha256()
    for part in (kind.encode(), name.encode(), canon):
        h.update(part)
        h.update(b"\0")
    return h.hexdigest()


class Cassette:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._run_script(_SCHEMA)

    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _run_script(self, script):
        conn = self._conn()
        try:
            conn.executescript(script)
        finally:
            conn.close()

    def _run(self, sql, args=(), *, one=False, write=False):
        conn = self._conn()
        try:
            cur = conn.execute(sql, args)
            if write:
                conn.commit()
                return cur.lastrowid
            rows = cur.fetchall()
            return (rows[0] if rows else None) if one else rows
        finally:
            conn.close()

    def begin(self, kind, name, body: bytes) -> int:
        return self._run(
            "INSERT INTO calls(kind, name, key, request, started) VALUES (?,?,?,?,?)",
            (kind, name, request_key(kind, name, body), body, time.time()), write=True)

    def finish(self, call_id, *, status, headers, is_sse, duration_ms, chunks):
        conn = self._conn()
        try:
            conn.execute("DELETE FROM chunks WHERE call_id=?", (call_id,))
            conn.executemany("INSERT INTO chunks VALUES (?,?,?)",
                             [(call_id, i, c) for i, c in enumerate(chunks)])
            conn.execute(
                "UPDATE calls SET status=?, headers=?, is_sse=?, duration_ms=?, complete=1 WHERE id=?",
                (status, json.dumps(headers), int(is_sse), duration_ms, call_id))
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _row(r):
        if r is None:
            return None
        d = dict(r)
        d["headers"] = json.loads(d["headers"]) if d["headers"] else []
        return d

    @staticmethod
    def _skip(consumed):
        return f" AND id NOT IN ({','.join(str(int(i)) for i in consumed)})" if consumed else ""

    def find(self, kind, key, consumed):
        return self._row(self._run(
            "SELECT * FROM calls WHERE kind=? AND key=? AND complete=1" + self._skip(consumed)
            + " ORDER BY id LIMIT 1", (kind, key), one=True))

    def next_by_name(self, kind, name, consumed):
        return self._row(self._run(
            "SELECT * FROM calls WHERE kind=? AND name=? AND complete=1" + self._skip(consumed)
            + " ORDER BY id LIMIT 1", (kind, name), one=True))

    def chunks(self, call_id):
        rows = self._run("SELECT data FROM chunks WHERE call_id=? ORDER BY seq", (call_id,))
        return [bytes(r["data"]) for r in rows]

    def calls(self):
        return [self._row(r) for r in self._run("SELECT * FROM calls ORDER BY id")]

    def add_abstain(self, reason):
        self._run("INSERT INTO abstains(reason, at) VALUES (?,?)", (reason, time.time()), write=True)

    def abstains(self):
        return [r["reason"] for r in self._run("SELECT reason FROM abstains ORDER BY id")]
