"""
Agent mémoire du workflow de chat.

Le projet garde un historique court de conversation dans Redis pour donner du
contexte au LLM. Cet agent est le premier nœud utile du graphe : il choisit
l'historique envoyé par le frontend si disponible, sinon il recharge celui qui
est stocké côté backend.
"""

from app.logger import logger
from app.memory.redis_memory import RedisMemoryService
from app.models.chat_models import AgentResult
from app.state import GraphState


class MemoryAgent:
    """Enrichit l'état LangGraph avec l'historique fourni ou stocké dans Redis."""

    def __init__(self, memory_service: RedisMemoryService):
        """Injecte le service Redis/fallback mémoire utilisé pour lire l'historique."""
        self.memory_service = memory_service

    async def run(self, state: GraphState) -> AgentResult:
        """
        Charge l'historique conversationnel et le place dans `conversation_context`.

        Priorité :
        1. historique transmis par le frontend dans `ChatRequest.history` ;
        2. historique stocké en Redis pour `conversation_id`.
        """
        owner_id = state.metadata.get("user_id")
        stored_context = await self.memory_service.get_messages(state.conversation_id, owner_id=owner_id)
        request_context = [message.model_dump() for message in state.history]
        # Le frontend reste prioritaire pour conserver la compatibilité avec l'UI actuelle.
        state.conversation_context = request_context or stored_context

        logger.bind(
            conversation_id=state.conversation_id,
            request_context_messages=len(request_context),
            stored_context_messages=len(stored_context),
        ).info("Memory agent completed.")

        return AgentResult(
            agent="memory",
            output=f"Loaded {len(state.conversation_context)} context messages.",
            metadata={
                "request_context_messages": len(request_context),
                "stored_context_messages": len(stored_context),
            },
        )
