"""Direct-answer and text-summary component without document retrieval. Despite its historical name, SummaryAgent also handles general answers and transformations of supplied text, using conversation context."""

from app.config.settings import settings
from app.logger import logger
from app.models.chat_models import AgentResult
from app.services.llm_service import LLMService
from app.state import GraphState

# Langfuse is optional: observe becomes a no-op when disabled.
if settings.langfuse_enabled:
    try:
        from langfuse import observe
    except ImportError:
        def observe(*args, **kwargs):
            def decorator(func):
                return func
            return decorator if args and callable(args[0]) else decorator
else:
    def observe(*args, **kwargs):
        def decorator(func):
            return func
        return decorator if args and callable(args[0]) else decorator


class SummaryAgent:
    """Generate a direct LLM answer from the message and conversation context."""

    def __init__(self, llm_service: LLMService):
        """Inject the LLM service used for direct answers."""
        self.llm_service = llm_service

    @observe(name="summary_agent")
    async def run(self, state: GraphState) -> AgentResult:
        """Call LLMService.summarize and populate summary_output and draft_answer for subsequent validation and safety checks."""
        logger.bind(
            route=state.route,
            message_preview=state.user_message[:120],
            context_messages=len(state.conversation_context),
        ).info("Summary agent started.")
        # Direct answer: use the message and short history without document retrieval.
        context = "\n".join(
            f"{message.get('role', 'unknown')}: {message.get('content', '')}"
            for message in state.conversation_context
        )
        if state.correction_attempted and state.critic_feedback:
            context += "\nPrevious draft: " + (state.draft_answer or "") + "\nQuality feedback: " + state.critic_feedback
        summary = await self.llm_service.summarize(state.user_message, context)
        state.summary_output = summary
        state.draft_answer = summary
        logger.bind(context_messages=len(state.conversation_context)).info(
            "Summary agent completed."
        )
        return AgentResult(
            agent="summary",
            output=summary,
            metadata={"context_messages": len(state.conversation_context)},
        )
