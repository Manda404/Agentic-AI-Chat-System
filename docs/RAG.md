# RAG Avancé

## Pipeline

```text
SearchAgent
  -> HybridRetrieverAgent
  -> RerankerAgent
  -> ContextCompressionAgent
  -> RAGAgent
```

## Recherche Hybride

`HybridRetrieverAgent` combine :
- résultats full-text Elasticsearch ;
- résultats vectoriels via `VectorStorePort`, si un store est branché plus tard.

Par défaut, `NullVectorStore` retourne une liste vide. Le système reste donc compatible sans embeddings.

## Reranking

Le reranker actuel est heuristique :
- score Elasticsearch ;
- bonus si les termes de la question apparaissent dans le titre/snippet ;
- limitation à `MAX_RAG_DOCUMENTS`.

Métriques produites :
- `retrieved_count`
- `reranked_count`
- `top_score`
- `sources_used`

## Compression

`ContextCompressionAgent` limite le contexte envoyé au LLM avec `MAX_RAG_CONTEXT_CHARS`. Il garde les titres, fichiers et pages pour préserver la traçabilité.

## Limites

Le projet ne contient pas encore :
- embeddings réels ;
- index vectoriel ;
- reranker cross-encoder ;
- citations phrase par phrase ;
- évaluation groundedness automatique avancée.
