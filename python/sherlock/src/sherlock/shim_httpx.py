"""httpx transport shim (spec 4.2): the single chokepoint under openai, anthropic and litellm.

Wraps HTTPTransport.handle_request / AsyncHTTPTransport.handle_async_request.
Records full request and response bodies; the response is stored as the ordered
chunk sequence the transport delivered, which keeps SSE streams faithful (FR-R5).
Request headers are never stored, so API keys cannot leak into a cassette.
"""

import time

from sherlock.runtime import warn


def _is_sse(response):
    return response.headers.get("content-type", "").startswith("text/event-stream")


def _headers(response):
    return [[k.decode("latin-1"), v.decode("latin-1")] for k, v in response.headers.raw]


class _Recorder:
    """Collects chunks as the consumer reads them; writes the call when the stream ends."""

    def __init__(self, rt, call_id, response):
        self.rt, self.call_id, self.response = rt, call_id, response
        self.chunks, self.t0, self.done = [], time.perf_counter(), False

    def finish(self):
        if self.done:
            return
        self.done = True
        try:
            self.rt.cassette.finish(
                self.call_id, status=self.response.status_code, headers=_headers(self.response),
                is_sse=_is_sse(self.response), duration_ms=(time.perf_counter() - self.t0) * 1000,
                chunks=self.chunks)
        except Exception as exc:
            warn("recording a response", exc)


def _begin(rt, request):
    try:
        return rt.cassette.begin("http", f"{request.method} {request.url}", request.content)
    except Exception as exc:
        warn("recording a request", exc)
        return None


def patch(httpx, rt):
    if getattr(httpx.HTTPTransport.handle_request, "_sherlock_orig", None):
        return
    orig_sync = httpx.HTTPTransport.handle_request
    orig_async = httpx.AsyncHTTPTransport.handle_async_request

    class SyncRec(httpx.SyncByteStream):
        def __init__(self, inner, rec):
            self._inner, self._rec = inner, rec

        def __iter__(self):
            try:
                for chunk in self._inner:
                    self._rec.chunks.append(bytes(chunk))
                    yield chunk
            finally:
                self._rec.finish()

        def close(self):
            try:
                self._inner.close()
            finally:
                self._rec.finish()

    class AsyncRec(httpx.AsyncByteStream):
        def __init__(self, inner, rec):
            self._inner, self._rec = inner, rec

        async def __aiter__(self):
            try:
                async for chunk in self._inner:
                    self._rec.chunks.append(bytes(chunk))
                    yield chunk
            finally:
                self._rec.finish()

        async def aclose(self):
            try:
                await self._inner.aclose()
            finally:
                self._rec.finish()

    class SyncReplay(httpx.SyncByteStream):
        def __init__(self, chunks):
            self._chunks = chunks

        def __iter__(self):
            yield from self._chunks

    class AsyncReplay(httpx.AsyncByteStream):
        def __init__(self, chunks):
            self._chunks = chunks

        async def __aiter__(self):
            for chunk in self._chunks:
                yield chunk

    def replayed(request, stream_cls):
        """Build the recorded response, or abstain. Never falls through to the real transport."""
        row = rt.lookup("http", f"{request.method} {request.url}", request.content)
        try:
            return httpx.Response(row["status"], headers=[tuple(h) for h in row["headers"]],
                                  stream=stream_cls(rt.cassette.chunks(row["id"])), request=request)
        except Exception as exc:
            rt.abstain(f"could not rebuild the recorded response ({exc!r})")

    def handle_request(self, request):
        request.read()
        if rt.replaying:
            return replayed(request, SyncReplay)
        call_id = _begin(rt, request)
        response = orig_sync(self, request)
        if call_id is not None:
            response.stream = SyncRec(response.stream, _Recorder(rt, call_id, response))
        return response

    async def handle_async_request(self, request):
        await request.aread()
        if rt.replaying:
            return replayed(request, AsyncReplay)
        call_id = _begin(rt, request)
        response = await orig_async(self, request)
        if call_id is not None:
            response.stream = AsyncRec(response.stream, _Recorder(rt, call_id, response))
        return response

    handle_request._sherlock_orig = orig_sync
    handle_async_request._sherlock_orig = orig_async
    httpx.HTTPTransport.handle_request = handle_request
    httpx.AsyncHTTPTransport.handle_async_request = handle_async_request


def unpatch(httpx):
    t = httpx.HTTPTransport.handle_request
    if getattr(t, "_sherlock_orig", None):
        httpx.HTTPTransport.handle_request = t._sherlock_orig
        a = httpx.AsyncHTTPTransport.handle_async_request
        httpx.AsyncHTTPTransport.handle_async_request = a._sherlock_orig
