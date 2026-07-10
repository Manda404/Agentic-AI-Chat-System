"""
Middleware HTTP qui logue chaque requête entrante et sa réponse.

Rôle : donner un identifiant unique (`request_id`) à chaque requête HTTP,
mesurer sa durée, et logger un événement "Incoming request" à l'entrée
puis "Request completed" (ou "Request failed" en cas d'exception) à la
sortie. C'est la première trace visible dans les logs pour n'importe
quel appel au backend, ce qui permet de savoir rapidement si une requête
est arrivée, combien de temps elle a pris, et si elle a échoué.

Le `request_id` est aussi renvoyé au client via l'en-tête `X-Request-ID`,
utile pour corréler un ticket de support avec une ligne de log précise.
"""

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
        """Génère un request_id, logue entrée/sortie et le temps d'exécution."""
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


