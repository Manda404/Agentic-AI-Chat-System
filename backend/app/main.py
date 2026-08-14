"""
Point d'entrée de l'application FastAPI.

Ce module :
1. Configure le logger centralisé (voir `app/logger.py`) AVANT toute
   autre chose, pour que même les logs émis pendant l'import des autres
   modules soient capturés correctement.
2. Crée l'application FastAPI et empile les middlewares (sécurité,
   rate limiting, logging HTTP, CORS).
3. Enregistre les routers (health, auth, ingest, chat).

Pour lancer le serveur en local :
    uvicorn app.main:app --reload
"""

from app.config.settings import settings
from app.logger import configure_logger, logger

# Le logger doit être configuré avant d'importer les routers et avant que
# le lifespan ne construise le conteneur de services partagé.
configure_logger()

if settings.app_env.lower() not in {"development", "local", "test"} and (
    not settings.auth_secret_key or settings.auth_secret_key == "change-me-in-real-projects"
):
    raise RuntimeError("AUTH_SECRET_KEY must be set to a strong non-default value outside development.")

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.middleware import (
    LoggingMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)
from app.routers.auth_router import router as auth_router
from app.routers.health_router import router as health_router
from app.routers.ingest_router import router as ingest_router
from app.routers.chat_router import router as chat_router
from app.service_container import ApplicationServices


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Crée les clients réseau dans le worker actif, puis les ferme à l'arrêt."""
    services = ApplicationServices()
    application.state.services = services
    try:
        yield
    finally:
        await services.close()

app = FastAPI(
    title=settings.app_name,
    version="0.0.1",
    description="Agentic RAG Platform backend with auth, Redis memory, MongoDB Atlas hybrid search (full-text + vector), LangGraph orchestration, and RAG-oriented agents.",
    lifespan=lifespan,
)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware, requests_per_minute=60)
app.add_middleware(LoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.backend_cors_origins,
    allow_origin_regex=(
        settings.backend_cors_dev_origin_regex
        if settings.app_env.lower() in {"development", "local"}
        else None
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(ingest_router)
app.include_router(chat_router)

logger.bind(
    app_name=settings.app_name,
    api_prefix=settings.api_prefix,
    llm_provider=settings.llm_provider,
    mongodb_collection=settings.mongodb_collection,
).info("Application startup configured.")
