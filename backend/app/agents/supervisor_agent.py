"""
Agent superviseur : décide quelle "route" suivre pour un message utilisateur.

Le superviseur donne une première orientation rapide avant le planner LLM.
Il ne décide pas tout le workflow final : `LLMPlannerAgent` et
`ToolRouterAgent` affinent ensuite le plan et les outils. Son rôle est de
fournir un signal robuste, avec fallback par mots-clés si le LLM est
indisponible.

Routes possibles :
- "greeting" : simple salutation, pas besoin d'agents.
- "search"   : l'utilisateur veut voir les documents bruts.
- "summary"  : réponse directe du LLM, sans recherche documentaire.
- "rag"      : recherche documentaire puis réponse ancrée sur les sources.
- "planning" : demande qui appelle explicitement un plan multi-étapes.
- "correction" : demande orientée validation/correction.

Deux stratégies de décision :
1. LLM-based (par défaut) : un prompt dédié demande au LLM de répondre
   par un seul mot. Rapide, `temperature=0.0` pour rester déterministe.
2. Keyword-based (secours) : règles simples sur des mots-clés, utilisée
   automatiquement si l'appel LLM échoue (ex: API indisponible).
"""

from app.config.settings import settings
from app.logger import logger
from app.prompts import LLMPrompts
from app.services.llm_service import LLMService, ModelCapability
from typing import Optional


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


class SupervisorAgent:
    """Décide une route initiale pour aider le planner à choisir le bon chemin."""

    def __init__(self, llm_service: Optional[LLMService] = None, use_llm_routing: bool = True):
        """
        Configure le superviseur.

        Args:
            llm_service: Service LLM utilisé pour le routage intelligent.
            use_llm_routing: `False` force le routage par mots-clés, utile en tests.
        """
        self.llm_service = llm_service
        self.use_llm_routing = use_llm_routing and llm_service is not None

        if self.use_llm_routing:
            logger.info("Supervisor initialized with LLM-based routing")
        else:
            logger.info("Supervisor initialized with keyword-based routing")

    @observe(name="supervisor_decide_route")
    async def decide_route(self, message: str) -> str:
        """
        Décide de la route à suivre pour ce message (tente le LLM d'abord,
        puis retombe sur les mots-clés si l'appel LLM échoue).

        Args:
            message: Le message envoyé par l'utilisateur

        Returns:
            Le nom de la route : "greeting", "search", "summary", "rag", "planning" ou "correction"
        """
        if self.use_llm_routing:
            try:
                # Chemin nominal : demander au LLM une route courte et normalisée.
                route = await self._llm_based_routing(message)
                logger.bind(route=route, message_preview=message[:120]).info(
                    "Supervisor selected route (LLM-based)."
                )
                return route
            except Exception as e:
                logger.bind(message_preview=message[:120]).warning(
                    f"LLM routing failed, falling back to keyword-based: {e}"
                )
                # Fallback local : évite qu'une panne LLM bloque toute la conversation.
                return self._keyword_based_routing(message)
        else:
            route = self._keyword_based_routing(message)
            logger.bind(route=route, message_preview=message[:120]).info(
                "Supervisor selected route (keyword-based)."
            )
            return route

    @observe(name="llm_routing_decision")
    async def _llm_based_routing(self, message: str) -> str:
        """Demande au LLM de choisir une route en un mot, puis valide/normalise sa réponse."""
        prompt = LLMPrompts.routing_decision(user_message=message)

        logger.bind(message_preview=message[:100], prompt_length=len(prompt)).info(
            "Calling LLM for routing decision"
        )

        response = await self.llm_service.generate(
            prompt=prompt,
            capability=ModelCapability.QUESTION_ANSWERING,
            max_tokens=20,
            temperature=0.0,
        )

        logger.bind(
            raw_response=response,
            response_length=len(response),
            message_preview=message[:100],
        ).info("LLM routing response received")

        route = response.strip().lower()

        # `parallel` reste accepté pour compatibilité historique, mais devient `rag`.
        valid_routes = ["greeting", "search", "summary", "simple_llm", "rag", "parallel", "planning", "correction"]
        for valid_route in valid_routes:
            if valid_route in route:
                normalized_route = "rag" if valid_route == "parallel" else valid_route
                logger.bind(raw_response=response).info(
                    f"LLM routing extracted '{normalized_route}' from response"
                )
                return normalized_route

        logger.bind(
            llm_response=response,
            cleaned_response=route,
            message_preview=message[:100],
        ).warning("LLM returned invalid route, defaulting to 'rag'")
        return "rag"

    def _keyword_based_routing(self, message: str) -> str:
        """Routage de secours par mots-clés, utilisé si le routage LLM échoue ou est désactivé."""
        lowered = message.strip().lower()

        search_only_keywords = ["show me documents", "list documents", "display documents", "raw documents"]
        greeting_keywords = [
            "hello",
            "hi",
            "hey",
            "bonjour",
            "salut",
            "coucou",
            "good morning",
            "good afternoon",
            "good evening",
        ]
        planning_keywords = ["plan", "steps", "roadmap", "strategy", "multi-step", "étapes", "strategie"]
        correction_keywords = ["correct", "validate", "review", "critic", "fix", "corrige", "valide"]
        summary_keywords = ["summarize", "summary", "résume", "resume", "summarise"]

        # Les règles sont volontairement simples et explicables.
        if lowered in greeting_keywords:
            route = "greeting"
        elif any(keyword in lowered for keyword in search_only_keywords):
            route = "search"
        elif any(keyword in lowered for keyword in correction_keywords):
            route = "correction"
        elif any(keyword in lowered for keyword in planning_keywords):
            route = "planning"
        elif any(keyword in lowered for keyword in summary_keywords):
            route = "summary"
        else:
            route = "rag"

        logger.bind(route=route, message_preview=message[:120]).info(
            "Supervisor selected route."
        )

        return route
