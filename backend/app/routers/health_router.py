"""
Endpoint `/health` : sonde de supervision (health check).

Retourne l'état de l'application ET de ses dépendances externes
(Redis, MongoDB Atlas), sans nécessiter d'authentification. C'est ce
que le frontend interroge en continu pour afficher les pastilles
"online/offline" (backend, redis, mongodb, model) dans son cockpit.
Volontairement exempté du rate limiting (voir `RateLimitMiddleware`).
"""

from fastapi import APIRouter, Depends

from app.config.settings import settings
from app.logger import logger
from app.dependencies.services import get_memory_service, get_search_service
from app.memory.redis_memory import RedisMemoryService
from app.services.search_service import SearchService

router = APIRouter(tags=["health"])

@router.get("/health")
def health(
    memory_service: RedisMemoryService = Depends(get_memory_service),
    search_service: SearchService = Depends(get_search_service),
) -> dict[str,object]:
    """Renvoie un instantané de l'état du backend et de ses dépendances."""
    logger.bind(
        redis_connected=memory_service.using_redis,
        mongodb_connected=search_service.available,
    ).info("Health check requested.")
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.app_env,
        "llm_provider": settings.llm_provider,
        "redis_connected": memory_service.using_redis,
        "mongodb_connected": search_service.available,
    }
