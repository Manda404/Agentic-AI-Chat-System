"""MongoDB Atlas text retrieval. Send the current retrieval query to SearchService.search, retain structured hits in state.search_results and render source metadata into state.search_output for downstream retrieval and diagnostics."""

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
    """Find relevant MongoDB Atlas documents for the current query."""

    def __init__(self,search_service:SearchService):
        """Inject the shared MongoDB Atlas search service."""
        self.search_service = search_service

    @observe(name="search_agent")
    async def run(self, state:GraphState) -> AgentResult:
        """Run SearchService.search, store structured hits, render title/file/page/excerpts and expose result metadata."""
        retrieval_query = state.metadata.get("retrieval_query") or state.user_message
        logger.bind(route=state.route, message_preview=retrieval_query[:120]).info(
            "Search agent started."
        )

        # Initial text retrieval; downstream components refine the context.
        owner_id = state.metadata.get("user_id")
        results = await self.search_service.search(retrieval_query, owner_id=owner_id)

        state.search_results = results
        lines = []
        for index, item in enumerate(results):
            # Render a readable line with file/page metadata when available.
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
                "retrieval_query": retrieval_query,
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
 
