"""Deny-list redaction for what the cassette stores (spec FR-R8).

Applied to the stored copy of a request (HTTP body or tool input) only. The cassette key
is hashed from the original request and responses are kept verbatim, because replay must
match and rebuild exactly what the recording saw.

Deny-list (documented, deliberately small):
  keys    api_key, x-api-key, authorization, proxy-authorization, password, passwd, secret,
          client_secret, token, access_token, refresh_token, id_token, session_token,
          private_key, cookie, set-cookie, aws_secret_access_key
          (compared case-insensitively, ignoring '-' and '_'; "max_tokens" is not "token")
  values  OpenAI/Anthropic-style keys (sk-...), "Bearer <token>", AWS access key ids,
          GitHub tokens, JWTs, email addresses (the only PII class covered)
"""

import json
import re

REDACTED = "[REDACTED]"

_KEYS = {k.replace("_", "").replace("-", "") for k in (
    "api_key", "x-api-key", "authorization", "proxy-authorization", "password", "passwd", "secret",
    "client_secret", "token", "access_token", "refresh_token", "id_token", "session_token",
    "private_key", "cookie", "set-cookie", "aws_secret_access_key")}

_VALUES = re.compile("|".join((
    r"sk-[A-Za-z0-9_-]{16,}",
    r"Bearer\s+[A-Za-z0-9._~+/=-]{8,}",
    r"AKIA[0-9A-Z]{16}",
    r"gh[pousr]_[A-Za-z0-9]{30,}",
    r"eyJ[A-Za-z0-9_-]{5,}\.eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*",
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+",
)))


def _text(s: str) -> str:
    return _VALUES.sub(REDACTED, s)


def _walk(value):
    if isinstance(value, dict):
        return {k: REDACTED if k.lower().replace("_", "").replace("-", "") in _KEYS else _walk(v)
                for k, v in value.items()}
    if isinstance(value, list):
        return [_walk(v) for v in value]
    return _text(value) if isinstance(value, str) else value


def redact_body(body: bytes) -> bytes:
    """Return `body` with deny-listed keys and secret-shaped values masked."""
    try:
        parsed = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return _text(body.decode("utf-8", "replace")).encode()
    cleaned = _walk(parsed)
    return body if cleaned == parsed else json.dumps(cleaned, separators=(",", ":")).encode()
