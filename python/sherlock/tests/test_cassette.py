import threading

from sherlock.cassette import Cassette, request_key


def _put(c, kind, name, body, chunks=(b"x",), **kw):
    cid = c.begin(kind, name, body)
    c.finish(cid, status=kw.get("status", 200), headers=kw.get("headers", []), is_sse=kw.get("is_sse", False),
             duration_ms=1.0, chunks=list(chunks))
    return cid


def test_key_is_stable_across_json_key_order_and_spacing():
    a = request_key("http", "POST http://x/v1", b'{"a": 1, "b": [1, 2]}')
    b = request_key("http", "POST http://x/v1", b'{"b":[1,2],"a":1}')
    assert a == b


def test_key_differs_on_body_name_or_kind():
    base = request_key("http", "POST http://x/v1", b'{"a":1}')
    assert base != request_key("http", "POST http://x/v1", b'{"a":2}')
    assert base != request_key("http", "POST http://x/v2", b'{"a":1}')
    assert base != request_key("tool", "POST http://x/v1", b'{"a":1}')


def test_non_json_body_hashed_raw():
    assert request_key("http", "n", b"\x00\x01") != request_key("http", "n", b"\x00\x02")


def test_roundtrip_preserves_chunk_order_and_metadata(tmp_path):
    c = Cassette(tmp_path / ".sherlock" / "c.db")
    cid = _put(c, "http", "POST http://x", b'{"q":1}',
               chunks=[b"data: 1\n\n", b"data: 2\n\n", b"data: [DONE]\n\n"],
               headers=[["content-type", "text/event-stream"]], is_sse=True)
    row = c.find("http", request_key("http", "POST http://x", b'{"q":1}'), consumed=set())
    assert row["id"] == cid and row["status"] == 200 and row["is_sse"] == 1
    assert row["headers"] == [["content-type", "text/event-stream"]]
    assert c.chunks(cid) == [b"data: 1\n\n", b"data: 2\n\n", b"data: [DONE]\n\n"]
    assert row["request"] == b'{"q":1}'  # full request body kept (FR-R2, FR-R7)


def test_find_skips_consumed_and_serves_duplicates_in_order(tmp_path):
    c = Cassette(tmp_path / "c.db")
    ids = [_put(c, "http", "GET http://x", b"", chunks=[str(i).encode()]) for i in range(2)]
    key = request_key("http", "GET http://x", b"")
    assert c.find("http", key, set())["id"] == ids[0]
    assert c.find("http", key, {ids[0]})["id"] == ids[1]
    assert c.find("http", key, set(ids)) is None


def test_sequence_fallback_returns_next_unconsumed_with_same_name(tmp_path):
    c = Cassette(tmp_path / "c.db")
    first = _put(c, "http", "POST http://x", b'{"n":1}')
    _put(c, "http", "POST http://y", b"{}")
    second = _put(c, "http", "POST http://x", b'{"n":2}')
    assert c.next_by_name("http", "POST http://x", set())["id"] == first
    assert c.next_by_name("http", "POST http://x", {first})["id"] == second
    assert c.next_by_name("http", "POST http://z", set()) is None


def test_abstain_reasons_persist_across_connections(tmp_path):
    path = tmp_path / "c.db"
    Cassette(path).add_abstain("cannot say: no recording")
    assert Cassette(path).abstains() == ["cannot say: no recording"]


def test_survives_concurrent_writers(tmp_path):
    c = Cassette(tmp_path / "c.db")

    def work():
        for _ in range(10):
            _put(c, "http", "GET http://x", b"")

    ts = [threading.Thread(target=work) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(c.calls()) == 40
