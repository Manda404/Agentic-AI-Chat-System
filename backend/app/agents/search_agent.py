"""
Agent de recherche documentaire MongoDB Atlas (full-text, Atlas Search).

Prend le message utilisateur brut, le passe tel quel à `SearchService.search`,
puis met en forme les résultats (titre, fichier, page, extrait) en un
texte lisible stocké dans `state.search_output`. Les résultats structurés
restent aussi disponibles dans `state.search_results` pour être réutilisés
par les agents suivants : retrieval hybride, reranking, compression et RAG.
"""

from app.config.settings import settings
from app.logger import logger
from app.models.chat_models import AgentResult
from app.services.search_service import SearchService
from app.state import GraphState

if settings.langfuse_enabled:
    try:
        from langfuse import observe
    except ImportError:
        def observe(*args,**kwargs):
            def decorator(func):
                return func
            return decorator if args and callable(args[0]) else decorator
else:
     def observe(*args, **kwargs):
        def decorator(func):
            return func
        return decorator if args and callable(args[0]) else decorator


class SearchAgent:
    """Cherche des documents pertinents dans MongoDB Atlas pour le message courant."""

    def __init__(self,search_service:SearchService):
        """Injecte le service MongoDB Atlas réutilisé par l'agent."""
        self.search_service = search_service

    @observe(name="search_agent")
    async def run(self, state:GraphState) -> AgentResult:
        """
        Exécute la recherche MongoDB Atlas et remplit l'état partagé.

        Étapes :
        1. appeler `SearchService.search` ;
        2. garder les résultats structurés dans `state.search_results` ;
        3. produire une version texte lisible dans `state.search_output` ;
        4. exposer les métadonnées pour le frontend.
        """
        logger.bind(route=state.route, message_preview=state.user_message[:120]).info(
            "Search agent started."
        )

        # Recherche full-text de premier niveau ; les agents suivants amélioreront le contexte.
        owner_id = state.metadata.get("user_id")
        results = await self.search_service.search(state.user_message, owner_id=owner_id)

        state.search_results = results
        lines = []
        for index, item in enumerate(results):
            # Construire une ligne lisible avec fichier/page quand ces métadonnées existent.
            location_parts = []
            if item.file_name:
                location_parts.append(item.file_name)
            if item.page_number is not None:
                location_parts.append(f"Page {item.page_number}")

            location = f" ({', '.join(location_parts)})" if location_parts else ""
            lines.append(
                f"{index + 1}. {item.title}{location} — {item.snippet}"
            )

        output = "Search results from MongoDB Atlas:\n" + "\n".join(lines) if lines else "No matching documents found."
        
        state.search_output = output
        logger.bind(results_count=len(results), index_name=self.search_service.index_name).info(
            "Search agent completed."
        )
        
        return AgentResult(
            agent="search",
            output=output,
            metadata={
                "results_count": len(results),
                "index_name" : self.search_service.index_name,
                "document_scope": settings.document_scope_mode,
                "documents": [
                    {
                        "document_id": item.document_id,
                        "title": item.title,
                        "file_name": item.file_name,
                        "page_number": item.page_number,
                        "score": item.score,
                        "snippet": item.snippet,
                    }
                    for item in results
                ],
            }
        )
 
