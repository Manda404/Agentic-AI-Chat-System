"""
Middleware qui ajoute des en-têtes de sécurité HTTP à chaque réponse.

Ne fait aucune logique métier : il se contente d'ajouter des headers
standards (CSP, X-Frame-Options, etc.) pour réduire la surface
d'attaque côté navigateur (clickjacking, XSS, sniffing MIME...).
Ce middleware ne logue rien intentionnellement : il s'exécute sur
CHAQUE requête et n'apporte aucune information utile au diagnostic.
"""

from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add security headers to all responses.
    Helps protect against common web vulnerabilities.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Laisse la requête suivre son cours puis ajoute les en-têtes de sécurité à la réponse."""
        response = await call_next(request)
        
        response.headers["X-Frame-Options"] = "DENY"
        
        response.headers["X-Content-Type-Options"] = "nosniff"
        
        response.headers["X-XSS-Protection"] = "1; mode=block"
        
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "font-src 'self' data:; "
            "connect-src 'self'"
        )
        
        response.headers["Permissions-Policy"] = (
            "geolocation=(), "
            "microphone=(), "
            "camera=(), "
            "payment=(), "
            "usb=(), "
            "magnetometer=(), "
            "gyroscope=(), "
            "accelerometer=()"
        )
        
       
        
        return response


