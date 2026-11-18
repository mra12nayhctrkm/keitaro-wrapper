"""
Request IDs, structured logs, Prometheus metrics and optional Sentry.

* Every request gets an ID (taken from `X-Request-ID` or generated), returned in
  the response and attached to every log line written while handling it.
* `LOG_FORMAT=json` writes one JSON object per line, ready for Loki/ELK.
* `/metrics` exposes Prometheus metrics for the API and for Keitaro calls,
  including `keitaro_api_key_valid` (0 when Keitaro rejects the key) to alert on.
* `SENTRY_DSN` turns on error reporting to Sentry.
"""

import json
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from datetime import UTC, datetime

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

from app.config import Settings

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

HTTP_REQUESTS = Counter("http_requests_total", "API requests", ["method", "route", "status"])
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds", "API request duration", ["method", "route"]
)
KEITARO_REQUESTS = Counter(
    "keitaro_requests_total", "Requests to the Keitaro API", ["method", "endpoint", "status"]
)
KEITARO_LATENCY = Histogram(
    "keitaro_request_duration_seconds", "Keitaro API request duration", ["method", "endpoint"]
)
KEITARO_API_KEY_VALID = Gauge(
    "keitaro_api_key_valid", "1 while Keitaro accepts the API key, 0 after it rejected it"
)
KEITARO_API_KEY_VALID.set(1)
_key_valid = True

log = logging.getLogger("app")
_IDS = re.compile(r"/\d+")


def endpoint_label(path: str) -> str:
    """`/campaigns/214529/streams` -> `/campaigns/{id}/streams` (bounded label values)."""
    return _IDS.sub("/{id}", path)


def record_keitaro_call(method: str, path: str, status: int | str, seconds: float) -> None:
    endpoint = endpoint_label(path)
    KEITARO_REQUESTS.labels(method, endpoint, str(status)).inc()
    KEITARO_LATENCY.labels(method, endpoint).observe(seconds)
    global _key_valid
    if status in (401, 403):
        if _key_valid:  # log once per outage, not on every request
            log.error("Keitaro rejected the API key (HTTP %s): check KEITARO_API_KEY", status)
        _key_valid = False
        KEITARO_API_KEY_VALID.set(0)
    elif isinstance(status, int) and status < 400:
        if not _key_valid:
            log.info("Keitaro accepts the API key again")
        _key_valid = True
        KEITARO_API_KEY_VALID.set(1)


_key_valid = True


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        for key in ("method", "path", "status", "duration_ms", "user"):
            if hasattr(record, key):
                entry[key] = getattr(record, key)
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def configure_logging(settings: Settings) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(_RequestIdFilter())
    if settings.log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s")
        )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level.upper())
    # Our access log replaces uvicorn's (it has the request ID and the user).
    logging.getLogger("uvicorn.access").disabled = True


def configure_sentry(settings: Settings) -> None:
    dsn = settings.sentry_dsn.get_secret_value()
    if not dsn:
        return
    import sentry_sdk

    sentry_sdk.init(
        dsn=dsn, environment=settings.environment, traces_sample_rate=0.0, send_default_pii=False
    )


def install(app: FastAPI) -> None:
    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.middleware("http")
    async def observe(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        token = request_id_var.set(request_id[:64])
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request_id_var.get()
            return response
        finally:
            seconds = time.perf_counter() - start
            route = getattr(request.scope.get("route"), "path", "unmatched")
            if route != "/metrics":
                HTTP_REQUESTS.labels(request.method, route, str(status)).inc()
                HTTP_LATENCY.labels(request.method, route).observe(seconds)
                principal = getattr(request.state, "principal", None)
                log.info(
                    "%s %s %s %.0fms",
                    request.method,
                    request.url.path,
                    status,
                    seconds * 1000,
                    extra={
                        "method": request.method,
                        "path": request.url.path,
                        "status": status,
                        "duration_ms": round(seconds * 1000, 1),
                        "user": getattr(principal, "user", None),
                    },
                )
            request_id_var.reset(token)
