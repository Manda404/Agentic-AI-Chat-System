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

Le reranker combine deux signaux :
- score lexical : score Elasticsearch + bonus si les termes de la question
  apparaissent dans le titre/snippet ;
- score sémantique : similarité cosinus entre l'embedding de la question et
  l'embedding de chaque document candidat, calculés via le HuggingFace
  Router (`HuggingFaceEmbeddingService`, modèle `MODEL_EMBEDDING`, défaut
  `BAAI/bge-small-en-v1.5`).

Le score sémantique est optionnel (`SEMANTIC_RERANKER_ENABLED`) et retombe
silencieusement sur le score lexical seul si l'appel embeddings échoue
(clé API absente, quota, timeout) — aucune exception ne remonte à
l'utilisateur.

Résultat final borné à `MAX_RAG_DOCUMENTS`.

Métriques produites :
- `retrieved_count`
- `reranked_count`
- `top_score`
- `sources_used`
- `semantic_reranking_used`

## Compression

`ContextCompressionAgent` limite le contexte envoyé au LLM avec `MAX_RAG_CONTEXT_CHARS`. Il garde les titres, fichiers et pages pour préserver la traçabilité.

## Limites

Le projet ne contient pas encore :
- index vectoriel (le `VectorStorePort` reste branché sur `NullVectorStore`) ;
- reranker cross-encoder dédié (le scoring sémantique utilise des embeddings
  bi-encodeur, pas un cross-encoder) ;
- citations phrase par phrase ;
- évaluation groundedness automatique avancée.
