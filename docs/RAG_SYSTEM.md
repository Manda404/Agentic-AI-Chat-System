# Système RAG — fonctionnement détaillé et limites connues

Ce document explique en détail comment fonctionne le pipeline RAG (Retrieval-Augmented
Generation) de ce projet, étage par étage, et liste les erreurs/limites identifiées
dans le code actuel. Pour une vue d'ensemble plus courte, voir [`docs/RAG.md`](../../../docs/RAG.md).

## Vue d'ensemble

Le RAG n'est pas un seul agent : c'est une chaîne de 5 agents, chacun dans son
propre fichier, orchestrés par `ChatWorkflow` ([`backend/app/workflows/chat_workflow.py`](../workflows/chat_workflow.py)) :

```
SearchAgent → HybridRetrieverAgent → RerankerAgent → ContextCompressionAgent → RAGAgent
                                                                                    ↓
                                                                    LLMCriticAgent → SafetyGuardAgent → FinalAnswerAgent
```

Ce pipeline n'est déclenché que si `LLMPlannerAgent` décide que la question nécessite
une recherche documentaire (`requires_rag=True` dans `PlannerDecision`). Pour une
salutation ou une question générale, le graphe saute directement vers `SummaryAgent`.

Chaque étage lit et écrit dans un état partagé, `GraphState`
([`backend/app/state/graph_state.py`](../state/graph_state.py)), qui traverse tout le graphe LangGraph.

---

## 1. SearchAgent — recherche full-text

**Fichier :** [`search_agent.py`](search_agent.py) · **Dépend de :** [`SearchService`](../services/search_service.py)

- Envoie `state.user_message` tel quel à MongoDB Atlas via `SearchService.search()`.
- Requête d'agrégation `$search` (Atlas Search) en `compound`/`text` sur les champs
  `title` (boost 2x), `snippet`, `category`.
- Résultat : jusqu'à **5 documents** (valeur codée en dur, voir *Erreur #1* plus bas),
  stockés dans `state.search_results` (objets `SearchResult` structurés) et
  reformatés en texte lisible dans `state.search_output`.
- Si MongoDB Atlas est indisponible ou l'index Atlas Search n'existe pas,
  `SearchService.search()` lève une exception — mais le nœud du graphe est
  configuré avec `swallow_errors=True`, donc le workflow continue avec
  `search_results = []` plutôt que de planter.

## 2. HybridRetrieverAgent — fusion full-text + vectoriel

**Fichier :** [`hybrid_retriever_agent.py`](hybrid_retriever_agent.py) · **Dépend de :** [`VectorStorePort`](../services/retrieval_ports.py)

- Fusionne les résultats full-text (MongoDB Atlas Search) avec ceux de la
  recherche vectorielle, via `MongoVectorStore` (implémentation de
  `VectorStorePort` branchée par défaut dans `ChatWorkflow`, MongoDB Atlas
  Vector Search sur le champ `embedding`).
- Si la connexion Mongo échoue ou que l'embedding de la requête ne peut pas
  être calculé, `MongoVectorStore.similarity_search` retourne `[]` plutôt que
  de lever une exception : l'agent continue alors avec les seuls résultats
  full-text (dégradation silencieuse, pas un vrai `NullVectorStore` par défaut
  comme avant la migration vers MongoDB Atlas).
- Déduplique via une clé `(titre, fichier ou source, numéro de page)` — voir
  *Erreur #3* pour un cas où cette clé peut fusionner deux documents différents.
- Tronque à `limit` (8 par défaut) et met à jour `state.retrieval_metrics`
  (`full_text_count`, `vector_count`, `hybrid_count`).

## 3. RerankerAgent — réordonnancement

**Fichier :** [`reranker_agent.py`](reranker_agent.py) · **Dépend de :** [`EmbeddingService`](../services/retrieval_ports.py)

Combine deux scores par document :

1. **Score lexical** (toujours calculé) : score full-text brut (MongoDB Atlas
   Search, `searchScore`) + bonus `0.25` par mot de la question retrouvé dans
   le titre/snippet.
2. **Score sémantique** (si `SEMANTIC_RERANKER_ENABLED=true`) : similarité
   cosinus entre l'embedding de la question et l'embedding de chaque document,
   calculés via `HuggingFaceEmbeddingService` (route `pipeline/feature-extraction`
   du HuggingFace Router, modèle `MODEL_EMBEDDING`, défaut
   `BAAI/bge-small-en-v1.5`), en un seul appel batch.

Score final = `lexical + 2.0 × cosinus` (voir *Erreur #6* sur ce facteur `2.0`).
Si l'appel d'embeddings échoue (quota, timeout, modèle indisponible), l'agent
retombe silencieusement sur le score lexical seul — aucune exception ne
remonte à l'utilisateur.

Résultat trié et tronqué à `MAX_RAG_DOCUMENTS` dans `state.reranked_results`.
Métriques : `retrieved_count`, `reranked_count`, `top_score`, `sources_used`,
`semantic_reranking_used`.

## 4. ContextCompressionAgent — compression du contexte

**Fichier :** [`context_compression_agent.py`](context_compression_agent.py)

- Prend `state.reranked_results`, garde titre/fichier/page pour la traçabilité,
  et tronque les snippets pour respecter `MAX_RAG_CONTEXT_CHARS` (4000 par défaut).
- Par défaut (`use_llm=False`), la compression est **purement locale** : simple
  troncature caractère par caractère, sans sélection intelligente des passages
  les plus pertinents (voir *Erreur #7*).
- Un mode LLM existe (`use_llm=True`) mais n'est jamais activé dans
  `ChatWorkflow` aujourd'hui — la compression LLM (`LLMService.compress_context`)
  est du code mort en pratique.
- Résultat dans `state.compressed_context`, repris par `RAGAgent`.

## 5. RAGAgent — génération de la réponse ancrée

**Fichier :** [`rag_agent.py`](rag_agent.py)

- Utilise `state.reranked_results` (ou `search_results` en repli) comme source
  de vérité.
- **Garde-fou anti-hallucination** : si aucun document n'est disponible, renvoie
  directement un message explicite sans jamais appeler le LLM.
- Sinon, appelle `LLMService.grounded_answer(question, documents, historique)` —
  un prompt qui interdit explicitement au LLM de répondre en dehors des
  documents fournis.
- Ajoute une section `Sources:` (3 meilleurs documents) à la réponse, que
  l'appel réussisse ou échoue.
- Si le LLM échoue, retombe sur `state.search_output` brut plutôt que de
  planter tout le workflow.

## Après le RAG : Critic → Safety → FinalAnswer

- `LLMCriticAgent` évalue la réponse (`groundedness_score`, `relevance_score`,
  `clarity_score`) et peut déclencher **un seul** essai de correction
  (`retry_rag`) si le score est insuffisant.
- `SafetyGuardAgent` rédige les secrets évidents (clé API, token, etc.) avant
  finalisation.
- `FinalAnswerAgent` assemble la réponse finale envoyée au frontend.

## Configuration qui influence le RAG

| Variable | Effet | Défaut |
|---|---|---|
| `MAX_RAG_DOCUMENTS` | Nombre de documents gardés après reranking | 5 |
| `MAX_RAG_CONTEXT_CHARS` | Taille max du contexte envoyé au LLM | 4000 |
| `SEMANTIC_RERANKER_ENABLED` | Active le scoring sémantique (embeddings) | true |
| `MODEL_EMBEDDING` | Modèle HF utilisé pour les embeddings | `BAAI/bge-small-en-v1.5` |
| `MONGODB_SEARCH_INDEX` | Index Atlas Search interrogé par `SearchService` | `documents_search` |
| `MONGODB_VECTOR_INDEX` | Index Atlas Vector Search interrogé par `MongoVectorStore` | `documents_vector` |

---

## Erreurs et limites identifiées

Classées par impact décroissant. Chacune référence le fichier et le
mécanisme exact en cause.

### 1. `MAX_RAG_DOCUMENTS` n'a aucun effet sur le nombre de documents *récupérés* en full-text
**Fichier :** [`search_service.py:94`](../services/search_service.py) (`$limit: 5` codé en dur dans le pipeline `$search`)

`SearchService.search()` fixe `$limit: 5` sans lire `settings.max_rag_documents`.
Résultat : même si vous configurez `MAX_RAG_DOCUMENTS=20`, la branche full-text
ne renverra jamais plus de 5 candidats. Le setting ne contrôle en pratique que
la troncature *après* reranking, pas la profondeur de recherche full-text.

### 2. `HybridRetrieverAgent.limit=8` — ✅ résolu par la migration vers MongoDB Atlas
**Fichier :** [`hybrid_retriever_agent.py:25`](hybrid_retriever_agent.py)

Avant la migration vers MongoDB Atlas, ce paramètre était inopérant : le
full-text était plafonné à 5 (erreur #1) et le store vectoriel par défaut
(`NullVectorStore`) retournait toujours `[]`, donc la liste fusionnée ne
dépassait jamais 5 éléments et `[: self.limit]` (limite à 8) ne s'activait
jamais. Depuis que `MongoVectorStore` (Atlas Vector Search) est branché par
défaut dans `ChatWorkflow`, la branche vectorielle peut retourner jusqu'à 8
résultats supplémentaires : le total pré-dédup peut donc dépasser 8, et la
troncature `[: self.limit]` s'applique réellement (vérifié en pratique :
`full_text_count=5`, `vector_count=8`, `hybrid_count=8` sur une requête réelle).

### 3. Risque de collision de déduplication pour les documents issus de CSV
**Fichiers :** [`hybrid_retriever_agent.py:66`](hybrid_retriever_agent.py) + [`csv_ingest.py`](../data_ingest/csv_ingest.py)

La clé de dédup est `(titre, file_name ou source, page_number)`. Pour les
PDF, `title` inclut le numéro de page (`"fichier - Page 3"`) donc pas de
collision possible. Mais `load_documents_from_csv()` ne renseigne **jamais**
`file_name` ni `page_number`, et `source` retombe sur la chaîne littérale
`"csv-ingest"` si la colonne `source` n'est pas fournie dans le CSV. Deux
lignes CSV qui partagent le même `title` (ex. catégories dupliquées) et pas
de colonne `source` distincte produiront **la même clé** → une des deux
lignes sera silencieusement supprimée par `_merge()`, même si leur contenu
diffère.

### 4. `RAGAgent` rapporte un `sources_count` trompeur
**Fichier :** [`rag_agent.py:67`](rag_agent.py)

`metadata["sources_count"] = len(state.search_results)` utilise le nombre de
résultats *bruts* de recherche, pas `len(documents)` (= ce qui a réellement
servi à générer la réponse, après reranking). Si le reranker filtre des
documents, la métrique affichée au frontend/observabilité surestime le
nombre de sources réellement utilisées pour ancrer la réponse.

### 5. Troncature "dure" du contexte compressé peut couper une citation en plein milieu
**Fichier :** [`context_compression_agent.py:50`](context_compression_agent.py)

`state.compressed_context = compressed[: self.max_chars]` coupe la chaîne
finale au caractère près, sans respecter les frontières de blocs. Si le
dernier document inclus dépasse tout juste la limite, son label
`[n] Titre (fichier, page X)` peut être tronqué en plein milieu — le LLM
reçoit alors un fragment de citation illisible pour ce dernier document.

### 6. Pondération du score sémantique non calibrée
**Fichier :** [`reranker_agent.py`](reranker_agent.py) (`SEMANTIC_WEIGHT = 2.0`)

Le score final additionne le score lexical (issu du score MongoDB Atlas Search,
BM25 via Lucene, dont l'échelle dépend du corpus et peut dépasser largement 2)
et le score sémantique (cosinus ∈ [-1, 1], multiplié par 2, donc borné à
[-2, 2]). Sur un corpus où les scores full-text sont élevés, la contribution
sémantique peut devenir négligeable dans le classement final. Ce risque est
d'autant plus pertinent maintenant que la recherche vectorielle contribue
réellement des documents au retrieval (voir erreur #2 résolue) : un mauvais
équilibrage pourrait faire dominer systématiquement les résultats full-text
sur les résultats purement sémantiques lors du tri final. Cette pondération
mériterait d'être testée/calibrée sur des données réelles plutôt que fixée
arbitrairement.

### 7. La compression de contexte est une troncature naïve, pas une sélection intelligente
**Fichier :** [`context_compression_agent.py`](context_compression_agent.py) (`use_llm=False` par défaut, jamais activé dans `chat_workflow.py`)

`_local_compress` coupe chaque snippet à un budget de caractères sans
comprendre le contenu. Si l'information pertinente pour répondre à la
question se trouve après le point de troncature dans un snippet long, elle
est perdue avant même d'atteindre le LLM — sans qu'aucun signal n'indique
que cela s'est produit.

---

## Pistes de correction (non appliquées, à discuter)

- #1 : lire `settings.max_rag_documents` (ou une nouvelle variable dédiée,
  ex. `SEARCH_TOP_K`) dans `SearchService.search()` au lieu de `$limit: 5` fixe.
- #3 : générer un `source` unique par ligne CSV par défaut (ex. `f"csv-ingest:{file_path}:{index}"`)
  au lieu du littéral partagé `"csv-ingest"`.
- #4 : remplacer `len(state.search_results)` par `len(documents)` dans `RAGAgent`.
- #5 : tronquer par bloc complet (`chunks`) plutôt que par caractère brut sur
  la chaîne finale déjà assemblée.
- #6 : mesurer la distribution réelle des scores MongoDB Atlas Search sur le
  corpus du projet avant de choisir un poids, ou normaliser les deux scores sur
  une échelle commune (ex. min-max) avant de les combiner.
- #7 : activer `use_llm=True` pour `ContextCompressionAgent` sur les cas où
  la qualité prime sur la latence/coût, avec le même pattern de repli
  déterministe déjà en place.
