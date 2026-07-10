"""
Routes de chat : le cœur fonctionnel exposé aux utilisateurs authentifiés.

- `POST /api/v1/chat` : envoie un message au `ChatWorkflow`, qui décide
  de la route (greeting/search/summary/parallel) et orchestre les agents.
- `GET/DELETE /api/v1/conversations/{id}/context` : consulter ou vider
  l'historique d'une conversation stocké dans Redis.

Toutes ces routes exigent un utilisateur authentifié (`get_current_user`).
"""

from fastapi import APIRouter, Depends

from app.config.settings import settings
from app.dependencies.auth_dependencies import get_current_user
from app.logger import logger
from app.memory.redis_memory import RedisMemoryService
from app.models.auth_models import UserResponse
from app.models.chat_models import ChatRequest, ChatResponse, ConversationContextResponse
from app.workflows.chat_workflow import ChatWorkflow

router = APIRouter(prefix=settings.api_prefix, tags=["chat"])

workflow = ChatWorkflow()
memory_service = RedisMemoryService(settings.redis_url, settings.redis_ttl_seconds)

@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, current_user: UserResponse = Depends(get_current_user)) -> ChatResponse:
    """Point d'entrée unique du chat : délègue tout le travail au ChatWorkflow."""
    logger.bind(
        user_id=current_user.email,
        conversation_id=request.conversation_id or "new",
        message_preview=request.message[:120],
    ).info("Chat API request received.")
    return await workflow.run(request)


@router.get("/conversations/{conversation_id}/context", response_model=ConversationContextResponse)
def get_conversation_context(
    conversation_id: str,
    current_user: UserResponse = Depends(get_current_user),
) -> ConversationContextResponse:
    """Retourne l'historique brut (rôle + contenu) d'une conversation stockée dans Redis."""
    logger.bind(user_id=current_user.email, conversation_id=conversation_id).info(
        "Conversation context requested."
    )
    messages = memory_service.get_messages(conversation_id)
    return ConversationContextResponse(
        conversation_id=conversation_id,
        message_count=len(messages),
        messages=messages,
    )

@router.delete("/conversations/{conversation_id}/context", response_model=ConversationContextResponse)
def clear_conversation_context(
    conversation_id: str,
    current_user: UserResponse = Depends(get_current_user),
) -> ConversationContextResponse:
    """Supprime définitivement l'historique d'une conversation dans Redis."""
    logger.bind(user_id=current_user.email, conversation_id=conversation_id).info(
        "Conversation context cleared."
    )
    memory_service.clear_messages(conversation_id)
    return ConversationContextResponse(
        conversation_id=conversation_id,
        message_count=0,
        messages=[],
    )


