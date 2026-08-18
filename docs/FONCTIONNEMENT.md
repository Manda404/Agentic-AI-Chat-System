# Fonctionnement du projet — parcours complet

> Lecture chronologique du comportement réel, vérifiée contre le code le
> **18 août 2026**.

## 1. Démarrage

Depuis la racine :

```bash
make dev
```

`make` lance deux cibles en parallèle :

- `backend` : Uvicorn avec reload sur le port 8000 ;
- `frontend` : Next.js dev sur le port 3000.

Le backend configure Loguru, vérifie la clé JWT hors environnement de
développement, crée FastAPI, ajoute les middlewares et entre dans son lifespan.
Le lifespan construit `ApplicationServices`, qui ouvre les clients Redis,
MongoDB et LLM, crée le workflow et compile le graphe LangGraph une fois.

Un échec Redis entraîne un fallback mémoire locale. Un échec MongoDB laisse le
backend démarrer avec `mongodb_connected=false`. Une clé Hugging Face absente
laisse également le backend démarrer, mais les appels LLM échoueront ensuite.

Un message `Address already in use` signifie qu'un autre processus écoute déjà
sur le port. `clear` ne tue pas ce processus.

## 2. Ouverture du frontend

À l'ouverture de `http://localhost:3000` :

1. le thème sauvegardé, ou la préférence système, est appliqué avant
   l'hydratation ;
2. le frontend lit le JWT et l'email dans `localStorage` ;
3. si un JWT existe, il appelle `GET /api/v1/auth/me` ;
4. le workspace n'est affiché que si le token est validé ;
5. un `GET /health` initial alimente les statuts backend, Redis et MongoDB.

Il n'y a pas de polling automatique du health check. Les nouvelles vérifications
sont déclenchées par le bouton refresh et après upload, ingestion ou reset.

La pastille `model` ne prouve pas que le LLM répond : elle considère le modèle
online quand le backend répond et que le provider déclaré vaut `ollama` ou
`huggingface`.

## 3. Inscription et connexion

En mode register, le frontend enchaîne automatiquement :

```text
POST /api/v1/auth/register
  → AuthService vérifie user:<email>
  → hash PBKDF2-SHA256
  → stockage Redis sans expiration
POST /api/v1/auth/login
  → vérification du hash
  → création du JWT
  → stockage local du JWT et de l'email
```

Les routes protégées utilisent `get_current_user`, qui valide le header Bearer,
la signature et l'expiration du JWT, puis vérifie que le compte existe encore.
Le logout frontend retire uniquement le token local ; il ne révoque pas le JWT
côté serveur.

## 4. Ingestion des documents

Le frontend propose deux actions visibles :

- drag-and-drop ou sélection d'un PDF/CSV, puis `upload & index` ;
- `INGESTION DATA`, qui appelle `/api/v1/ingest/batch` sans body et indexe donc
  le dossier `backend/data` par défaut.

La route `/api/v1/ingest/sample-data` existe, mais n'est pas appelée par le
bouton actuel.

### Upload

1. Le frontend refuse les extensions autres que PDF/CSV.
2. Le backend neutralise le chemin du nom de fichier.
3. Le fichier est conservé dans `backend/data` ; un suffixe UUID évite
   l'écrasement d'un fichier homonyme.
4. Un PDF produit un document par page non vide ; une page est tronquée à 5 000
   caractères.
5. Un CSV produit un document par ligne.
6. Le backend demande en batch les embeddings de `title + snippet`.
7. Les documents sont insérés dans MongoDB.

Si les embeddings échouent, l'étape 7 continue sans champ `embedding`. La
recherche full-text reste possible, contrairement à la recherche vectorielle.
Une nouvelle ingestion ne remplace pas les documents existants : elle ajoute de
nouvelles lignes et peut créer des doublons.

## 5. Envoi d'un message

Le bouton send ou `Cmd/Ctrl+Enter` appelle :

```http
POST /api/v1/chat
Authorization: Bearer <jwt>
Content-Type: application/json
```

Le payload contient le texte, le `conversation_id` courant et tout l'historique
local. Le message d'accueil du frontend est lui aussi envoyé comme message
assistant tant qu'il figure dans la liste locale.

Le message utilisateur est immédiatement ajouté à l'affichage. En cas d'échec
réseau, le texte de l'exception navigateur est ajouté comme message assistant ;
sur Safari, il peut s'agir simplement de `Load failed`.

## 6. Prétraitement dans ChatWorkflow

### 6.1 Identifiant et contexte

Le backend réutilise le `conversation_id` reçu ou génère un UUID. Il lit ensuite
l'historique Redis avant toute exécution du graphe.

### 6.2 Limite de taille

Au-delà de `MAX_USER_MESSAGE_CHARS`, la réponse est immédiate :

- `route="safety"` ;
- `agents_used=["safety"]` ;
- pas de graphe, pas de cache écrit, pas de message ajouté à Redis.

### 6.3 Cache

La clé est :

```text
chat:<conversation_id>:<message.strip().lower()>
```

Un hit retourne `route="cache"` sans exécuter LangGraph et sans ajouter la
répétition à l'historique. La clé ignore l'historique, le corpus, le modèle et les
prompts ; elle peut donc renvoyer une réponse ancienne dans la même conversation.

### 6.4 Cache miss

Le message utilisateur est ajouté à Redis, puis le graphe reçoit un `GraphState`
initial avec le message, l'historique frontend et `evaluation.cache.hit=false`.

## 7. Exécution LangGraph

### 7.1 MemoryAgent

Il relit Redis et choisit :

```python
conversation_context = request_history or stored_history
```

Dès qu'un historique non vide est envoyé par le frontend, Redis n'est donc pas
utilisé comme contexte du modèle pour ce tour.

### 7.2 LLMPlannerAgent

Le planner demande au LLM un `PlannerDecision` JSON : intention, besoins de
retrieval/RAG, étapes, outils et raison. Pydantic valide la structure.

Si l'appel ou le parsing échoue, une règle locale décide :

- salutation exacte connue → `greeting` ;
- demande d'inventaire du corpus → `document_list` ;
- expression arithmétique ou demande de calcul contenant un nombre → `calculation` ;
- résumé sans mot documentaire → `summarization` ;
- mots de planification → `planning` ;
- mots de correction → `correction` ;
- tout le reste → `document_qa` + RAG.

Ainsi, `hey my name is Manda` n'est pas une salutation exacte pour le fallback :
en cas de panne du planner LLM, cette phrase part par défaut vers le RAG.

### 7.3 ToolRouterAgent

Il transforme l'intention en route. Les flags ont priorité :

- `requires_rag=true` → `rag` ;
- sinon `requires_retrieval=true` → `document_qa` ;
- sinon mapping vers `greeting`, `direct_answer`, `calculation`,
  `document_list` ou `fallback`.

Les flags `requires_critic` et `requires_safety` ne modifient pas actuellement le
graphe : ces deux étapes restent obligatoires hors cache.

### 7.4 Branches

```text
greeting
  → réponse statique

direct_answer / fallback
  → SummaryAgent

calculation / document_list
  → ToolExecutorAgent

document_qa / rag
  → SearchAgent
  → HybridRetrieverAgent
  → RerankerAgent
  → ContextCompressionAgent
  → RAGAgent, sauf document_qa avec requires_rag=false
```

`SummaryAgent` est en réalité un agent de réponse directe. Son prompt couvre
question générale, résumé, correction, réécriture et planification.

`ToolExecutorAgent` n'exécute pas un nom d'outil arbitraire produit par le LLM.
Il utilise une allowlist liée à la route : calculatrice AST locale pour
`calculation`, lecture bornée de l'inventaire MongoDB pour `document_list`.

## 8. Branche RAG

### SearchAgent

MongoDB Atlas Search cherche la requête dans `title` (boost 2), `snippet` et
`category`, puis garde 5 résultats.

### HybridRetrieverAgent

Il calcule l'embedding de la requête, exécute `$vectorSearch` avec jusqu'à 8
résultats, concatène full-text et vectoriel, déduplique, trie les scores bruts et
garde 8 candidats. Un échec vectoriel conserve le full-text.

### RerankerAgent

Pour chaque candidat :

```text
score = score_retrieval + 0.25 × mots_communs + 2.0 × cosinus
```

La partie cosinus est omise si le reranking sémantique est désactivé ou si les
embeddings échouent. Les `MAX_RAG_DOCUMENTS` meilleurs sont gardés.

### ContextCompressionAgent

Le mode actif est local : il garde les labels source et tronque les snippets pour
rester sous `MAX_RAG_CONTEXT_CHARS`. Le mode LLM existe mais n'est pas activé.

### RAGAgent

Sans document, il n'appelle pas le LLM et répond qu'aucun document pertinent n'a
été trouvé. Avec des documents :

1. il envoie question, contexte compressé et historique au prompt groundé ;
2. le prompt exige la langue de la question et des citations `[n]` proches de
   chaque affirmation ;
3. le contenu des documents est explicitement traité comme donnée non fiable,
   pas comme instruction ;
4. l'application ajoute ensuite une section `Sources:` avec les trois premiers
   documents.

Si le LLM échoue, les résultats full-text formatés deviennent la réponse de
secours, avec la section Sources.

### CitationValidatorAgent

Après `RAGAgent`, ce nœud vérifie les labels `[n]` dans le corps de la réponse :
au moins un label quand des documents existent, et aucun numéro supérieur au
nombre de documents disponibles. Sans document, la validation est marquée
comme ignorée et réussie. Ce contrôle est structurel : il ne prouve pas que la
phrase citée est sémantiquement supportée par la source.

## 9. Critic, retry, safety et finalisation

### Critic

`LLMCriticAgent` demande un verdict JSON avec scores de grounding, pertinence et
clarté. En cas d'échec, `CriticAgent` vérifie localement : réponse présente,
longueur minimale, documents et section Sources pour une route RAG.

### Retry

- Route RAG refusée avec documents : un seul retry du `RAGAgent`, puis nouveau
  passage critic.
- Route directe refusée : un seul retry du `SummaryAgent`, via
  `prepare_summary_retry`, puis nouveau passage critic.
- Après un retry déjà tenté, la réponse passe au safety même si le critic refuse
  encore.

### Safety

Le garde-fou actif est local. Trois regex masquent clés/tokens/mots de passe et
en-têtes de clés privées avec `[REDACTED_SECRET]`. Une revue LLM existe mais
`use_llm` reste `false` dans le workflow.

### FinalAnswerAgent

Il choisit la première sortie disponible parmi réponse déjà finalisée, draft,
RAG, réponse directe, search et fallback générique. Il ajoute une note de
validation ou de sécurité lorsque nécessaire.

## 10. Retour et affichage

Après le graphe, le backend :

1. ajoute la réponse assistant à Redis ;
2. écrit la réponse dans le cache ;
3. relit l'historique pour calculer `context_messages` ;
4. retourne `ChatResponse`.

Le frontend affiche la réponse puis met à jour le cockpit : route, agents,
outils (`tool_results`), cache, plan, critic, safety, métriques, trace et
sorties brutes. Chaque outil y apparaît avec un statut `ok` ou `failed`.

## 11. Diagnostic rapide

### `Load failed`

La requête n'a généralement pas atteint FastAPI. Vérifier :

```bash
curl http://127.0.0.1:8000/health
lsof -nP -iTCP:8000 -sTCP:LISTEN
```

Si aucun `Incoming request ... path=/api/v1/chat` n'apparaît dans
`backend/logs/multi-agent-backend.log`, le problème est entre le navigateur et
le backend, pas dans les agents.

### Réponse sans documents

Vérifier `mongodb_connected`, l'existence des index Atlas, l'ingestion et les
sorties `search`/`hybrid_retriever` dans le cockpit.

### Réponse lente

Consulter `evaluation.latency_ms`. Le chemin RAG peut appeler le planner, les
embeddings plusieurs fois, le LLM de réponse et le critic. Le retry RAG ajoute un
second appel de génération et de critique.

### Quota Hugging Face

Le planner et le critic ont des fallbacks. Le RAG retombe sur les résultats de
recherche. Le système peut donc renvoyer une réponse dégradée plutôt qu'une erreur
HTTP, mais l'indicateur model peut rester visuellement online.

## 12. Documents complémentaires

- [GUIDE_PROJET.md](GUIDE_PROJET.md) — référence d'architecture et sécurité.
- [AGENTS.md](AGENTS.md) — contrat détaillé de chaque agent.
- [RAG_SYSTEM.md](RAG_SYSTEM.md) — qualité et limites du retrieval.
- [EVALUATION.md](EVALUATION.md) — tests et métriques.
