"""Structured logs, request ids, and Prometheus metrics.

- Every log line is one JSON object with the request id, so one request can be followed
  through the API and into the background jobs it enqueued (jobs store the id).
- Metrics are served on a separate internal port (METRICS_PORT), never on the public API.
"""

import json
import logging
import re
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from prometheus_client import Counter, Histogram, start_http_server
from starlette.types import ASGIApp, Message, Receive, Scope, Send

request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
log = logging.getLogger("app.access")

HTTP_REQUESTS = Counter(
    "http_requests_total", "HTTP requests by route template.", ["method", "route", "status"]
)
HTTP_SECONDS = Histogram("http_request_duration_seconds", "HTTP latency.", ["method", "route"])
JOBS = Counter("jobs_total", "Background jobs run.", ["kind", "outcome"])
JOB_SECONDS = Histogram("job_duration_seconds", "Background job duration.", ["kind"])
LLM_TOKENS = Counter("llm_tokens_total", "Claude API tokens.", ["model", "direction"])

_SAFE_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")
_QUIET_ROUTES = {"/healthz", "/readyz"}  # polled every few seconds: metrics yes, log lines no


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id.get(),
            **getattr(record, "fields", {}),  # log.info("...", extra={"fields": {...}})
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def setup_logging(level: int = logging.INFO) -> None:
    """JSON lines on stdout (12-factor: the platform collects stdout)."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)
    for name in ("uvicorn", "uvicorn.error"):  # route uvicorn's own lines through JSON too
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True
    logging.getLogger("uvicorn.access").disabled = True  # replaced by our access line


def start_metrics_server(port: int) -> None:
    start_http_server(port)


class RequestContext:
    """ASGI middleware: request id (reuse a sane incoming X-Request-ID, else a new one),
    returned in the response header, plus one access log line and metrics per request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope["headers"]).get(b"x-request-id", b"").decode("latin-1")
        rid = incoming if _SAFE_ID.fullmatch(incoming) else uuid.uuid4().hex
        token = request_id.set(rid)
        status, started = 500, time.perf_counter()

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message["headers"] = [*message.get("headers", []), (b"x-request-id", rid.encode())]
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            # The router stored the matched route on the scope: label by template
            # (/v1/suppliers/{supplier_id}), never the raw path, or metrics explode per id.
            route = getattr(scope.get("route"), "path", "unmatched")
            elapsed = time.perf_counter() - started
            method = scope["method"]
            HTTP_REQUESTS.labels(method, route, str(status)).inc()
            HTTP_SECONDS.labels(method, route).observe(elapsed)
            if route not in _QUIET_ROUTES:
                fields = {"method": method, "route": route, "status": status}
                log.info("request", extra={"fields": {**fields, "ms": round(elapsed * 1000, 1)}})
            request_id.reset(token)
