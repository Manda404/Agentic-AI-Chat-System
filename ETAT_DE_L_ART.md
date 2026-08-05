# État de l’art du projet — Agentic RAG Platform

## 1. Objectif du document

Ce document présente l’état de l’art du projet **Agentic RAG Platform** après son évolution vers une architecture agentique plus proche d’un système **production-grade**.

Il décrit :
- l’architecture actuelle du projet ;
- le workflow LangGraph réellement exécuté ;
- les agents disponibles et leur rôle ;
- le niveau actuel du RAG ;
- les apports en observabilité, sécurité, évaluation et configuration ;
- les écarts restants avec une plateforme agentique de production complète ;
- les prochaines évolutions recommandées.

Le projet n’est plus seulement un starter multi-agent simple. Il possède désormais :
- une orchestration **LangGraph** réelle ;
- un planner LLM validé avec fallback déterministe ;
- un tool router explicite ;
- un pipeline RAG plus avancé ;
- un critic LLM avec fallback ;
- un garde-fou de sécurité ;
- des métriques de retrieval et de latence ;
- un checkpointing LangGraph optionnel ;
- une documentation dédiée à l’architecture, aux agents, au RAG, à l’évaluation et à la production readiness.

Le système conserve néanmoins l’esprit pédagogique du projet : le code reste lisible, les dépendances lourdes ne sont pas imposées, et les composants avancés sont introduits de façon progressive.

---

## 2. Vision générale du projet

Le projet est une application de chat IA composée de :
- un frontend **Next.js / React / TypeScript** ;
- un backend **FastAPI** ;
- une orchestration **LangGraph** ;
- une mémoire conversationnelle et un cache via **Redis** ;
- une recherche documentaire via **Elasticsearch** ;
- un fournisseur LLM via **HuggingFace Router** compatible OpenAI ;
- un cockpit frontend de debug ;
- une couche d’évaluation légère ;
- une configuration production-oriented sans casser le mode local.

Vue simplifiée :

```text
Utilisateur
    ↓
Frontend Next.js
    ↓
Backend FastAPI
    ↓
ChatWorkflow LangGraph
    ↓
MemoryAgent
    ↓
LLMPlannerAgent
    ↓
ToolRouterAgent
    ↓
Search / Retrieval / RAG / Direct Answer
    ↓
LLMCriticAgent
    ↓
SafetyGuardAgent
    ↓
FinalAnswerAgent
    ↓
Redis history/cache + optional LangGraph checkpoint
    ↓
ChatResponse compatible frontend
```

L’objectif fonctionnel reste le même : recevoir un message utilisateur et produire une réponse claire. La différence importante est que le système décide désormais plus explicitement :
- quelle intention est détectée ;
- quels outils sont nécessaires ;
- si une recherche documentaire est utile ;
- si le RAG doit être utilisé ;
- si la réponse doit être critiquée ;
- si une vérification de sécurité est nécessaire ;
- quelles métriques doivent être exposées au cockpit de debug.

---

## 3. Architecture actuelle

### 3.1 Vue d’ensemble détaillée

```text
Frontend Next.js
    ↓ HTTP / JSON
Backend FastAPI
    ↓
ChatWorkflow
    ↓
LangGraph StateGraph
    ↓
MemoryAgent
    ↓
LLMPlannerAgent
    ↓
ToolRouterAgent
    ↓
Conditional routing
    ├── Greeting
    ├── SummaryAgent / direct answer
    └── SearchAgent
            ↓
        HybridRetrieverAgent
            ↓
        RerankerAgent
            ↓
        ContextCompressionAgent
            ↓
        RAGAgent
    ↓
LLMCriticAgent
    ↓
SafetyGuardAgent
    ↓
FinalAnswerAgent
    ↓
ChatResponse
```

### 3.2 Organisation du backend

Le backend reste structuré par responsabilités :
- `routers/` : endpoints HTTP ;
- `models/` : modèles Pydantic ;
- `services/` : services réutilisables, notamment LLM, recherche et ports de retrieval ;
- `agents/` : agents spécialisés ;
- `workflows/` : orchestration LangGraph ;
- `state/` : état partagé du graphe ;
- `memory/` : accès Redis avec fallback mémoire ;
- `data_ingest/` : ingestion de documents CSV/PDF ;
- `evaluation/` : mini framework d’évaluation ;
- `prompts/` : prompts LLM centralisés ;
- `middleware/` : logs HTTP, sécurité, rate limiting ;
- `config/` : configuration centralisée.

### 3.3 Documentation ajoutée

Le projet contient maintenant une documentation dédiée :
- `docs/ARCHITECTURE.md`
- `docs/AGENTS.md`
- `docs/RAG.md`
- `docs/EVALUATION.md`
- `docs/PRODUCTION_READINESS.md`

Ces fichiers complètent cet état de l’art avec des vues plus opérationnelles.

---

## 4. Compatibilité API

Le point d’entrée principal reste :

```text
POST /api/v1/chat
```

Le contrat historique reste présent :
- `conversation_id`
- `route`
- `answer`
- `agents_used`
- `agent_results`
- `cached`
- `context_messages`

Le modèle `ChatResponse` expose aussi des champs optionnels de debug et de pilotage :
- `plan`
- `critic_feedback`
- `critic_passed`
- `critic_score`
- `retrieval_metrics`
- `safety_feedback`
- `safety_passed`
- `evaluation`
- `trace_id`

Cette approche est importante : le frontend existant n’est pas cassé, mais il peut afficher davantage d’informations quand elles sont disponibles.

---

## 5. Orchestration LangGraph

### 5.1 Rôle du workflow

Le fichier central reste :

```text
backend/app/workflows/chat_workflow.py
```

Il conserve les responsabilités suivantes :
- gérer le `conversation_id` ;
- gérer le cache Redis ;
- initialiser `GraphState` ;
- exécuter le graphe LangGraph ;
- sauvegarder l’historique assistant ;
- construire le `ChatResponse`.

### 5.2 Graphe actuel

Le workflow construit un `StateGraph(GraphStateDict)` avec les nœuds suivants :

```text
memory
planner
tool_router
greeting
search
hybrid_retriever
reranker
context_compression
summary
rag
critic
safety
prepare_rag_retry
prepare_summary_retry
final_answer
```

Le graphe est compilé à l’initialisation du workflow.

### 5.3 Checkpointing optionnel

Le projet supporte un checkpoint LangGraph optionnel :

```env
LANGGRAPH_CHECKPOINT_ENABLED=false
LANGGRAPH_CHECKPOINT_BACKEND=memory
```

Par défaut, le mode reste simple et local. Si le checkpoint est activé avec le backend `memory`, le graphe est compilé avec `MemorySaver`.

Quand le checkpoint est actif, l’exécution reçoit :

```python
{"configurable": {"thread_id": conversation_id}}
```

Cela prépare le projet à des workflows plus longs, auditables ou reprenables, sans imposer de persistance lourde dès maintenant.

### 5.4 Boucle de correction bornée

Le système conserve une seule tentative de correction :
- si le critic accepte la réponse, le workflow passe au safety guard ;
- si le critic refuse et qu’aucune correction n’a encore été tentée, le graphe peut relancer `rag` ou `summary` ;
- si une correction a déjà été tentée, le workflow passe au safety guard ;
- aucune boucle infinie n’est possible dans le design actuel.

---

## 6. État partagé : GraphState

### 6.1 Rôle de GraphState

`GraphState` transporte toutes les informations de la requête à travers le graphe.

Il contient désormais :

```python
conversation_id: str
transaction_id: str | None
user_message: str
history: list
conversation_context: list
route: str | None
intent: str | None
plan: list[str]
tools: list[str]
planner_decision: PlannerDecision | None
search_results: list
reranked_results: list
compressed_context: str | None
search_output: str | None
summary_output: str | None
rag_output: str | None
draft_answer: str | None
critic_feedback: str | None
critic_passed: bool
critic_score: float | None
safety_feedback: str | None
safety_passed: bool
final_answer: str | None
agents_used: list[str]
agent_results: list
retrieval_metrics: dict
evaluation: dict
error: str | None
correction_attempted: bool
metadata: dict
```

### 6.2 Double représentation

Le projet conserve deux représentations :
- `GraphState` : dataclass lisible pour les agents ;
- `GraphStateDict` : `TypedDict` compatible LangGraph.

Cette double représentation est un bon compromis :
- les agents restent faciles à comprendre ;
- LangGraph manipule un schéma dictionnaire explicite ;
- les conversions sont centralisées ;
- les modèles Pydantic sont reconstruits proprement dans `from_mapping()`.

### 6.3 Traçabilité interne

Chaque agent peut écrire dans :
- `agent_results` pour exposer sa sortie brute ;
- `agents_used` pour tracer le chemin suivi ;
- `retrieval_metrics` pour les métriques RAG ;
- `evaluation` pour les résultats critic/safety/cache/latence ;
- `metadata` pour les détails non contractuels.

---

## 7. Agents actuels

### 7.1 MemoryAgent

Responsabilité :
- charger l’historique conversationnel depuis Redis ;
- utiliser l’historique fourni par le frontend s’il est présent ;
- enrichir `conversation_context`.

Positionnement :
- mémoire courte conversationnelle ;
- compatible avec Redis ;
- fallback mémoire géré par `RedisMemoryService`.

Limite :
- pas encore de mémoire sémantique longue durée.

### 7.2 LLMPlannerAgent

Responsabilité :
- analyser la demande utilisateur ;
- produire un plan structuré ;
- décider si retrieval, RAG, critic et safety sont nécessaires ;
- choisir les outils attendus ;
- fournir une raison courte.

Ce planner est désormais le seul point de classification d’intention du
workflow. Un agent superviseur existait auparavant en amont pour produire une
route rapide par mots-clés/LLM, mais il a été retiré : sa sortie n’était
utilisée que comme indice textuel dans le prompt du planner, et était de
toute façon toujours écrasée par `ToolRouterAgent` une fois le plan produit —
c’était un appel LLM supplémentaire (coût + latence) pour un résultat sans
effet structurel sur le graphe. Le fallback par mots-clés du superviseur
(greeting/summary/planning/correction) a été repris directement dans le
fallback déterministe du planner, donc la robustesse en cas de panne LLM
reste identique.

Sortie validée par Pydantic :

```json
{
  "intent": "document_qa",
  "requires_retrieval": true,
  "requires_rag": true,
  "requires_critic": true,
  "requires_safety": true,
  "steps": [
    "load_memory",
    "search_documents",
    "hybrid_retrieve",
    "rerank_results",
    "compress_context",
    "generate_grounded_answer",
    "critic_review",
    "safety_review",
    "final_answer"
  ],
  "tools": [
    "memory",
    "search",
    "hybrid_retriever",
    "reranker",
    "compressor",
    "rag",
    "critic",
    "safety"
  ],
  "reason": "Default document question plan."
}
```

Point important :
- si le LLM échoue ;
- si le JSON est invalide ;
- si la validation Pydantic échoue ;

alors l’agent produit un fallback déterministe.

Cette approche est plus proche des architectures modernes que le planner précédent, qui était entièrement déterministe.

### 7.3 ToolRouterAgent

Responsabilité :
- lire `PlannerDecision` ;
- convertir l’intention en route LangGraph ;
- éviter les appels d’outils inutiles ;
- garantir un fallback sûr.

Routes de sortie :
- `greeting`
- `direct_answer`
- `document_qa`
- `rag`
- `fallback`

Il agit comme un pont entre la décision abstraite du planner et les transitions concrètes du graphe.

### 7.4 SearchAgent

Responsabilité :
- interroger Elasticsearch ;
- récupérer les documents candidats ;
- conserver les métadonnées utiles.

Métadonnées exposées :
- titre ;
- fichier ;
- page ;
- score ;
- snippet.

Il reste la base full-text du RAG.

### 7.5 HybridRetrieverAgent

Responsabilité :
- fusionner les résultats full-text Elasticsearch ;
- intégrer une recherche vectorielle si disponible ;
- normaliser les résultats ;
- exposer des métriques.

Le projet prépare deux ports :
- `EmbeddingService`
- `VectorStorePort`

Par défaut, le système utilise `NullVectorStore`, donc aucune dépendance lourde n’est imposée.

Métriques produites :
- `full_text_count`
- `vector_count`
- `hybrid_count`

Positionnement :
- l’architecture est prête pour une recherche hybride ;
- la recherche vectorielle réelle reste à brancher plus tard.

### 7.6 RerankerAgent

Responsabilité :
- filtrer les documents ;
- réordonner les résultats ;
- limiter le nombre de sources envoyées au LLM.

Implémentation actuelle :
- score lexical : score Elasticsearch + bonus si les termes de la question apparaissent dans le titre ou le snippet ;
- score sémantique optionnel (`SEMANTIC_RERANKER_ENABLED`) : similarité cosinus entre l’embedding de la question et celui de chaque document, calculés via `HuggingFaceEmbeddingService` (réutilise le client HuggingFace Router déjà configuré, modèle `MODEL_EMBEDDING`) ;
- si l’appel d’embeddings échoue, repli silencieux sur le score lexical seul ;
- limitation via `MAX_RAG_DOCUMENTS`.

Métriques produites :
- `retrieved_count`
- `reranked_count`
- `top_score`
- `sources_used`
- `semantic_reranking_used`

Positionnement :
- ce n’est pas encore un cross-encoder dédié (le scoring sémantique utilise des embeddings bi-encodeur) ;
- mais le reranking dispose maintenant d’un vrai signal sémantique, pas seulement lexical.

Détail complet et limites connues : [backend/app/agents/RAG_SYSTEM.md](backend/app/agents/RAG_SYSTEM.md).

### 7.7 ContextCompressionAgent

Responsabilité :
- réduire les snippets trop longs ;
- garder les passages utiles ;
- limiter le contexte envoyé au LLM ;
- conserver les labels source.

Configuration :

```env
MAX_RAG_CONTEXT_CHARS=4000
```

L’agent peut utiliser une compression locale. Une compression LLM existe comme point d’extension, mais n’est pas forcée par défaut.

### 7.8 SummaryAgent

Responsabilité :
- produire une réponse directe ;
- utiliser le contexte conversationnel ;
- remplir `summary_output` et `draft_answer`.

Il est utilisé pour :
- réponses directes ;
- résumés ;
- analyses simples ;
- demandes de correction ;
- fallback si la route est inconnue ou non documentaire.

### 7.9 RAGAgent

Responsabilité :
- utiliser les documents rerankés ou les résultats de recherche ;
- utiliser le contexte compressé si disponible ;
- appeler `LLMService.grounded_answer()` ;
- produire une réponse ancrée dans les documents ;
- conserver les sources.

Le RAG actuel répond à partir de :
- `reranked_results` si disponibles ;
- sinon `search_results` ;
- `compressed_context` si disponible ;
- sinon un formatage direct des documents.

Comportement si aucun document n’est disponible :
- l’agent répond clairement que l’information n’a pas été trouvée dans les documents indexés ;
- il évite de fabriquer une réponse documentaire.

### 7.10 LLMCriticAgent

Responsabilité :
- évaluer la réponse provisoire ;
- vérifier la pertinence ;
- vérifier la clarté ;
- vérifier le support documentaire si des sources sont disponibles ;
- produire un score.

Sortie structurée :

```json
{
  "passed": true,
  "score": 0.95,
  "groundedness_score": 0.9,
  "relevance_score": 1.0,
  "clarity_score": 0.95,
  "issues": [],
  "recommendation": "accept",
  "feedback": "Answer is relevant and grounded."
}
```

Si le LLM critic échoue, l’agent bascule vers `CriticAgent`, le critic déterministe existant.

### 7.11 SafetyGuardAgent

Responsabilité :
- détecter les secrets évidents ;
- masquer les clés API, tokens bearer, mots de passe ou clés privées ;
- éviter de retourner des informations sensibles ;
- produire un feedback de sécurité.

Sortie structurée :

```json
{
  "passed": true,
  "issues": [],
  "redacted": false,
  "feedback": "No safety issue detected."
}
```

Le safety guard reste léger. Il ne remplace pas une vraie revue sécurité, mais il introduit un garde-fou utile pour un système proche production.

### 7.12 FinalAnswerAgent

Responsabilité :
- choisir la meilleure réponse disponible ;
- intégrer les notes de critic si besoin ;
- intégrer les notes de safety si besoin ;
- produire `final_answer`.

Cet agent garde la finalisation hors du workflow principal, ce qui rend le graphe plus lisible.

---

## 8. Pipeline RAG actuel

### 8.1 Vue pipeline

```text
Document CSV/PDF
    ↓
Ingestion
    ↓
Elasticsearch
    ↓
SearchAgent
    ↓
HybridRetrieverAgent
    ↓
RerankerAgent
    ↓
ContextCompressionAgent
    ↓
RAGAgent
    ↓
LLMCriticAgent
    ↓
SafetyGuardAgent
    ↓
FinalAnswerAgent
```

### 8.2 Ce qui est déjà en place

Le projet couvre maintenant plusieurs briques avancées :
- recherche full-text ;
- interface de recherche vectorielle future ;
- fusion de résultats ;
- reranking lexical + sémantique (embeddings HuggingFace) ;
- compression de contexte ;
- génération ancrée ;
- sources visibles ;
- métriques de retrieval ;
- critic LLM ;
- fallback clair sans documents.

### 8.3 Ce qui reste à brancher

Le projet ne force pas encore :
- index vectoriel pour le retrieval (les embeddings existent déjà côté reranking via le HuggingFace Router, mais pas encore pour la recherche elle-même) ;
- cross-encoder dédié ;
- reranker LLM actif par défaut ;
- citations phrase par phrase ;
- scoring automatique de factualité à grande échelle.

C’est un choix raisonnable : le starter reste léger, mais son architecture accepte ces ajouts.

---

## 9. Mémoire, cache et checkpoint

### 9.1 Mémoire conversationnelle

Redis stocke :
- l’historique de conversation ;
- le cache des réponses ;
- les utilisateurs.

Si Redis n’est pas disponible, `RedisMemoryService` bascule vers un stockage en mémoire locale.

### 9.2 Cache de réponse

Le cache est vérifié avant l’exécution du graphe.

En cas de cache hit :
- aucun agent LangGraph n’est exécuté ;
- la réponse est retournée directement ;
- `route` vaut `cache` ;
- `evaluation.cache.hit` vaut `true`.

En cas de cache miss :
- le graphe s’exécute ;
- `evaluation.cache.hit` vaut `false`.

### 9.3 Checkpoint LangGraph

Le checkpoint est optionnel et désactivé par défaut.

Objectifs :
- préparer les workflows longs ;
- faciliter l’audit ;
- faciliter la reprise ;
- garder le local simple.

Limite actuelle :
- seul le backend mémoire est prévu ;
- un backend persistant Redis/Postgres resterait à ajouter pour un vrai environnement production.

---

## 10. Observabilité

### 10.1 Logs

Chaque nœud LangGraph logge :
- nom du node ;
- `conversation_id` ;
- route ;
- aperçu de l’entrée ;
- aperçu de la sortie ;
- durée ;
- erreur éventuelle.

Le logger Loguru conserve aussi :
- `session_id` ;
- `transaction_id` ;
- `agent_type` ;
- `route`.

### 10.2 Métriques exposées

Le projet expose maintenant dans la réponse :

```python
retrieval_metrics
evaluation
critic_score
safety_passed
safety_feedback
trace_id
```

Exemples de métriques :
- cache hit/miss ;
- latence par agent ;
- nombre de documents Elasticsearch ;
- nombre de résultats vectoriels ;
- nombre de résultats hybrid ;
- nombre de résultats rerankés ;
- top score ;
- sources utilisées ;
- taille du contexte compressé.

### 10.3 Frontend debug cockpit

Le cockpit frontend affiche désormais :
- route ;
- agents utilisés ;
- cache ;
- plan ;
- critic pass/fail ;
- critic score ;
- safety status ;
- retrieval metrics ;
- trace id ;
- sorties brutes des agents.

C’est important pour les systèmes agentiques : sans visualisation du chemin d’exécution, les réponses deviennent difficiles à expliquer.

---

## 11. Sécurité et configuration

### 11.1 Safety guard

Le safety guard masque les secrets évidents :
- clés API ;
- tokens bearer ;
- mots de passe ;
- clés privées.

Il peut aussi servir de point d’extension pour une revue LLM de sécurité.

### 11.2 Limites utilisateur et RAG

Variables ajoutées :

```env
MAX_USER_MESSAGE_CHARS=8000
MAX_RAG_CONTEXT_CHARS=4000
MAX_RAG_DOCUMENTS=5
LLM_TIMEOUT_SECONDS=60
MODEL_EMBEDDING=BAAI/bge-small-en-v1.5
SEMANTIC_RERANKER_ENABLED=true
```

Ces limites réduisent les risques :
- messages trop longs ;
- contextes RAG trop coûteux ;
- trop grand nombre de documents envoyés au LLM ;
- appels LLM bloquants trop longtemps.

### 11.3 Secret JWT

Le backend vérifie que `AUTH_SECRET_KEY` ne reste pas à une valeur par défaut hors environnement local/dev/test.

C’est une amélioration importante pour éviter une erreur classique de déploiement.

---

## 12. Évaluation

### 12.1 Mini framework

Le dossier `backend/app/evaluation/` contient :
- `cases.py`
- `metrics.py`
- `evaluator.py`

Il permet de définir des cas simples et de vérifier :
- route attendue ;
- réponse non vide ;
- présence de sources si nécessaire ;
- critic observé ;
- compatibilité `ChatResponse`.

### 12.2 Tests

Les tests utilisent des fakes pour éviter :
- vrais appels LLM ;
- vraie connexion Redis ;
- vraie connexion Elasticsearch.

Les tests couvrent notamment :
- compilation du graphe ;
- agents principaux ;
- route greeting ;
- question documentaire ;
- safety redaction ;
- nouveaux champs debug.

Dans l’environnement Python système actuel, les tests se marquent skipped si les dépendances backend ne sont pas installées. Dans un environnement backend complet, ils sont prêts à s’exécuter.

---

## 13. Positionnement par rapport à l’état de l’art

### 13.1 Ce qui est maintenant bien aligné

Le projet aligne désormais plusieurs pratiques modernes :
- orchestration par graphe d’états ;
- planner LLM avec validation ;
- fallback déterministe ;
- tool router ;
- retrieval pipeline modulaire ;
- reranking lexical + sémantique (embeddings) ;
- compression de contexte ;
- critic LLM ;
- safety guard ;
- observabilité par node ;
- métriques exposées ;
- checkpointing optionnel ;
- documentation production readiness.

Ces éléments rapprochent fortement le projet des architectures modernes construites avec LangGraph, Semantic Kernel, AutoGen, CrewAI ou des orchestrateurs internes.

### 13.2 Ce qui reste volontairement léger

Le projet reste un starter pédagogique avancé, pas encore une plateforme entreprise complète.

Sont encore simples ou préparés mais non branchés :
- store vectoriel réel pour le retrieval (les embeddings existent déjà, mais seulement côté reranking) ;
- reranker cross-encoder dédié ;
- critic hallucination avancé ;
- évaluation continue ;
- dashboard qualité ;
- checkpoint persistant ;
- politiques de sécurité complètes ;
- métriques Prometheus/OpenTelemetry.

### 13.3 Niveau de maturité actuel

| Dimension | Niveau actuel |
|---|---|
| Architecture backend | Solide et modulaire |
| Orchestration LangGraph | Avancée pour un starter |
| Planner | LLM + Pydantic + fallback |
| Tool routing | Présent |
| RAG | Modulaire avec reranking/compression |
| Retrieval hybride | Préparé, fallback full-text |
| Critic | LLM optionnel + fallback |
| Safety | Garde-fou léger présent |
| Observabilité | Bonne pour debug avancé |
| Évaluation | Mini framework présent |
| Production readiness | En progression, pas complète |

---

## 14. Forces actuelles du projet

### 14.1 Migration progressive réussie

Le projet a évolué sans repartir de zéro. Les services existants sont conservés :
- `LLMService`
- `SearchService`
- `RedisMemoryService`
- routers FastAPI ;
- modèles Pydantic ;
- middlewares ;
- logger Loguru ;
- frontend existant.

### 14.2 Architecture lisible

Chaque agent a une responsabilité claire. Le workflow reste compréhensible malgré l’ajout de briques avancées.

### 14.3 Compatibilité frontend

Les champs historiques ne sont pas cassés. Les nouveaux champs sont additifs.

### 14.4 Extensibilité RAG

Le projet peut désormais accueillir :
- embeddings ;
- vector store ;
- reranker externe ;
- compression LLM ;
- évaluation RAG plus stricte.

### 14.5 Observabilité améliorée

Les logs et le cockpit permettent de suivre :
- le plan ;
- les outils ;
- les agents ;
- les métriques ;
- les scores ;
- les erreurs.

---

## 15. Limitations et dettes techniques restantes

### 15.1 Recherche vectorielle non branchée

`VectorStorePort` existe, mais aucun store vectoriel réel n’est encore connecté.

Prochaine étape :
- choisir une solution vectorielle ;
- indexer les embeddings ;
- fusionner scores dense/sparse.

### 15.2 Reranking : score sémantique ajouté, mais non calibré

Le reranker combine désormais un score lexical et un score sémantique
(embeddings HuggingFace via similarité cosinus), avec repli automatique sur
le lexical seul si l’appel échoue. Le poids attribué au score sémantique
(`SEMANTIC_WEIGHT = 2.0` dans `reranker_agent.py`) reste une valeur fixée
arbitrairement, non calibrée sur des données réelles — sur un corpus où les
scores Elasticsearch sont élevés, la contribution sémantique peut devenir
négligeable dans le classement final.

Prochaine étape :
- mesurer la distribution réelle des scores Elasticsearch du corpus avant de choisir un poids, ou normaliser les deux scores sur une échelle commune ;
- cross-encoder dédié pour un scoring plus robuste que des embeddings bi-encodeur ;
- calibration des seuils sur des cas d’évaluation réels.

### 15.3 Critic encore dépendant de la qualité LLM

Le critic LLM peut échouer ou produire une évaluation imparfaite.

Prochaine étape :
- ajouter des tests d’évaluation critic ;
- comparer critic LLM et critic déterministe ;
- ajouter une mesure groundedness plus objective.

### 15.4 Safety guard léger

Le safety guard masque les secrets évidents mais ne remplace pas :
- une politique complète de sécurité ;
- un système DLP ;
- une revue de prompt injection ;
- une gestion stricte des secrets ;
- un audit des logs.

### 15.5 Checkpoint non persistant

Le checkpoint mémoire prépare le terrain, mais ne suffit pas pour une vraie reprise inter-process ou inter-déploiement.

Prochaine étape :
- checkpoint Redis ou Postgres ;
- audit de l’état par conversation ;
- rétention contrôlée.

### 15.6 Évaluation encore minimale

Le framework d’évaluation existe, mais il reste simple.

Prochaine étape :
- jeux de données de référence ;
- métriques retrieval ;
- métriques groundedness ;
- tests de régression prompts ;
- dashboard qualité.

---

## 16. Recommandations d’évolution

### 16.1 Brancher un vrai store vectoriel

Les embeddings existent déjà côté reranking (via le HuggingFace Router),
mais pas encore pour la recherche elle-même. Le prochain saut de qualité RAG
serait d’ajouter :
- un index vectoriel (les embeddings déjà calculés pour le reranking pourraient être réutilisés/indexés) ;
- un hybrid retrieval réel via `VectorStorePort`.

### 16.2 Ajouter un reranker robuste

Un reranker cross-encoder ou LLM améliorerait la qualité des sources envoyées au RAG.

### 16.3 Renforcer l’évaluation

Créer un jeu de questions/réponses attendu permettrait de mesurer :
- routing ;
- retrieval ;
- qualité de réponse ;
- hallucination ;
- critic ;
- safety.

### 16.4 Ajouter des métriques production

Pour une vraie production :
- Prometheus ;
- OpenTelemetry ;
- métriques coût/latence ;
- taux de cache hit ;
- taux de critic fail ;
- taux de safety redaction.

### 16.5 Ajouter un checkpoint persistant

Pour les workflows longs :
- Redis checkpoint ;
- Postgres checkpoint ;
- audit et replay.

### 16.6 Durcir la sécurité

À terme :
- CORS par environnement ;
- secrets obligatoires hors dev ;
- limites de payload ;
- sanitization logs ;
- défense prompt injection ;
- politiques d’accès par utilisateur.

---

## 17. Conclusion

Le projet **Agentic RAG Platform** a évolué d’un starter pédagogique vers une architecture agentique nettement plus robuste.

Il dispose maintenant de :
- FastAPI ;
- LangGraph ;
- Redis ;
- Elasticsearch ;
- HuggingFace Router ;
- planner LLM (avec fallback déterministe, sans superviseur redondant) ;
- tool router ;
- retrieval hybride extensible ;
- reranking lexical + sémantique (embeddings) ;
- compression de contexte ;
- RAG avec sources ;
- critic LLM ;
- safety guard ;
- checkpointing optionnel ;
- métriques de debug ;
- mini framework d’évaluation ;
- documentation dédiée.

Son positionnement actuel est celui d’un **starter production-grade avancé** : il ne prétend pas encore remplacer une plateforme agentique d’entreprise, mais il en reprend les patterns essentiels avec une complexité maîtrisée.

En résumé :

```text
FastAPI + LangGraph + Redis + Elasticsearch
+ LLM Planner + Tool Router
+ Hybrid Retrieval + Reranking + Context Compression
+ RAG + LLM Critic + Safety Guard
+ Observability + Evaluation Hooks
```

Le projet est désormais une base solide pour apprendre, démontrer, tester et faire évoluer progressivement un système multi-agent vers une architecture plus proche de la production.
