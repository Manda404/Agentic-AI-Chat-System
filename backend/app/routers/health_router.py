"""Public /health probe reporting application, Redis and MongoDB status. The frontend uses it for dependency indicators. It is exempt from rate limiting and does not test LLM credentials or quota."""

from fastapi import APIRouter, Depends

from app.config.settings import settings
from app.logger import logger
from app.dependencies.services import get_memory_service, get_search_service, get_application_services
from app.service_container import ApplicationServices
from app.memory.redis_memory import RedisMemoryService
from app.services.search_service import SearchService

router = APIRouter(tags=["health"])

@router.get("/health")
def health(
    memory_service: RedisMemoryService = Depends(get_memory_service),
    search_service: SearchService = Depends(get_search_service),
    services: ApplicationServices = Depends(get_application_services),
) -> dict[str,object]:
    """Return a snapshot of backend and dependency status."""
    logger.bind(
        redis_connected=memory_service.using_redis,
        mongodb_connected=search_service.available,
    ).info("Health check requested.")
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.app_env,
        "llm_provider": settings.llm_provider,
        "llm_status": services.llm.last_call_status,
        "llm_checked_at": services.llm.last_call_at,
        "llm_failure_reason": services.llm.last_call_reason,
        "redis_connected": memory_service.using_redis,
        "mongodb_connected": search_service.available,
    }
