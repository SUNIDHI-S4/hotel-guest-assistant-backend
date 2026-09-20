import contextvars
import logging
import time
from uuid import uuid4

from fastapi import Request

logger = logging.getLogger("app.request")

REQUEST_ID_HEADER = "X-Request-ID"

# The id of the request being handled; "-" outside a request (startup, background work).
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

_LOG_FORMAT = "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"
_HANDLER_MARKER = "_hotel_assistant_handler"
# Libraries that log every single HTTP call at INFO, which would drown out our own lines.
_NOISY_LOGGERS = ("httpx", "httpcore", "google_genai", "hpack")


def _install_request_id_on_records() -> None:
    """Stamp every log record with the current request id, whichever handler prints it."""
    previous = logging.getLogRecordFactory()
    if getattr(previous, "adds_request_id", False):
        return

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        record.request_id = request_id_var.get()
        return record

    factory.adds_request_id = True
    logging.setLogRecordFactory(factory)


def configure_logging(level: str) -> None:
    """Send app logs to stderr with a request id on every line. Safe to call repeatedly."""
    _install_request_id_on_records()

    root = logging.getLogger()
    root.setLevel(level.upper())
    if not any(getattr(handler, _HANDLER_MARKER, False) for handler in root.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        setattr(handler, _HANDLER_MARKER, True)
        root.addHandler(handler)

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


async def request_context_middleware(request: Request, call_next):
    """Give each request an id, log how long it took, and return the id to the caller.

    A caller-supplied X-Request-ID is reused, so one id can follow a request from the browser
    through to these logs. Only the method, path and status are logged, never message content.
    """
    request_id = request.headers.get(REQUEST_ID_HEADER) or uuid4().hex[:12]
    token = request_id_var.set(request_id)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("%s %s -> unhandled error", request.method, request.url.path)
        raise
    else:
        response.headers[REQUEST_ID_HEADER] = request_id
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        logger.log(
            logging.WARNING if response.status_code >= 500 else logging.INFO,
            "%s %s -> %d in %dms",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response
    finally:
        request_id_var.reset(token)
