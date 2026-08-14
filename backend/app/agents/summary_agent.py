"""
Agent de résumé/réponse directe : génère une réponse LLM sans passer par
la recherche documentaire.

Malgré son nom "summary", cet agent ne fait pas un résumé au sens strict :
le prompt utilisé (`LLMPrompts.summarization`) demande au LLM de répondre
directement à la question de l'utilisateur, en tenant compte du contexte
de conversation. Dans le workflow actuel, il sert surtout aux réponses directes,
aux demandes de résumé, aux demandes de correction et aux fallbacks non RAG.
"""

from app.config.settings import settings
from app.logger import logger
from app.models.chat_models import AgentResult
from app.services.llm_service import LLMService
from app.state import GraphState

# Le décorateur Langfuse reste optionnel : en local, observe devient un no-op.
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
    """Génère une réponse LLM directe à partir du message et du contexte de conversation."""

    def __init__(self, llm_service: LLMService):
        """Injecte le service LLM utilisé pour produire la réponse directe."""
        self.llm_service = llm_service

    @observe(name="summary_agent")
    async def run(self, state: GraphState) -> AgentResult:
        """
        Appelle `LLMService.summarize` et remplit `summary_output` / `draft_answer`.

        `draft_answer` est important : il donne au critic et au safety guard une
        réponse candidate à analyser, même quand le workflow ne passe pas par RAG.
        """
        logger.bind(
            route=state.route,
            message_preview=state.user_message[:120],
            context_messages=len(state.conversation_context),
        ).info("Summary agent started.")
        # Réponse directe : pas de recherche documentaire, seulement le message + contexte court.
        context = "\n".join(
            f"{message.get('role', 'unknown')}: {message.get('content', '')}"
            for message in state.conversation_context
        )
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
