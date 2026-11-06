"""Logging with a per-request ID, and redaction of secrets in query strings."""
from __future__ import annotations

import logging
import re
import time
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
_TOKEN_RE = re.compile(r"(token=)[^&\s]+", re.IGNORECASE)


def redact(text: str) -> str:
    return _TOKEN_RE.sub(r"\1[REDACTED]", text)


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
        return True


def setup_logging() -> None:
    root = logging.getLogger()
    if any(getattr(h, "_app_handler", False) for h in root.handlers):
        return
    h = logging.StreamHandler()
    h._app_handler = True  # type: ignore[attr-defined]
    h.addFilter(_RequestIdFilter())
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"))
    root.addHandler(h)
    root.setLevel(logging.INFO)
    # uvicorn's access log prints full URLs; route it through our redacting filter.
    for name in ("uvicorn.access", "uvicorn.error"):
        for uh in logging.getLogger(name).handlers:
            uh.addFilter(_RequestIdFilter())


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        if not re.fullmatch(r"[A-Za-z0-9-]{1,64}", rid):
            rid = uuid.uuid4().hex[:12]
        request.state.request_id = rid
        token = request_id_var.set(rid)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        logging.getLogger("app.request").info(
            "%s %s -> %s (%.0f ms) rid=%s", request.method, redact(str(request.url.path)),
            response.status_code, (time.perf_counter() - start) * 1000, rid)
        return response
