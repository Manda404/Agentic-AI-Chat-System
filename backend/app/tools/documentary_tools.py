"""Deux outils en lecture seule. Le scope d'accès est injecté par le serveur."""
from app.state import GraphState
from app.services.tavily_service import TavilyService


class DocumentaryTools:
    def __init__(self, retrieval, search_service):
        self.web_service = TavilyService()
        self.retrieval = retrieval
        self.search_service = search_service

    async def rechercher(self, query: str, owner_id: str | None, conversation_id: str):
        # Un état neuf à chaque recherche évite de conserver les erreurs/sélections précédentes.
        state = GraphState(conversation_id=conversation_id, user_message=query,
                           metadata={'user_id': owner_id, 'retrieval_query': query})
        await self.retrieval.run(state)
        if state.retrieval_metrics.get('search_error') and state.retrieval_metrics.get('vector_error'):
            raise RuntimeError('retrieval_unavailable')
        compressor = self.retrieval.compressor
        terms = compressor._terms(query)
        documents = [item.model_copy(update={
            'snippet': compressor._select_evidence(item.snippet, terms, 500), 'embedding': None,
        }) for item in state.selected_documents if item.document_id]
        return documents, state.retrieval_metrics

    async def lire_passage(self, passage_id: str, owner_id: str | None, allowed_ids: set[str]):
        if passage_id not in allowed_ids:
            raise ValueError('passage_not_discovered')
        # Nouvelle lecture filtrée : les permissions peuvent avoir changé depuis la recherche.
        document = await self.search_service.get_passage(passage_id, owner_id=owner_id)
        if document is None:
            raise PermissionError('passage_unavailable')
        return document

    @property
    def web_available(self):
        return self.web_service.available

    async def rechercher_web(self, query):
        return await self.web_service.search(query)
