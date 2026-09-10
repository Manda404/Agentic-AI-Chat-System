"""Authenticated chat and conversation routes. POST /api/v1/chat delegates to ChatWorkflow; GET/DELETE /api/v1/conversations/{id}/context reads or clears owner-scoped Redis history."""

from fastapi import APIRouter, Depends

from app.config.settings import settings
from app.dependencies.auth_dependencies import get_current_user
from app.dependencies.services import get_chat_workflow, get_memory_service
from app.logger import logger
from app.memory.redis_memory import RedisMemoryService
from app.models.auth_models import UserResponse
from app.models.chat_models import ChatRequest, ChatResponse, ConversationContextResponse
from app.workflows.chat_workflow import ChatWorkflow

router = APIRouter(prefix=settings.api_prefix, tags=["chat"])

@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    current_user: UserResponse = Depends(get_current_user),
    workflow: ChatWorkflow = Depends(get_chat_workflow),
) -> ChatResponse:
    """Delegate the chat request to ChatWorkflow."""
    logger.bind(
        user_id=current_user.email,
        conversation_id=request.conversation_id or "new",
        message_preview=request.message[:120],
    ).info("Chat API request received.")
    return await workflow.run(request, user_id=current_user.email)


@router.get("/conversations/{conversation_id}/context", response_model=ConversationContextResponse)
async def get_conversation_context(
    conversation_id: str,
    current_user: UserResponse = Depends(get_current_user),
    memory_service: RedisMemoryService = Depends(get_memory_service),
) -> ConversationContextResponse:
    """Return the stored role/content history of a conversation."""
    logger.bind(user_id=current_user.email, conversation_id=conversation_id).info(
        "Conversation context requested."
    )
    messages = await memory_service.get_messages(conversation_id, owner_id=current_user.email)
    return ConversationContextResponse(
        conversation_id=conversation_id,
        message_count=len(messages),
        messages=messages,
    )

@router.delete("/conversations/{conversation_id}/context", response_model=ConversationContextResponse)
async def clear_conversation_context(
    conversation_id: str,
    current_user: UserResponse = Depends(get_current_user),
    memory_service: RedisMemoryService = Depends(get_memory_service),
) -> ConversationContextResponse:
    """Permanently clear this conversation's Redis history."""
    logger.bind(user_id=current_user.email, conversation_id=conversation_id).info(
        "Conversation context cleared."
    )
    await memory_service.clear_messages(conversation_id, owner_id=current_user.email)
    return ConversationContextResponse(
        conversation_id=conversation_id,
        message_count=0,
        messages=[],
    )
