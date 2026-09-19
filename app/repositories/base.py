import logging
import time

import httpx
from postgrest.exceptions import APIError

from app.exceptions import DatabaseError

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 0.3

# Errors raised before a request reaches the server, so retrying can never repeat a write.
_NOT_SENT_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout)


def execute(query, *, idempotent: bool = True):
    """Run a Supabase query, retrying transient network failures.

    Reads and upserts (idempotent=True) are retried on any network error. Plain inserts
    (idempotent=False) are only retried when the connection could not be established.
    Every failure surfaces as a DatabaseError so callers handle a single exception type.
    """
    retryable = httpx.TransportError if idempotent else _NOT_SENT_ERRORS

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return query.execute()
        except retryable as exc:
            if attempt == MAX_ATTEMPTS:
                logger.exception("Database request failed after %d attempts", attempt)
                raise DatabaseError() from exc
            logger.warning(
                "Transient database error (%s), retrying %d/%d",
                type(exc).__name__,
                attempt,
                MAX_ATTEMPTS - 1,
            )
            time.sleep(RETRY_DELAY_SECONDS * attempt)
        except (APIError, httpx.HTTPError) as exc:
            logger.exception("Database request failed")
            raise DatabaseError() from exc
