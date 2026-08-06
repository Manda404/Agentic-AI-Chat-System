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
- résultats full-text (MongoDB Atlas Search) ;
- résultats vectoriels via `VectorStorePort`, implémenté par `MongoVectorStore` (MongoDB Atlas Vector Search).

Les deux stores tournent sur la même collection MongoDB (`documents`) : le full-text est indexé par `documents_search`, les vecteurs par `documents_vector` (champ `embedding`). Si la connexion Mongo est indisponible, `HybridRetrieverAgent` continue avec les seuls résultats déjà présents dans `state.search_results` (dégradation silencieuse, pas d'exception).

## Reranking

Le reranker combine deux signaux :
- score lexical : score full-text (MongoDB Atlas Search) + bonus si les termes de la question
  apparaissent dans le titre/snippet ;
- score sémantique : similarité cosinus entre l'embedding de la question et
  l'embedding de chaque document candidat, calculés via la route
  `pipeline/feature-extraction` du HuggingFace Router
  (`HuggingFaceEmbeddingService`, modèle `MODEL_EMBEDDING`, défaut
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
- reranker cross-encoder dédié (le scoring sémantique utilise des embeddings
  bi-encodeur, pas un cross-encoder) ;
- citations phrase par phrase ;
- évaluation groundedness automatique avancée.
