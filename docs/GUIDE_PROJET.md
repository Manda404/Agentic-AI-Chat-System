# Guide de compréhension du projet — Agentic RAG Platform

> Ce guide explique le projet tel qu’il est maintenant : une plateforme RAG agentique basée sur FastAPI, LangGraph, Redis Cloud, MongoDB Atlas, HuggingFace Router et Next.js. L’objectif est de comprendre rapidement **quoi fait le projet**, **comment il fonctionne**, **où modifier quoi**, et **quels points restent à surveiller**.

---

## 1. Le projet en une phrase

Ce projet est une application de **chat IA agentique** : l’utilisateur pose une question, le backend décide quels agents appeler, récupère éventuellement des documents dans MongoDB Atlas, génère une réponse avec un LLM, vérifie la qualité avec un critic, applique un garde-fou de sécurité, puis renvoie une réponse compatible avec le frontend.

Il combine :
- un **frontend Next.js / React / TypeScript** ;
- un **backend FastAPI** ;
- une orchestration **LangGraph réelle** ;
- une mémoire et un cache via **Redis Cloud** ;
- une recherche documentaire hybride (full-text + vectorielle) via **MongoDB Atlas** (Atlas Search + Atlas Vector Search) ;
- un fournisseur LLM via **HuggingFace Router** compatible OpenAI ;
- un cockpit de debug pour observer route, agents, plan, sorties brutes, retrieval metrics, critic et safety.

L’idée générale :

```text
Message utilisateur
  -> mémoire
  -> planification LLM (avec fallback déterministe)
  -> choix des outils
  -> recherche / RAG / réponse directe
  -> critique
  -> sécurité
  -> réponse finale
```

---

## 2. Problématique résolue

Un chatbot simple répond souvent sans savoir :
- quand chercher dans une base documentaire ;
- quand répondre directement ;
- comment citer ses sources ;
- comment vérifier si la réponse est fiable ;
- comment éviter de divulguer des informations sensibles ;
- comment expliquer au développeur ce qui s’est passé.

Ce projet répond à cette problématique avec une architecture multi-agent inspectable :
- un planner décide du chemin ;
- un tool router choisit les outils ;
- un pipeline RAG récupère et prépare les documents ;
- un critic vérifie la réponse ;
- un safety guard contrôle la sortie ;
- le frontend affiche le parcours complet.

Ce n’est pas encore une plateforme agentique d’entreprise complète, mais c’est un **starter production-grade avancé** : assez simple pour apprendre, assez structuré pour évoluer.

---

## 3. Vue d’ensemble de l’architecture

```text
┌─────────────────────┐        HTTP/JSON        ┌──────────────────────────────┐
│   Frontend Next.js   │ ───────────────────────▶ │        Backend FastAPI       │
│   frontend/app       │ ◀─────────────────────── │        backend/app           │
└─────────────────────┘                          └──────────────────────────────┘
                                                          │
                                                          ▼
                                                ┌───────────────────┐
                                                │ ChatWorkflow       │
                                                │ LangGraph          │
                                                └───────────────────┘
                                                          │
                 ┌────────────────────────────────────────┼────────────────────────────────────────┐
                 ▼                                        ▼                                        ▼
          ┌─────────────┐                         ┌────────────────┐                       ┌────────────┐
          │ Redis Cloud  │                         │ MongoDB Atlas  │                       │ HuggingFace │
          │ memory/cache │                         │ full-text+vec  │                       │ Router LLM  │
          └─────────────┘                         └────────────────┘                       └────────────┘
```

Le graphe logique du chat :

```text
MemoryAgent
  -> LLMPlannerAgent
  -> ToolRouterAgent
  -> Greeting / SummaryAgent / SearchAgent
  -> HybridRetrieverAgent
  -> RerankerAgent
  -> ContextCompressionAgent
  -> RAGAgent
  -> LLMCriticAgent
  -> SafetyGuardAgent
  -> FinalAnswerAgent
```

---

## 4. Organisation des dossiers

```text
backend/app/main.py              -> point d’entrée FastAPI
backend/app/routers/             -> endpoints HTTP : auth, chat, ingest, health
backend/app/models/              -> modèles Pydantic
backend/app/services/            -> LLM, recherche, auth, tokens, ports retrieval
backend/app/agents/              -> agents du workflow
backend/app/workflows/           -> graphe LangGraph principal
backend/app/state/               -> GraphState / GraphStateDict
backend/app/memory/              -> Redis + fallback mémoire locale
backend/app/data_ingest/         -> ingestion CSV/PDF
backend/app/evaluation/          -> mini framework d’évaluation
backend/app/prompts/             -> prompts LLM centralisés
backend/app/middleware/          -> sécurité, rate limit, logs HTTP
backend/app/config/              -> configuration centralisée
frontend/app/page.tsx            -> interface principale + cockpit debug
docs/                            -> documentation architecture, agents, RAG, évaluation
```

---

## 5. Stack technique

| Composant | Technologie | Rôle |
|---|---|---|
| API backend | FastAPI | Expose les routes HTTP |
| Orchestration | LangGraph | Exécute le workflow agentique en graphe |
| Validation | Pydantic | Valide requêtes, réponses, plans, critic/safety |
| LLM | HuggingFace Router via client OpenAI | Génération, planning, critic, safety optionnel |
| Mémoire/cache | Redis Cloud | Historique, cache de réponses, utilisateurs |
| Recherche documentaire | MongoDB Atlas | Indexation et recherche hybride : full-text (Atlas Search) + vectorielle (Atlas Vector Search) |
| Frontend | Next.js / React / TypeScript | Chat + cockpit de debug |
| Observabilité | Loguru + Langfuse optionnel | Logs, traces LLM, debugging |
| Infra | Redis Cloud + MongoDB Atlas | Services managés cloud (tiers gratuits) ; aucun conteneur local requis |

Point important : contrairement à l’ancienne version du projet, **LangGraph est maintenant réellement utilisé** dans `backend/app/workflows/chat_workflow.py`.

---

## 6. Le backend étape par étape

### 6.1 Démarrage FastAPI

Le fichier `backend/app/main.py` :
- configure le logger ;
- vérifie `AUTH_SECRET_KEY` hors environnement local/dev/test ;
- crée l’app FastAPI ;
- ajoute les middlewares ;
- enregistre les routers.

Middlewares principaux :
- `SecurityHeadersMiddleware`
- `RateLimitMiddleware`
- `LoggingMiddleware`
- `CORSMiddleware`

### 6.2 Configuration

Le fichier `backend/app/config/settings.py` centralise les variables d’environnement.

Variables importantes :

```env
REDIS_URL=redis://default:<password>@<redis-cloud-endpoint>:<port>
MONGODB_URI=mongodb+srv://<user>:<password>@<cluster>.mongodb.net/?appName=Cluster0
MONGODB_SEARCH_INDEX=documents_search
MONGODB_VECTOR_INDEX=documents_vector
HUGGINGFACE_API_KEY=...
AUTH_SECRET_KEY=...
LANGGRAPH_CHECKPOINT_ENABLED=false
LANGGRAPH_CHECKPOINT_BACKEND=memory
MAX_USER_MESSAGE_CHARS=8000
MAX_RAG_CONTEXT_CHARS=4000
MAX_RAG_DOCUMENTS=5
LLM_TIMEOUT_SECONDS=60
MODEL_EMBEDDING=BAAI/bge-small-en-v1.5
SEMANTIC_RERANKER_ENABLED=true
```

À retenir :
- `AUTH_SECRET_KEY` doit être fort hors développement ;
- le backend limite la taille des messages ;
- le contexte RAG et le nombre de documents envoyés au LLM sont bornés ;
- le checkpoint LangGraph est optionnel ;
- le reranker sémantique peut être désactivé via `SEMANTIC_RERANKER_ENABLED=false` si besoin de limiter coût/latence.

### 6.3 Modèles Pydantic

Dans `backend/app/models/chat_models.py`, les modèles principaux sont :
- `ChatRequest`
- `ChatResponse`
- `SearchResult`
- `AgentResult`
- `PlannerDecision`
- `CriticReview`
- `SafetyReview`

`ChatResponse` garde les champs historiques :
- `conversation_id`
- `route`
- `answer`
- `agents_used`
- `agent_results`
- `cached`
- `context_messages`

Et ajoute des champs debug optionnels :
- `plan`
- `critic_feedback`
- `critic_passed`
- `critic_score`
- `retrieval_metrics`
- `safety_feedback`
- `safety_passed`
- `evaluation`
- `trace_id`

---

## 7. Le cœur du système : ChatWorkflow LangGraph

Le fichier le plus important est :

```text
backend/app/workflows/chat_workflow.py
```

### 7.1 Déroulé d’un appel `/api/v1/chat`

```text
1. Générer ou récupérer conversation_id.
2. Charger l’historique Redis.
3. Vérifier la limite de taille du message.
4. Vérifier le cache Redis.
5. Si cache hit :
     retourner route="cache".
6. Sinon :
     enregistrer le message utilisateur.
     construire GraphState.
     exécuter le graphe LangGraph.
     enregistrer la réponse assistant.
     mettre la réponse en cache.
     retourner ChatResponse.
```

### 7.2 Graphe exécuté

Le graphe contient ces nœuds :

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

### 7.3 Routage conditionnel

Après `ToolRouterAgent`, le graphe choisit :
- `greeting` -> réponse de salutation ;
- `direct_answer` -> `SummaryAgent` ;
- `document_qa` ou `rag` -> pipeline documentaire ;
- `fallback` -> `SummaryAgent`.

Après `LLMCriticAgent` :
- si la réponse passe -> `SafetyGuardAgent` ;
- si elle échoue et qu’aucune correction n’a été tentée -> retry `rag` ou `summary` ;
- sinon -> `SafetyGuardAgent`.

La boucle est bornée : une seule tentative de correction.

---

## 8. GraphState : l’état partagé

`GraphState` transporte les informations entre les agents.

Champs importants :

```python
conversation_id
transaction_id
user_message
history
conversation_context
route
intent
plan
tools
planner_decision
search_results
reranked_results
compressed_context
search_output
summary_output
rag_output
draft_answer
critic_feedback
critic_passed
critic_score
safety_feedback
safety_passed
final_answer
agents_used
agent_results
retrieval_metrics
evaluation
error
correction_attempted
metadata
```

Le projet garde deux formes :
- `GraphState` : dataclass pratique pour les agents ;
- `GraphStateDict` : `TypedDict` utilisé par LangGraph.

Les agents ajoutent leurs résultats dans :
- `agent_results` : sorties brutes affichées côté frontend ;
- `agents_used` : liste des agents appelés ;
- `retrieval_metrics` : métriques RAG ;
- `evaluation` : cache, critic, safety, latence.

---

## 9. Les agents, rôle par rôle

### 9.1 MemoryAgent

Charge le contexte de conversation :
- historique envoyé par le frontend ;
- sinon historique Redis.

### 9.2 LLMPlannerAgent

Produit un `PlannerDecision` validé par Pydantic :
- intention ;
- besoin de retrieval ;
- besoin de RAG ;
- besoin de critic ;
- besoin de safety ;
- étapes ;
- outils ;
- raison.

Si le LLM échoue ou renvoie un JSON invalide, l’agent produit un plan
déterministe de secours basé sur des mots-clés (greeting, summary, planning,
correction, sinon document_qa). C’est aussi le seul point de classification
d’intention du workflow : il n’y a plus d’agent superviseur séparé en amont —
il a été retiré car son résultat n’était de toute façon qu’un indice
textuel, toujours écrasé par `ToolRouterAgent` une fois le plan produit.

### 9.3 ToolRouterAgent

Convertit le plan en route LangGraph sûre :
- `greeting`
- `direct_answer`
- `document_qa`
- `rag`
- `fallback`

### 9.4 SearchAgent

Interroge MongoDB Atlas (Atlas Search, full-text) et retourne des documents avec :
- titre ;
- fichier ;
- page ;
- score ;
- snippet.

### 9.5 HybridRetrieverAgent

Fusionne :
- les résultats full-text (MongoDB Atlas Search) ;
- les résultats de la recherche vectorielle (MongoDB Atlas Vector Search).

Le port vectoriel est implémenté par :
- `VectorStorePort` (interface)
- `EmbeddingService` (interface)
- `MongoVectorStore` (implémentation branchée par défaut dans `ChatWorkflow`, appuyée sur `HuggingFaceEmbeddingService`)
- `NullVectorStore` (fallback neutre, utilisé si aucun store n'est explicitement injecté)

En pratique, `ChatWorkflow` branche toujours `MongoVectorStore` : la recherche vectorielle est active par défaut, pas seulement une interface préparée pour plus tard.

### 9.6 RerankerAgent

Réordonne les documents en combinant deux scores :
- score lexical : score full-text (MongoDB Atlas Search) + recouvrement de mots avec la question ;
- score sémantique (optionnel, `SEMANTIC_RERANKER_ENABLED`) : similarité
  cosinus entre l’embedding de la question et celui de chaque document,
  calculés via le HuggingFace Router (`MODEL_EMBEDDING`). Retombe
  silencieusement sur le score lexical seul si l’appel embeddings échoue.
- limite `MAX_RAG_DOCUMENTS`.

Produit :
- `retrieved_count`
- `reranked_count`
- `top_score`
- `sources_used`
- `semantic_reranking_used`

Détail complet et limites connues : [backend/app/agents/RAG_SYSTEM.md](backend/app/agents/RAG_SYSTEM.md).

### 9.7 ContextCompressionAgent

Réduit le contexte envoyé au LLM :
- snippets plus courts ;
- labels source conservés ;
- limite `MAX_RAG_CONTEXT_CHARS`.

### 9.8 SummaryAgent

Produit une réponse directe via le LLM.

Utilisé pour :
- réponses non documentaires ;
- résumés ;
- analyses simples ;
- demandes de correction ;
- fallback.

### 9.9 RAGAgent

Génère une réponse ancrée dans les documents :
- utilise `reranked_results` si disponibles ;
- utilise `compressed_context` si disponible ;
- cite les sources ;
- dit clairement quand aucun document pertinent n’est trouvé.

### 9.10 LLMCriticAgent

Évalue la réponse provisoire :
- pertinence ;
- clarté ;
- groundedness ;
- score global ;
- recommandation.

Si le LLM critic échoue, il utilise le critic déterministe existant.

### 9.11 SafetyGuardAgent

Vérifie la réponse avant finalisation :
- détecte clés API ;
- tokens bearer ;
- mots de passe ;
- clés privées ;
- masque les secrets évidents.

### 9.12 FinalAnswerAgent

Construit la réponse finale :
- prend la meilleure sortie disponible ;
- ajoute une note critic si nécessaire ;
- ajoute une note safety si nécessaire.

---

## 10. Pipeline RAG

Pipeline actuel :

```text
Ingestion CSV/PDF (+ calcul d'embeddings)
  -> MongoDB Atlas (full-text + vecteurs)
  -> SearchAgent
  -> HybridRetrieverAgent
  -> RerankerAgent
  -> ContextCompressionAgent
  -> RAGAgent
  -> LLMCriticAgent
  -> SafetyGuardAgent
  -> FinalAnswerAgent
```

Ce qui existe :
- ingestion CSV/PDF, avec calcul d'embeddings à la volée ;
- recherche full-text (Atlas Search) ;
- recherche vectorielle (Atlas Vector Search), fusionnée avec le full-text par `HybridRetrieverAgent` ;
- reranking lexical + sémantique (embeddings HuggingFace) ;
- compression de contexte ;
- génération sourcée ;
- critic ;
- safety ;
- métriques de retrieval.

Ce qui reste à brancher pour aller plus loin :
- reranker cross-encoder dédié ;
- citations phrase par phrase ;
- évaluation continue de la factualité.

---

## 11. Mémoire, cache et checkpoint

### 11.1 Redis

`RedisMemoryService` sert à :
- stocker les utilisateurs ;
- stocker l’historique conversationnel ;
- mettre en cache les réponses de chat.

Si Redis est indisponible, le service bascule vers un stockage mémoire local. C’est utile en développement, mais pas suffisant pour plusieurs workers ou un vrai déploiement distribué.

### 11.2 Cache de chat

Clé de cache :

```text
chat:<conversation_id>:<message normalisé>
```

En cas de cache hit :
- route `cache` ;
- agents `["cache"]` ;
- pas d’exécution LangGraph ;
- `evaluation.cache.hit = true`.

### 11.3 Checkpoint LangGraph

Variables :

```env
LANGGRAPH_CHECKPOINT_ENABLED=false
LANGGRAPH_CHECKPOINT_BACKEND=memory
```

Le checkpoint est désactivé par défaut. En mode `memory`, le graphe utilise `MemorySaver`.

---

## 12. LLMService et prompts

`backend/app/services/llm_service.py` utilise le client OpenAI officiel, pointé vers :

```text
https://router.huggingface.co/v1
```

Méthodes importantes :
- `generate()`
- `summarize()`
- `grounded_answer()`
- `plan()`
- `critic_review()`
- `safety_review()`
- `compress_context()`
- `rerank_with_llm()`

Les prompts sont centralisés dans :

```text
backend/app/prompts/llm_prompts.py
```

Les sorties JSON du planner, du critic et du safety review sont validées par Pydantic.

---

## 13. Frontend

Le frontend principal est dans :

```text
frontend/app/page.tsx
```

Il contient :
- écran login/register ;
- interface de chat ;
- ingestion des données ;
- statut backend / Redis / MongoDB ;
- cockpit de debug.

Le cockpit affiche notamment :
- route ;
- agents utilisés ;
- cache ;
- plan ;
- critic pass/fail ;
- critic score ;
- safety status ;
- retrieval metrics ;
- trace id ;
- sorties brutes `agent_results`.

Pourquoi c’est important : le projet est pédagogique. On ne voit pas seulement la réponse finale, on voit aussi **comment** elle a été produite.

---

## 14. Authentification et sécurité

### 14.1 Auth

Le projet utilise :
- email/mot de passe ;
- hash `pbkdf2_sha256` ;
- JWT signé ;
- dépendance FastAPI `get_current_user`.

Limite actuelle :
- pas de révocation serveur des tokens ;
- logout côté frontend = suppression du token local.

### 14.2 Sécurité applicative

Déjà présent :
- security headers ;
- rate limiting en mémoire ;
- CORS configurable ;
- `AUTH_SECRET_KEY` obligatoire hors dev/local/test ;
- safety guard anti-secrets ;
- limites de taille message et contexte RAG.

À durcir pour une vraie production :
- rate limiting Redis distribué ;
- politique CORS par environnement ;
- audit des logs ;
- protection prompt injection ;
- gestion centralisée des secrets ;
- checkpoint persistant avec rétention maîtrisée.

---

## 15. Observabilité

Le projet utilise :
- Loguru ;
- contexte de logs avec `session_id`, `transaction_id`, `agent_type`, `route` ;
- Langfuse optionnel ;
- `agent_results` pour le cockpit ;
- `evaluation.latency_ms` pour les durées par node ;
- `retrieval_metrics` pour le RAG ;
- `trace_id` dans `ChatResponse`.

Chaque nœud LangGraph logge :
- nom ;
- conversation ;
- route ;
- aperçu entrée/sortie ;
- durée ;
- erreur éventuelle.

---

## 16. Mini framework d’évaluation

Dossier :

```text
backend/app/evaluation/
```

Fichiers :
- `cases.py` : cas d’évaluation ;
- `metrics.py` : métriques simples ;
- `evaluator.py` : exécuteur branchable sur `ChatWorkflow`.

Objectif :
- vérifier route attendue ;
- vérifier réponse non vide ;
- vérifier présence de sources quand nécessaire ;
- observer critic/safety ;
- préparer des tests de non-régression.

---

## 17. Exemple concret de bout en bout

Question :

```text
What is Langfuse used for?
```

Déroulé probable :

```text
1. Frontend envoie POST /api/v1/chat.
2. ChatWorkflow vérifie le cache.
3. MemoryAgent charge le contexte.
4. LLMPlannerAgent produit un plan document_qa.
5. ToolRouterAgent choisit rag.
6. SearchAgent interroge MongoDB Atlas (full-text) ; en parallèle logique, `MongoVectorStore` interroge l'index vectoriel.
7. HybridRetrieverAgent normalise/fusionne les résultats full-text et vectoriels.
8. RerankerAgent classe les documents (score lexical + sémantique).
9. ContextCompressionAgent réduit le contexte.
10. RAGAgent génère une réponse sourcée.
11. LLMCriticAgent vérifie la réponse.
12. SafetyGuardAgent vérifie la sortie.
13. FinalAnswerAgent produit la réponse finale.
14. Redis stocke historique et cache.
15. Frontend affiche réponse + debug cockpit.
```

La réponse frontend inclut typiquement :
- `answer`
- `route`
- `agents_used`
- `agent_results`
- `plan`
- `retrieval_metrics`
- `critic_score`
- `safety_feedback`
- `trace_id`

---

## 18. Où modifier quoi ?

| Tu veux... | Fichier(s) |
|---|---|
| Changer le graphe LangGraph | `backend/app/workflows/chat_workflow.py` |
| Ajouter un agent | `backend/app/agents/` puis brancher dans `chat_workflow.py` |
| Changer le prompt du planner/critic/RAG | `backend/app/prompts/llm_prompts.py` |
| Modifier le routing initial et le fallback par mots-clés | `backend/app/agents/llm_planner_agent.py` |
| Modifier le plan structuré | `backend/app/agents/llm_planner_agent.py` |
| Modifier le tool routing | `backend/app/agents/tool_router_agent.py` |
| Modifier le RAG | `rag_agent.py`, `reranker_agent.py`, `context_compression_agent.py` |
| Changer d'implémentation de vector store | `backend/app/services/retrieval_ports.py` (interface) + `backend/app/services/mongo_vector_store.py` (implémentation actuelle) |
| Modifier les champs API | `backend/app/models/chat_models.py` |
| Modifier l’état partagé | `backend/app/state/graph_state.py` |
| Changer les modèles LLM | variables `MODEL_*` dans `.env` |
| Modifier l’UI | `frontend/app/page.tsx` |
| Ajouter un endpoint | `backend/app/routers/` + `main.py` |
| Ajouter des cas d’évaluation | `backend/app/evaluation/cases.py` |
| Modifier la config | `backend/app/config/settings.py` + `.env.example` |

---

## 19. Points de vigilance

- `AUTH_SECRET_KEY` doit être changé hors dev.
- `llm_provider="ollama"` existe dans la config, mais le service LLM réellement branché est HuggingFace Router.
- Le vector store (`MongoVectorStore`, Atlas Vector Search) est branché par défaut. Le reranking sémantique, lui, n'en dépend pas : il calcule ses propres embeddings à la volée pour reclasser les candidats déjà récupérés, indépendamment de l'index vectoriel utilisé pour le recall.
- Le calcul d'embeddings dépend de la disponibilité du endpoint `pipeline/feature-extraction` du HuggingFace Router : en cas d'échec (quota, modèle indisponible), l'ingestion et la recherche continuent en mode dégradé (documents sans embedding, recherche vectorielle vide pour ces documents), sans faire planter le workflow.
- Le reranking combine un score lexical et un score sémantique (embeddings HuggingFace), mais ce n’est pas encore un cross-encoder dédié.
- Le checkpoint est mémoire, pas persistant.
- Le rate limiting est en mémoire locale.
- Le cache est exact-match sur le message normalisé, pas sémantique.
- Les tests sont prévus avec fakes ; dans un environnement sans dépendances backend installées, ils peuvent être skipped proprement.

---

## 20. Lancer le projet

Aucune infrastructure locale à démarrer : Redis (Redis Cloud) et MongoDB
(Atlas) tournent tous les deux en cloud, sur des tiers gratuits. Il suffit de
renseigner leurs URIs dans `backend/.env`.

```bash
# 1. Configuration
cd backend
cp .env.example .env
# éditer .env : REDIS_URL, MONGODB_URI, HUGGINGFACE_API_KEY, ...

# 2. Backend + Frontend ensemble (depuis la racine du projet)
make install   # venv Python + npm install
make dev       # lance backend (:8000) et frontend (:3000) en parallèle

# ou séparément :
# make backend
# make frontend

# 3. Ouvrir
http://localhost:3000
```

Ensuite :
1. créer un compte ;
2. se connecter ;
3. ingérer les données d’exemple ;
4. poser une question ;
5. observer le cockpit de debug.

---

## 21. Résumé final

Ce projet est maintenant un **système de chat IA multi-agent orchestré par LangGraph**.

Il reçoit un message, charge la mémoire, planifie l’exécution, choisit les outils, cherche éventuellement dans MongoDB Atlas (full-text + vectoriel), prépare le contexte documentaire, génère une réponse sourcée, la critique, la sécurise, la met en cache, puis expose tout le parcours au frontend.

En une ligne :

```text
FastAPI + LangGraph + Redis Cloud + MongoDB Atlas + HuggingFace Router
+ Planner + Tool Router + RAG + Critic + Safety + Debug Cockpit
```

Le projet reste pédagogique, mais il reflète déjà beaucoup de patterns utilisés dans des architectures agentiques modernes.
