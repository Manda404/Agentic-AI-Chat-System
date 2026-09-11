"""Attach browser security headers, including CSP, X-Frame-Options and MIME protections, to responses. This middleware has no business logic and intentionally emits no per-request diagnostic logs."""

from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add security headers to all responses.
    Helps protect against common web vulnerabilities.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process the request and add security headers to the response."""
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


