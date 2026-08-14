"""Dépendances FastAPI donnant accès au conteneur initialisé au démarrage."""

from fastapi import Request

from app.memory.redis_memory import RedisMemoryService
from app.service_container import ApplicationServices
from app.services.auth_service import AuthService
from app.services.embedding_service import HuggingFaceEmbeddingService
from app.services.search_service import SearchService
from app.workflows.chat_workflow import ChatWorkflow


def get_application_services(request: Request) -> ApplicationServices:
    return request.app.state.services


def get_memory_service(request: Request) -> RedisMemoryService:
    return get_application_services(request).memory


def get_search_service(request: Request) -> SearchService:
    return get_application_services(request).search


def get_embedding_service(request: Request) -> HuggingFaceEmbeddingService:
    return get_application_services(request).embedding


def get_auth_service(request: Request) -> AuthService:
    return get_application_services(request).auth


def get_chat_workflow(request: Request) -> ChatWorkflow:
    return get_application_services(request).workflow
