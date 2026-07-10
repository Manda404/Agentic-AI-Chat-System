"""
Service de recherche documentaire basé sur Elasticsearch.

Encapsule toute la logique Elasticsearch : connexion (tolérante aux
pannes — si Elasticsearch est injoignable au démarrage, le service
reste utilisable mais `available` devient `False` et toute recherche
lève une erreur explicite), création d'index, indexation en masse, et
recherche full-text multi-champs.
"""

from typing import Any, Dict, List

from app.config.settings import settings
from app.logger import logger
from app.models.chat_models import SearchResult


class SearchService:
    """Point d'accès unique à Elasticsearch pour indexer et rechercher des documents."""

    def __init__(self) -> None:
        """Tente une connexion à Elasticsearch ; échoue silencieusement (mode dégradé) si indisponible."""
        self.url = settings.elasticsearch_url
        self.index_name = settings.elasticsearch_index
        self.api_key = settings.elasticsearch_api_key
        self._client = None
        
        try:
            import importlib

            elasticsearch_module = importlib.import_module("elasticsearch")
            elasticsearch_class = getattr(elasticsearch_module, "Elasticsearch")
            
            connection_params = {
                "hosts": [self.url],
                "verify_certs": False, 
                "ssl_show_warn": False, 
            }
            
            if self.api_key:
                connection_params["api_key"] = self.api_key
            elif settings.elasticsearch_user and settings.elasticsearch_password:
                connection_params["basic_auth"] = (
                    settings.elasticsearch_user,
                    settings.elasticsearch_password
                )
            
            
            self._client = elasticsearch_class(**connection_params)
            
            
            info = self._client.info()
            logger.bind(
                index_name=self.index_name,
                url=self.url,
                version=info.get("version", {}).get("number", "unknown"),
            ).info("Elasticsearch client initialized.")

        except Exception as exc:
            logger.bind(index_name=self.index_name, url=self.url, reason=str(exc)).warning(
                "Elasticsearch client unavailable during startup."
            )
            self._client = None

    def ensure_index(self) -> None:
        """Crée l'index Elasticsearch avec son mapping s'il n'existe pas encore."""
        if not self._client:
            raise RuntimeError("Elasticsearch is not available.")
        if not self._client.indices.exists(index=self.index_name):
            logger.bind(index_name=self.index_name).info("Creating Elasticsearch index.")
            self._client.indices.create(
                index=self.index_name,
                mappings={
                    "properties": {
                        "title": {"type": "text"},
                        "snippet": {"type": "text"},
                        "category": {"type": "keyword"},
                        "source": {"type": "keyword"},
                        "page_number": {"type": "integer"},
                        "total_pages": {"type": "integer"},
                        "file_name": {"type": "keyword"},
                    }
                },
            )
            
    def bulk_index_documents(self, documents: List[Dict[str, Any]]) -> int:
        """Indexe une liste de documents en une seule requête `_bulk` (crée l'index si besoin)."""
        if not self._client:
            raise RuntimeError("Elasticsearch is not available.")
        logger.bind(index_name=self.index_name, document_count=len(documents)).info(
            "Bulk index started."
        )
        self.ensure_index()
        operations: List[Dict[str, Any]] = []
        for document in documents:
            operations.append({"index": {"_index": self.index_name}})
            operations.append(document)
        response = self._client.bulk(operations=operations, refresh=True)
        if response.get("errors"):
            logger.bind(index_name=self.index_name).error("Bulk indexing completed with errors.")
            raise RuntimeError("Bulk indexing completed with errors.")
        logger.bind(index_name=self.index_name, document_count=len(documents)).info(
            "Bulk index completed."
        )
        return len(documents)


    async def search(self, query: str) -> List[SearchResult]:
        """Recherche full-text (multi_match) sur title/snippet/category, top 5 résultats."""
        if not self._client:
            raise RuntimeError("Elasticsearch is not available. Please ingest data and start Elasticsearch.")
        logger.bind(index_name=self.index_name, query_preview=query[:120]).info(
            "Elasticsearch query started."
        )
        try:
            response = self._client.search(
                index=self.index_name,
                query={
                    "multi_match": {
                        "query": query,
                        "fields": ["title^2", "snippet", "category"],
                    }
                },
                size=5,
            )
            hits = response.get("hits", {}).get("hits", [])
            logger.bind(index_name=self.index_name, hits_count=len(hits)).info(
                "Elasticsearch query completed."
            )
            return [
                SearchResult(
                    title=hit.get("_source", {}).get("title", "Untitled"),
                    snippet=hit.get("_source", {}).get("snippet", ""),
                    score=float(hit.get("_score", 0.0)),
                    source=hit.get("_source", {}).get("source", "elasticsearch"),
                    page_number=hit.get("_source", {}).get("page_number"),
                    file_name=hit.get("_source", {}).get("file_name"),
                )
                for hit in hits
            ]
        except Exception as exc:
            logger.bind(index_name=self.index_name, query_preview=query[:120]).exception(
                "Elasticsearch query failed."
            )
            raise RuntimeError(f"Elasticsearch query failed: {exc}") from exc
        
    
    @property
    def available(self) -> bool:
     """True si la connexion Elasticsearch a réussi au démarrage (utilisé par `/health`)."""
     return self._client is not None