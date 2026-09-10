"""Log incoming HTTP requests and outgoing responses with a unique request_id and duration. Record Incoming request, Request completed or Request failed. Return X-Request-ID so clients can correlate failures with logs."""

import time
import uuid
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.logger import logger


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware to log all incoming requests and outgoing responses.
    Adds request ID for correlation and tracks request duration.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Create a request ID and log request entry, completion and duration."""
        request_id = str(uuid.uuid4())

        request.state.request_id = request_id

        request_logger = logger.bind(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        request_logger.bind(
            client_host=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        ).info("Incoming request")

        start_time = time.time()

        try:
            response = await call_next(request)

            duration = time.time() - start_time

            response.headers["X-Request-ID"] = request_id

            request_logger.bind(
                status_code=response.status_code,
                duration_ms=round(duration * 1000, 2),
            ).info("Request completed")

            return response

        except Exception as e:
            duration = time.time() - start_time
            request_logger.bind(
                error=str(e),
                duration_ms=round(duration * 1000, 2),
            ).exception("Request failed")
            raise


