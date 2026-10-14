"""Record/replay for `requests` and `urllib.request` (NFR-3). Responses are buffered whole (no streaming
fidelity); replay serves the cassette and never reaches the real transport. aiohttp is not covered."""

import email.message
import http.client
import io
import socket
import time
import urllib.error
import urllib.response

from sherlock.runtime import warn


def _bytes(body) -> bytes:
    return body if isinstance(body, bytes) else body.encode() if isinstance(body, str) else b""


def _begin(rt, method, url, body):
    try:
        return rt.cassette.begin("http", f"{method} {url}", body)
    except Exception as exc:
        warn("recording a request", exc)


def _finish(rt, call_id, t0, status, headers, content):
    if call_id is None:
        return
    try:
        rt.cassette.finish(call_id, status=status, headers=[[k, v] for k, v in headers], is_sse=False,
                           duration_ms=(time.perf_counter() - t0) * 1000, chunks=[content])
    except Exception as exc:
        warn("recording a response", exc)


def _recorded(rt, method, url, body):
    row = rt.lookup("http", f"{method} {url}", body)  # abstains (CannotSay) on a miss; never live
    return row["status"], row["headers"], b"".join(rt.cassette.chunks(row["id"]))


def patch_requests(adapters, rt):
    import requests

    orig = adapters.HTTPAdapter.send
    if getattr(orig, "_sherlock_orig", None):
        return

    def send(self, request, **kwargs):
        body = _bytes(request.body)
        if rt.replaying:
            status, headers, content = _recorded(rt, request.method, request.url, body)
            r = requests.Response()
            r.status_code, r._content, r._content_consumed = status, content, True
            for k, v in headers:
                r.headers[k] = v
            r.url, r.request, r.raw = request.url, request, io.BytesIO(content)
            r.reason = http.client.responses.get(status, "")
            r.encoding = requests.utils.get_encoding_from_headers(r.headers)
            return r
        call_id, t0 = _begin(rt, request.method, request.url, body), time.perf_counter()
        r = orig(self, request, **kwargs)
        _finish(rt, call_id, t0, r.status_code, list(r.headers.items()), r.content)
        return r

    send._sherlock_orig = orig
    adapters.HTTPAdapter.send = send


def unpatch_requests(adapters):
    s = adapters.HTTPAdapter.send
    if getattr(s, "_sherlock_orig", None):
        adapters.HTTPAdapter.send = s._sherlock_orig


def patch_urllib(request_mod, rt):
    orig = request_mod.OpenerDirector.open
    if getattr(orig, "_sherlock_orig", None):
        return

    def open_(self, fullurl, data=None, timeout=socket._GLOBAL_DEFAULT_TIMEOUT):
        req = fullurl if isinstance(fullurl, request_mod.Request) else None
        url = req.full_url if req else fullurl
        if not str(url).startswith(("http://", "https://")):
            return orig(self, fullurl, data, timeout)
        data = data if data is not None else (req.data if req else None)
        method = req.get_method() if req else ("POST" if data is not None else "GET")
        body = _bytes(data)
        if rt.replaying:
            status, headers, content = _recorded(rt, method, url, body)
            return _response(url, status, headers, content)
        call_id, t0 = _begin(rt, method, url, body), time.perf_counter()
        try:
            resp = orig(self, fullurl, data, timeout)
        except urllib.error.HTTPError as err:
            content = err.read()
            _finish(rt, call_id, t0, err.code, list(err.headers.items()), content)
            raise urllib.error.HTTPError(err.url, err.code, err.msg, err.headers, io.BytesIO(content)) from None
        content = resp.read()
        _finish(rt, call_id, t0, resp.status, list(resp.headers.items()), content)
        return urllib.response.addinfourl(io.BytesIO(content), resp.headers, resp.geturl(), resp.status)

    open_._sherlock_orig = orig
    request_mod.OpenerDirector.open = open_


def _response(url, status, headers, content):
    msg = email.message.Message()
    for k, v in headers:
        msg[k] = v
    fp = io.BytesIO(content)
    if status >= 400:
        raise urllib.error.HTTPError(url, status, http.client.responses.get(status, ""), msg, fp)
    return urllib.response.addinfourl(fp, msg, url, status)


def unpatch_urllib(request_mod):
    o = request_mod.OpenerDirector.open
    if getattr(o, "_sherlock_orig", None):
        request_mod.OpenerDirector.open = o._sherlock_orig
