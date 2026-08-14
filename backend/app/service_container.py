"""Ressources partagées par toutes les routes pendant la vie du processus."""

from app.config.settings import settings
from app.memory.redis_memory import RedisMemoryService
from app.services.auth_service import AuthService
from app.services.embedding_service import HuggingFaceEmbeddingService
from app.services.llm_service import LLMService
from app.services.search_service import SearchService
from app.workflows.chat_workflow import ChatWorkflow


class ApplicationServices:
    """Construit une seule fois les clients réseau et les services qui les utilisent."""

    def __init__(self) -> None:
        self.memory = RedisMemoryService(settings.redis_url, settings.redis_ttl_seconds)
        self.search = SearchService()
        self.embedding = HuggingFaceEmbeddingService()
        self.llm = LLMService()
        self.auth = AuthService(self.memory)
        self.workflow = ChatWorkflow(
            memory_service=self.memory,
            cache_service=self.memory,
            search_service=self.search,
            llm_service=self.llm,
            embedding_service=self.embedding,
        )

    async def close(self) -> None:
        """Ferme proprement les connexions possédées par le conteneur."""
        await self.memory.close()
        self.search.close()
        if self.llm.client is not None:
            await self.llm.client.close()
