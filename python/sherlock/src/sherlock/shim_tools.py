"""BaseTool.run / arun patch (spec 4.2): records local, non-HTTP tool calls (FR-R3).

Each call stores the tool input, then the output as chunk 0 (pickle, for replay)
and chunk 1 (readable text). A tool that raises is stored with status 1.
"""

import json
import pickle
import time

from sherlock.runtime import warn


def _body(tool_input):
    return json.dumps(tool_input, sort_keys=True, default=str).encode()


def _begin(rt, name, tool_input):
    try:
        return rt.cassette.begin("tool", name, _body(tool_input))
    except Exception as exc:
        warn("recording a tool call", exc)
        return None


def _finish(rt, call_id, t0, status, payload):
    try:
        try:
            blob = pickle.dumps(payload)
        except Exception:
            blob = b""  # not replayable; the readable text is still kept
        rt.cassette.finish(call_id, status=status, headers=[], is_sse=False,
                           duration_ms=(time.perf_counter() - t0) * 1000,
                           chunks=[blob, repr(payload).encode()])
    except Exception as exc:
        warn("recording a tool result", exc)


def _replayed(rt, name, tool_input):
    if rt.allow_tools is not None and name not in rt.allow_tools:
        rt.abstain(f"tool {name} is not on the read-safe allowlist; a trial never fires an unlisted tool")
    row = rt.lookup("tool", name, _body(tool_input))
    blob = rt.cassette.chunks(row["id"])[0]
    if not blob:
        rt.abstain(f"recorded output of tool {name} cannot be rebuilt (not picklable)")
    value = pickle.loads(blob)
    if row["status"] == 1:
        raise value
    return value


def patch(module, rt):
    BaseTool = module.BaseTool
    if getattr(BaseTool.run, "_sherlock_orig", None):
        return
    orig_run, orig_arun = BaseTool.run, BaseTool.arun

    def run(self, tool_input, *args, **kwargs):
        if rt.replaying:
            return _replayed(rt, self.name, tool_input)
        call_id, t0 = _begin(rt, self.name, tool_input), time.perf_counter()
        try:
            result = orig_run(self, tool_input, *args, **kwargs)
        except Exception as exc:
            if call_id is not None:
                _finish(rt, call_id, t0, 1, exc)
            raise
        if call_id is not None:
            _finish(rt, call_id, t0, 0, result)
        return result

    async def arun(self, tool_input, *args, **kwargs):
        if rt.replaying:
            return _replayed(rt, self.name, tool_input)
        call_id, t0 = _begin(rt, self.name, tool_input), time.perf_counter()
        try:
            result = await orig_arun(self, tool_input, *args, **kwargs)
        except Exception as exc:
            if call_id is not None:
                _finish(rt, call_id, t0, 1, exc)
            raise
        if call_id is not None:
            _finish(rt, call_id, t0, 0, result)
        return result

    run._sherlock_orig, arun._sherlock_orig = orig_run, orig_arun
    BaseTool.run, BaseTool.arun = run, arun


def unpatch(module):
    BaseTool = module.BaseTool
    if getattr(BaseTool.run, "_sherlock_orig", None):
        BaseTool.run, BaseTool.arun = BaseTool.run._sherlock_orig, BaseTool.arun._sherlock_orig
