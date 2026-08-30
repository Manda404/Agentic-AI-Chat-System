"""Middleware de limitation de débit par IP, Redis si disponible, mémoire sinon."""

import hashlib
import time
from collections import defaultdict
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.logger import logger


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Limite les requêtes par IP avec un compteur Redis partagé et un fallback local."""

    def __init__(self, app, requests_per_minute: int = 60):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.request_counts = defaultdict(list)
        self.cleanup_interval = 60  # Clean up old entries every 60 seconds
        self.last_cleanup = time.time()

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Compte les requêtes par IP sur une fenêtre glissante de 60s et bloque au-delà de la limite."""
        client_ip = request.client.host if request.client else "unknown"
        
        if request.url.path == "/health":
            return await call_next(request)
        
        current_time = time.time()
        redis_count = await self._increment_redis_counter(request, client_ip, current_time)
        if redis_count is not None:
            reset_at = int((int(current_time // 60) + 1) * 60)
            if redis_count > self.requests_per_minute:
                logger.bind(
                    client_ip=client_ip,
                    path=request.url.path,
                    requests_in_window=redis_count,
                    limit=self.requests_per_minute,
                    storage="redis",
                ).warning("Rate limit exceeded")
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": "Rate limit exceeded. Please try again later.",
                        "retry_after": max(1, reset_at - int(current_time)),
                    },
                    headers={"Retry-After": str(max(1, reset_at - int(current_time)))},
                )
            response = await call_next(request)
            response.headers["X-RateLimit-Limit"] = str(self.requests_per_minute)
            response.headers["X-RateLimit-Remaining"] = str(
                max(0, self.requests_per_minute - redis_count)
            )
            response.headers["X-RateLimit-Reset"] = str(reset_at)
            return response

        if current_time - self.last_cleanup > self.cleanup_interval:
            self._cleanup_old_entries(current_time)
            self.last_cleanup = current_time
        
        timestamps = self.request_counts[client_ip]
        
        cutoff_time = current_time - 60
        timestamps[:] = [ts for ts in timestamps if ts > cutoff_time]
        
        if len(timestamps) >= self.requests_per_minute:
            logger.bind(
                client_ip=client_ip,
                path=request.url.path,
                requests_in_window=len(timestamps),
                limit=self.requests_per_minute,
            ).warning("Rate limit exceeded")
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded. Please try again later.",
                    "retry_after": 60,
                },
                headers={"Retry-After": "60"},
            )
        
        timestamps.append(current_time)
        
        response = await call_next(request)
        
        remaining = self.requests_per_minute - len(timestamps)
        response.headers["X-RateLimit-Limit"] = str(self.requests_per_minute)
        response.headers["X-RateLimit-Remaining"] = str(max(0, remaining))
        response.headers["X-RateLimit-Reset"] = str(int(current_time + 60))
        
        return response

    async def _increment_redis_counter(
        self,
        request: Request,
        client_ip: str,
        current_time: float,
    ) -> int | None:
        """Incrémente un compteur partagé Redis si le service applicatif est disponible."""
        services = getattr(request.app.state, "services", None)
        memory_service = getattr(services, "memory", None)
        if memory_service is None or not getattr(memory_service, "using_redis", False):
            return None
        bucket = int(current_time // 60)
        client_hash = hashlib.sha256(client_ip.encode("utf-8")).hexdigest()[:16]
        try:
            return await memory_service.increment_value(f"rate:{client_hash}:{bucket}", ttl=70)
        except Exception as exc:
            logger.bind(reason=str(exc)).warning(
                "Redis rate limit failed; falling back to in-memory limiter."
            )
            return None

    def _cleanup_old_entries(self, current_time: float):
        """Supprime les compteurs des IP inactives depuis plus de 5 minutes (évite une fuite mémoire)."""
        cutoff_time = current_time - 300  # 5 minutes
        ips_to_remove = []
        
        for ip, timestamps in self.request_counts.items():
            if not timestamps or max(timestamps) < cutoff_time:
                ips_to_remove.append(ip)
        
        for ip in ips_to_remove:
            del self.request_counts[ip]
        
        if ips_to_remove:
            logger.debug(f"Cleaned up rate limit data for {len(ips_to_remove)} IPs")

