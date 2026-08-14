# Guide de compréhension du projet — Agentic RAG Platform

> Ce guide explique le projet tel qu'il est **aujourd'hui** (vérifié contre le code source le 2026-08-13) : une plateforme RAG agentique basée sur FastAPI, LangGraph, Redis Cloud, MongoDB Atlas, HuggingFace Router et Next.js. Il couvre à lui seul l'architecture, le rôle de chaque agent, le stack technique, la configuration, les limites connues et les points d'extension — c'est le document de référence unique du projet.

---

## 1. Le projet en une phrase

Une application de **chat IA agentique** : l'utilisateur pose une question, le backend décide quels agents appeler, récupère éventuellement des documents dans MongoDB Atlas (full-text + vectoriel), génère une réponse avec un LLM, vérifie sa qualité avec un critic, applique un garde-fou de sécurité, puis renvoie une réponse compatible avec le frontend — avec un cockpit de debug qui rend tout ce parcours visible.

```text
Message utilisateur
  -> mémoire
  -> planification LLM (avec fallback déterministe)
  -> choix des outils (tool routing)
  -> recherche / RAG / réponse directe
  -> critique
  -> sécurité
  -> réponse finale
```

## 2. Problématique résolue

Un chatbot simple répond souvent sans savoir :
- quand chercher dans une base documentaire ;
- quand répondre directement ;
- comment citer ses sources ;
- comment vérifier si la réponse est fiable ;
- comment éviter de divulguer des informations sensibles ;
- comment expliquer au développeur ce qui s'est passé.

Ce projet y répond avec une architecture multi-agent inspectable : un planner décide du chemin, un tool router choisit les outils, un pipeline RAG récupère et prépare les documents, un critic vérifie la réponse, un safety guard contrôle la sortie, et le frontend affiche le parcours complet.

Positionnement : un **starter production-grade avancé** — assez simple pour apprendre, assez structuré pour évoluer. Ce n'est pas (encore) une plateforme agentique d'entreprise complète ; la section [19](#19-points-de-vigilance-et-limites-connues) liste précisément ce qui manque.

---

## 3. Vue d'ensemble de l'architecture

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

Aucun service n'est auto-hébergé : Redis et MongoDB tournent tous les deux en cloud, sur des tiers gratuits (Redis Cloud, MongoDB Atlas M0), aussi bien en développement local qu'en production. Il n'y a donc pas de `docker-compose`/`podman-compose` dans le projet.

## 4. Organisation des dossiers

```text
backend/app/main.py              -> point d'entrée FastAPI
backend/app/routers/             -> endpoints HTTP : auth, chat, ingest, health
backend/app/models/              -> modèles Pydantic
backend/app/services/            -> LLM, recherche, embeddings, auth, tokens, ports retrieval
backend/app/agents/              -> agents du workflow
backend/app/workflows/           -> graphe LangGraph principal
backend/app/state/               -> GraphState / GraphStateDict
backend/app/memory/              -> Redis + fallback mémoire locale
backend/app/data_ingest/         -> ingestion CSV/PDF
backend/app/evaluation/          -> mini framework d'évaluation
backend/app/prompts/             -> prompts LLM centralisés
backend/app/middleware/          -> sécurité, rate limit, logs HTTP
backend/app/config/              -> configuration centralisée
frontend/app/page.tsx            -> interface principale + cockpit debug (2300+ lignes)
docs/                            -> documentation (ce guide, RAG_SYSTEM.md, EVALUATION.md)
```

---

## 5. Stack technique

| Composant | Technologie | Rôle | Pourquoi |
|---|---|---|---|
| API backend | FastAPI + Uvicorn | Exposer les routes HTTP (chat, auth, ingest, health) | Async, rapide, validation native via Pydantic |
| Orchestration | LangGraph (`StateGraph`) | Exécuter le workflow agentique en graphe d'états compilé | Orchestration réelle, pas manuelle — état partagé, transitions conditionnelles, boucle de correction bornée |
| Validation | Pydantic | Valider requêtes, réponses, plan, critic/safety | Évite les erreurs de structure de données |
| LLM | HuggingFace Router (client OpenAI officiel, `router.huggingface.co/v1`) | Génération, planning, critic, safety optionnel | API compatible OpenAI, pas d'infra GPU à gérer |
| Embeddings | HuggingFace Router, route `pipeline/feature-extraction` (`HuggingFaceEmbeddingService`) | Vectoriser documents (ingestion) et requêtes (reranking + recherche vectorielle) | Le endpoint `/v1/embeddings` compatible OpenAI ne dessert aucun modèle d'embedding testé ; cette route "pipeline" fonctionne réellement |
| Mémoire/cache | Redis Cloud | Historique conversationnel, cache de réponses, comptes utilisateurs | Managé, tier gratuit, pas de serveur à héberger |
| Recherche documentaire | MongoDB Atlas (Atlas Search + Atlas Vector Search) | Indexation et recherche hybride (full-text + sémantique) sur une même collection | Une seule base à faire tourner/synchroniser pour le full-text et les vecteurs |
| Observabilité | Loguru + Langfuse (optionnel, `LANGFUSE_ENABLED`) | Logs structurés, traces LLM, latence par nœud | Debug et compréhension du parcours agentique |
| Frontend | Next.js 15 / React 19 / TypeScript | Chat + auth + ingestion + cockpit de debug | Environnement moderne, typé |
| Lancement local | Makefile | `make install` (venv + npm), `make dev` (backend + frontend en parallèle) | Un seul point d'entrée pour le dev local |

Détail des bibliothèques Python notables (`backend/requirements.txt`) : `langgraph`/`langgraph-checkpoint` (orchestration), `langfuse` (traçage LLM), `pymongo` (MongoDB Atlas), `redis` (Redis Cloud), `openai` (client HTTP HuggingFace Router), `PyJWT` + `passlib` (auth), `PyPDF2` (extraction texte PDF), `python-multipart` (upload fichiers).

---

## 6. Le backend étape par étape

### 6.1 Démarrage FastAPI (`backend/app/main.py`)

1. Configure le logger (avant tout le reste, pour capturer les logs de démarrage des autres modules).
2. Vérifie que `AUTH_SECRET_KEY` a été changé hors des environnements `development`/`local`/`test` (sinon `RuntimeError` au démarrage).
3. Crée l'app FastAPI et empile les middlewares : `SecurityHeadersMiddleware`, `RateLimitMiddleware` (60 req/min par IP, en mémoire), `LoggingMiddleware`, `CORSMiddleware`.
4. Enregistre les routers : `health`, `auth`, `ingest`, `chat`.

### 6.2 Configuration (`backend/app/config/settings.py`)

Variables importantes (voir `backend/.env.example` pour la liste complète) :

```env
LLM_PROVIDER=huggingface
HUGGINGFACE_API_KEY=...
MODEL_EMBEDDING=BAAI/bge-small-en-v1.5
SEMANTIC_RERANKER_ENABLED=true

REDIS_URL=redis://default:<password>@<redis-cloud-endpoint>:<port>

MONGODB_URI=mongodb+srv://<user>:<password>@<cluster>.mongodb.net/?appName=Cluster0
MONGODB_SEARCH_INDEX=documents_search
MONGODB_VECTOR_INDEX=documents_vector
EMBEDDING_DIMENSIONS=384

LANGGRAPH_CHECKPOINT_ENABLED=false
LANGGRAPH_CHECKPOINT_BACKEND=memory
MAX_USER_MESSAGE_CHARS=8000
MAX_RAG_CONTEXT_CHARS=4000
MAX_RAG_DOCUMENTS=5
LLM_TIMEOUT_SECONDS=60

AUTH_SECRET_KEY=...
```

À retenir :
- le champ `llm_provider` accepte `"ollama"` (valeur par défaut du code Python si la variable d'env est absente) ou `"huggingface"` — mais `.env.example` fixe `LLM_PROVIDER=huggingface`, et c'est le seul fournisseur réellement branché dans `LLMService` ; `ollama_base_url`/`ollama_model` existent dans `Settings` mais ne sont utilisés par aucun service ;
- le reranker sémantique peut être désactivé via `SEMANTIC_RERANKER_ENABLED=false` pour limiter coût/latence ;
- `MAX_RAG_DOCUMENTS` ne borne que le nombre de documents *après* reranking, pas la profondeur de recherche full-text (voir [RAG_SYSTEM.md](RAG_SYSTEM.md), erreur #1).

### 6.3 Modèles Pydantic (`backend/app/models/chat_models.py`)

- `ChatRequest` : `message`, `conversation_id`, `history`.
- `ChatResponse` : garde les champs historiques (`conversation_id`, `route`, `answer`, `agents_used`, `agent_results`, `cached`, `context_messages`) et ajoute des champs debug optionnels (`plan`, `critic_feedback`, `critic_passed`, `critic_score`, `retrieval_metrics`, `safety_feedback`, `safety_passed`, `evaluation`, `trace_id`).
- `SearchResult`, `AgentResult`, `PlannerDecision`, `CriticReview`, `SafetyReview` : structures internes échangées entre agents.

---

## 7. Le cœur du système : ChatWorkflow LangGraph

Fichier central : `backend/app/workflows/chat_workflow.py`.

### 7.1 Déroulé d'un appel `POST /api/v1/chat`

```text
1. Générer ou récupérer conversation_id.
2. Charger l'historique Redis.
3. Vérifier la limite de taille du message (sinon route="safety", pas d'exécution du graphe).
4. Vérifier le cache Redis (clé chat:<conversation_id>:<message normalisé>).
5. Si cache hit : retourner route="cache" (aucun agent LangGraph exécuté).
6. Sinon : enregistrer le message utilisateur, construire GraphState,
   exécuter le graphe LangGraph, enregistrer la réponse assistant,
   mettre la réponse en cache, retourner ChatResponse.
```

### 7.2 Graphe exécuté — 15 nœuds

Le workflow construit un `StateGraph(GraphStateDict)` avec ces nœuds :

```text
memory · planner · tool_router · greeting · search · hybrid_retriever
reranker · context_compression · summary · rag · critic · safety
prepare_rag_retry · prepare_summary_retry · final_answer
```

12 nœuds sont adossés à une classe d'agent dédiée (section 9), 3 sont des nœuds techniques sans classe propre (`greeting`, `prepare_rag_retry`, `prepare_summary_retry`). Le graphe est compilé une seule fois à l'initialisation du workflow.

### 7.3 Routage conditionnel

Après `ToolRouterAgent` :
- `greeting` -> nœud `greeting` ;
- `direct_answer` (ou `analysis`/`correction`/`planning`) -> `SummaryAgent` ;
- `document_qa`/`rag` -> pipeline documentaire (`search` -> `hybrid_retriever` -> `reranker` -> `context_compression`) ;
- toute autre valeur -> `SummaryAgent` (fallback).

Après `context_compression`, si la route est `document_qa` mais que le plan indique `requires_rag=False`, le graphe saute directement au critic sans appeler `RAGAgent`.

Après `LLMCriticAgent` :
- réponse acceptée -> `SafetyGuardAgent` ;
- réponse refusée et **aucune** correction encore tentée -> `prepare_rag_retry` (si la route était `rag`/`parallel` et qu'il y a des `search_results`) ou `prepare_summary_retry` (si la route était `summary`/`simple_llm`/`planning`/`correction`), qui relance respectivement `RAGAgent` ou `SummaryAgent` ;
- correction déjà tentée -> `SafetyGuardAgent` directement.

La boucle est bornée à **une seule** tentative de correction (`state.correction_attempted`) : aucune boucle infinie possible.

---

## 8. GraphState : l'état partagé

`GraphState` transporte les informations entre les agents (`backend/app/state/graph_state.py`) :

```python
conversation_id, transaction_id, user_message, history, conversation_context
route, intent, plan, tools, planner_decision
search_results, reranked_results, compressed_context
search_output, summary_output, rag_output, draft_answer
critic_feedback, critic_passed, critic_score
safety_feedback, safety_passed
final_answer, agents_used, agent_results
retrieval_metrics, evaluation, error, correction_attempted, metadata
```

Le projet garde deux représentations : `GraphState` (dataclass pratique pour les agents) et `GraphStateDict` (`TypedDict` utilisé par LangGraph). `GraphState.from_mapping()`/`to_dict()` font la conversion aux frontières des nœuds, et reconstruisent proprement les modèles Pydantic imbriqués (`ChatMessage`, `SearchResult`, `AgentResult`, `PlannerDecision`).

Chaque agent écrit dans `agent_results` (sortie brute affichée côté frontend), `agents_used` (chemin suivi), `retrieval_metrics` (métriques RAG) et `evaluation` (cache/critic/safety/latence par nœud, via `record_result()`).

---

## 9. Les agents, rôle par rôle

Le graphe compte **15 nœuds** : **12 nœuds adossés à une classe d'agent**, **1 classe de secours** utilisée en interne (`CriticAgent`, appelée par `LLMCriticAgent` si le LLM échoue) et **3 nœuds techniques** sans classe dédiée (`greeting`, `prepare_rag_retry`, `prepare_summary_retry`).

Il n'y a **pas** d'agent superviseur en amont du planner (un `SupervisorAgent` existait dans une version antérieure du projet ; il a été retiré — sa sortie n'était qu'un indice textuel, de toute façon toujours écrasé par `ToolRouterAgent`). Il n'existe pas non plus de classe `PlannerAgent` déterministe séparée : le fallback déterministe du planner est une méthode interne de `LLMPlannerAgent` (`_fallback_decision`), pas un fichier/agent à part.

**Détail complet de chaque agent (rôle, entrées/sorties, logique interne, comportement en cas d'échec) : [AGENTS.md](AGENTS.md)** — ce guide ne le duplique pas, il en garde seulement le résumé ci-dessous.

| Agent | Nœud | Rôle en une ligne |
|---|---|---|
| `MemoryAgent` | `memory` | Charge l'historique de conversation (frontend en priorité, sinon Redis) |
| `LLMPlannerAgent` | `planner` | Seul point de classification d'intention ; plan structuré + fallback par mots-clés |
| `ToolRouterAgent` | `tool_router` | Convertit le plan en route de graphe (`greeting`/`direct_answer`/`document_qa`/`rag`/`fallback`) |
| `SearchAgent` | `search` | Recherche full-text MongoDB Atlas (Atlas Search) |
| `HybridRetrieverAgent` | `hybrid_retriever` | Fusionne full-text + recherche vectorielle (Atlas Vector Search) |
| `RerankerAgent` | `reranker` | Réordonne les documents (score lexical + score sémantique par embeddings) |
| `ContextCompressionAgent` | `context_compression` | Réduit le contexte envoyé au LLM (`MAX_RAG_CONTEXT_CHARS`) |
| `SummaryAgent` | `summary` | Réponse directe sans recherche documentaire |
| `RAGAgent` | `rag` | Génère une réponse ancrée dans les documents, avec garde-fou anti-hallucination |
| `LLMCriticAgent` | `critic` | Évalue qualité/clarté/ancrage de la réponse, fallback sur `CriticAgent` |
| `SafetyGuardAgent` | `safety` | Détecte et masque les secrets évidents (regex) |
| `FinalAnswerAgent` | `final_answer` | Assemble la réponse finale envoyée au frontend |

Le diagramme du graphe (avec la boucle de correction bornée) et le détail agent par agent sont dans [AGENTS.md](AGENTS.md).

---

## 10. Pipeline RAG

```text
Ingestion CSV/PDF (+ calcul d'embeddings)
  -> MongoDB Atlas (full-text + vecteurs)
  -> SearchAgent -> HybridRetrieverAgent -> RerankerAgent -> ContextCompressionAgent -> RAGAgent
  -> LLMCriticAgent -> SafetyGuardAgent -> FinalAnswerAgent
```

Ce qui est en place : recherche full-text (Atlas Search) et vectorielle (Atlas Vector Search) actives et fusionnées, reranking lexical + sémantique, compression de contexte, génération sourcée, critic, safety, métriques de retrieval.

Ce qui reste à brancher : reranker cross-encoder dédié, citations phrase par phrase, fusion dense/sparse pondérée (RRF) plutôt qu'une concaténation triée, évaluation continue de la factualité.

**Le détail étage par étage, les 7 bugs/limites identifiés dans le code actuel (avec fichier:ligne) et les pistes de correction sont documentés séparément dans [RAG_SYSTEM.md](RAG_SYSTEM.md)** — ce guide ne les duplique pas.

---

## 11. Mémoire, cache et checkpoint

**Redis** (`RedisMemoryService`) stocke l'historique conversationnel, le cache des réponses et les comptes utilisateurs (clé `user:<email>`, sans expiration). Si Redis est indisponible, le service bascule vers un stockage mémoire local du process (utile en dev, insuffisant pour plusieurs workers).

**Cache de chat** : clé `chat:<conversation_id>:<message normalisé>`. En cas de hit : `route="cache"`, `agents_used=["cache"]`, aucune exécution LangGraph, `evaluation.cache.hit=true`.

**Checkpoint LangGraph** : désactivé par défaut (`LANGGRAPH_CHECKPOINT_ENABLED=false`). En mode `memory`, le graphe est compilé avec `MemorySaver` et reçoit `{"configurable": {"thread_id": conversation_id}}`. Pas de backend persistant (Redis/Postgres) à ce jour.

---

## 12. LLMService et prompts

`backend/app/services/llm_service.py` utilise le client OpenAI officiel pointé vers `https://router.huggingface.co/v1`.

Méthodes exposées : `generate()`, `summarize()`, `generate_code()`, `answer_question()`, `grounded_answer()`, `plan()`, `critic_review()`, `safety_review()`, `compress_context()`, `rerank_with_llm()`, `reason()`.

Les prompts sont centralisés dans `backend/app/prompts/llm_prompts.py`. Les sorties JSON du planner, du critic et du safety review sont validées par Pydantic (`PlannerDecision`, `CriticReview`, `SafetyReview`).

---

## 13. Frontend

`frontend/app/page.tsx` (composant unique, ~2300 lignes) contient :
- écran login/register (`/api/v1/auth/login`, `/api/v1/auth/register`) ;
- interface de chat ;
- ingestion des données (`/api/v1/ingest/batch`, `/upload`, `/sample-data`) ;
- indicateurs de statut backend / Redis / MongoDB / modèle LLM (`GET /health`) ;
- **cockpit de debug** : route, agents utilisés, cache, plan, critic pass/fail + score, safety status, retrieval metrics, trace id, sorties brutes `agent_results`.

Le cockpit est central au projet : il ne montre pas seulement la réponse finale, mais **comment** elle a été produite.

---

## 14. Authentification et sécurité

**Auth** : email/mot de passe (`AuthService`, comptes stockés en JSON dans Redis), hash `pbkdf2_sha256` (`passlib`), JWT signé (`PyJWT`), dépendance FastAPI `get_current_user`. Limite : pas de révocation serveur des tokens — le logout côté frontend supprime seulement le token local.

**Sécurité applicative déjà présente** : `SecurityHeadersMiddleware`, `RateLimitMiddleware` (60 req/min/IP, en mémoire process — pas distribué entre workers), CORS configurable, `AUTH_SECRET_KEY` obligatoire hors dev/local/test, `SafetyGuardAgent` anti-secrets, limites de taille message/contexte RAG.

**À durcir pour une vraie production** : rate limiting distribué (Redis), politique CORS par environnement, audit des logs, défense prompt injection, gestion centralisée des secrets, checkpoint persistant.

---

## 15. Observabilité

Chaque nœud LangGraph logge (Loguru) : nom du nœud, `conversation_id`, route, aperçu entrée/sortie, durée, erreur éventuelle. Le logger conserve aussi `session_id`, `transaction_id`, `agent_type`, `route` en contexte. Langfuse est optionnel (`LANGFUSE_ENABLED`) pour le traçage LLM (décorateur `@observe`, no-op si désactivé).

Métriques exposées dans `ChatResponse` : `retrieval_metrics`, `evaluation` (dont `evaluation.latency_ms` par nœud), `critic_score`, `safety_passed`, `safety_feedback`, `trace_id`.

---

## 16. Évaluation

Mini framework branchable sur `ChatWorkflow`, sans dépendance externe (`backend/app/evaluation/`). Détail dans [EVALUATION.md](EVALUATION.md).

---

## 17. Exemple concret de bout en bout

Question : `What is Langfuse used for?`

```text
1. Frontend envoie POST /api/v1/chat.
2. ChatWorkflow vérifie le cache Redis.
3. MemoryAgent charge le contexte.
4. LLMPlannerAgent produit un plan document_qa (requires_rag=true).
5. ToolRouterAgent choisit la route rag.
6. SearchAgent interroge MongoDB Atlas (full-text, Atlas Search).
7. HybridRetrieverAgent fusionne avec les résultats de MongoVectorStore (Atlas Vector Search).
8. RerankerAgent classe les documents (score lexical + sémantique).
9. ContextCompressionAgent réduit le contexte.
10. RAGAgent génère une réponse sourcée.
11. LLMCriticAgent vérifie la réponse (accept ou un essai de retry_rag).
12. SafetyGuardAgent vérifie/rédige la sortie.
13. FinalAnswerAgent produit la réponse finale.
14. Redis stocke historique et cache.
15. Frontend affiche la réponse + le cockpit de debug.
```

La réponse inclut typiquement : `answer`, `route`, `agents_used`, `agent_results`, `plan`, `retrieval_metrics`, `critic_score`, `safety_feedback`, `trace_id`.

---

## 18. Où modifier quoi ?

| Tu veux... | Fichier(s) |
|---|---|
| Changer le graphe LangGraph | `backend/app/workflows/chat_workflow.py` |
| Ajouter un agent | `backend/app/agents/` puis brancher dans `chat_workflow.py` |
| Changer le prompt du planner/critic/RAG | `backend/app/prompts/llm_prompts.py` |
| Modifier le fallback déterministe du planner | `backend/app/agents/llm_planner_agent.py` (`_fallback_decision`) |
| Modifier le tool routing | `backend/app/agents/tool_router_agent.py` |
| Modifier le RAG | `rag_agent.py`, `reranker_agent.py`, `context_compression_agent.py` — voir aussi [RAG_SYSTEM.md](RAG_SYSTEM.md) |
| Changer d'implémentation de vector store | `backend/app/services/retrieval_ports.py` (interface) + `backend/app/services/mongo_vector_store.py` (implémentation actuelle) |
| Modifier les champs API | `backend/app/models/chat_models.py` |
| Modifier l'état partagé | `backend/app/state/graph_state.py` |
| Changer les modèles LLM/embedding | variables `MODEL_*` dans `.env` |
| Modifier l'UI / le cockpit | `frontend/app/page.tsx` |
| Ajouter un endpoint | `backend/app/routers/` + `main.py` |
| Ajouter des cas d'évaluation | `backend/app/evaluation/cases.py` |
| Modifier la config | `backend/app/config/settings.py` + `.env.example` |

---

## 19. Points de vigilance et limites connues

### 19.1 Configuration et code
- `AUTH_SECRET_KEY` doit être changé hors dev (le backend refuse de démarrer sinon, hors `development`/`local`/`test`).
- `llm_provider` par défaut vaut `"ollama"` côté code si `LLM_PROVIDER` n'est pas défini, mais `.env.example` fixe `huggingface` — c'est le seul fournisseur réellement branché ; les champs `ollama_*` de `Settings` ne sont utilisés par aucun service.
- Le calcul d'embeddings dépend de la disponibilité de la route `pipeline/feature-extraction` du HuggingFace Router : en cas d'échec (quota, modèle indisponible), l'ingestion et la recherche continuent en mode dégradé, sans planter le workflow.
- Le rate limiting est en mémoire locale (pas distribué entre workers/replicas).
- Le cache de chat est exact-match sur le message normalisé, pas sémantique.
- Le checkpoint LangGraph est mémoire, pas persistant (pas de reprise inter-process).

### 19.2 RAG
Voir [RAG_SYSTEM.md](RAG_SYSTEM.md) pour la liste précise (fichier:ligne) des 7 limites connues du pipeline RAG — notamment : `MAX_RAG_DOCUMENTS` ne borne pas la recherche full-text (limite codée en dur à 5), la pondération lexical/sémantique du reranker (`SEMANTIC_WEIGHT=2.0`) n'est pas calibrée, la compression de contexte est une troncature naïve.

### 19.3 Ce qui reste volontairement simple (roadmap)
Le projet reste un starter pédagogique avancé, pas une plateforme d'entreprise complète. Pistes d'évolution, par priorité :
1. **Fusion dense/sparse pondérée** : remplacer la concaténation triée de `HybridRetrieverAgent` par une fusion de rang type RRF, ou évaluer `$rankFusion` côté MongoDB Atlas.
2. **Reranker robuste** : cross-encoder dédié ou reranker LLM (au lieu d'un score bi-encodeur additionné à un score lexical).
3. **Évaluation renforcée** : jeu de questions/réponses de référence, métriques retrieval/groundedness/hallucination, dashboard qualité.
4. **Métriques production** : Prometheus/OpenTelemetry, taux de cache hit, taux de critic fail, taux de safety redaction.
5. **Checkpoint persistant** : backend Redis ou Postgres pour les workflows longs/repris.
6. **Sécurité renforcée** : CORS par environnement, rate limiting distribué, sanitization des logs, défense prompt injection.

### 19.4 Snapshot de maturité

| Dimension | Niveau actuel |
|---|---|
| Architecture backend | Solide et modulaire |
| Orchestration LangGraph | Avancée pour un starter (graphe réel, retry borné) |
| Planner | LLM + Pydantic + fallback déterministe |
| Retrieval hybride | Actif : full-text (Atlas Search) + vectoriel (Atlas Vector Search) |
| Reranking | Lexical + sémantique (embeddings bi-encodeur), poids non calibré |
| Critic / Safety | LLM avec fallback déterministe / garde-fou regex léger |
| Observabilité | Bonne pour debug (logs par nœud, cockpit, Langfuse optionnel) |
| Évaluation | Mini framework présent, pas de jeu de données de référence |
| Production readiness | En progression, pas complète (voir 19.1 et 19.3) |

---

## 20. Lancer le projet

Aucune infrastructure locale à démarrer : Redis (Redis Cloud) et MongoDB (Atlas) tournent tous les deux en cloud, sur des tiers gratuits.

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

Ensuite : créer un compte -> se connecter -> ingérer les données d'exemple (`/ingest/sample-data` ou `/ingest/batch`) -> poser une question -> observer le cockpit de debug.

---

## 21. Résumé final

```text
FastAPI + LangGraph + Redis Cloud + MongoDB Atlas (full-text + vector)
+ LLM Planner + Tool Router
+ Hybrid Retrieval + Reranking + Context Compression
+ RAG + LLM Critic + Safety Guard
+ Observability + Evaluation Hooks
+ Next.js Debug Cockpit
```

Le projet reçoit un message, charge la mémoire, planifie l'exécution, choisit les outils, cherche éventuellement dans MongoDB Atlas (full-text + vectoriel), prépare le contexte documentaire, génère une réponse sourcée, la critique, la sécurise, la met en cache, puis expose tout le parcours au frontend. Il reste pédagogique, mais reflète déjà beaucoup de patterns utilisés dans des architectures agentiques modernes (LangGraph, Semantic Kernel, AutoGen, CrewAI ou orchestrateurs internes).
