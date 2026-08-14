# Comment fonctionne le projet — pas à pas

Ce document a un seul objectif : que tu comprennes **ce qui se passe réellement**, dans l'ordre, quand tu utilises ce projet — du démarrage du serveur jusqu'à l'affichage d'une réponse dans le chat. Pas un catalogue de référence (ça, c'est [GUIDE_PROJET.md](GUIDE_PROJET.md) et [AGENTS.md](AGENTS.md)) : une histoire, racontée dans l'ordre chronologique exact d'exécution, avec pour chaque étape le **quoi**, le **pourquoi**, et le **et si ça échoue ?**.

Contenu vérifié directement contre le code le 2026-08-14 (branche `feature/async-io-performance-fix`, après le passage du backend en I/O réellement asynchrones).

---

## Vue d'ensemble en 30 secondes

Le projet, c'est un chat avec IA. Tu poses une question dans une page web (frontend Next.js). Cette question part vers un serveur (backend FastAPI) qui, au lieu de répondre bêtement avec un seul appel au modèle de langage, fait passer ta question à travers une **chaîne de 12 petits programmes spécialisés** (des "agents") : l'un se souvient de la conversation, l'un décide quoi faire, l'un cherche dans des documents, l'un reclasse les résultats, l'un génère la réponse, l'un vérifie qu'elle est correcte, l'un vérifie qu'elle ne contient pas de secret. Chaque agent fait une seule chose bien précise, puis passe la main au suivant. À la fin, tu reçois une réponse — et le frontend te montre aussi **tout ce qui s'est passé** dans un "cockpit de debug".

```text
Toi (navigateur)
   → Frontend Next.js
      → Backend FastAPI
         → Cache Redis (déjà répondu à ça ? → réponse immédiate)
         → Graphe LangGraph (les 12 agents, dans l'ordre)
      ← Réponse + tout le détail du trajet
   ← Affichage : réponse + cockpit
```

Le reste de ce document déroule chaque flèche ci-dessus, une par une.

---

## Étape 0 — Démarrer le projet

Avant qu'un utilisateur ne fasse quoi que ce soit, deux serveurs doivent tourner :

```bash
make install   # installe les dépendances Python (venv) + les dépendances JS (npm)
make dev       # lance les deux serveurs en parallèle
```

`make dev` lance concrètement deux process :
- **Backend** (`uvicorn app.main:app --reload --port 8000`) : au démarrage, `backend/app/main.py` configure le logger, vérifie que `AUTH_SECRET_KEY` a été changé (sauf en dev), crée l'app FastAPI, empile les middlewares (sécurité, rate limiting, logs, CORS), puis enregistre les 4 groupes de routes (`health`, `auth`, `ingest`, `chat`). C'est aussi à ce moment que `ChatWorkflow()` est construit **une seule fois** (dans `chat_router.py`) : il ouvre la connexion Redis, la connexion MongoDB Atlas, initialise le client LLM — et construit le graphe des 12 agents, compilé une seule fois pour toute la durée de vie du process.
- **Frontend** (`next dev -p 3000`) : sert la page unique de l'application (`frontend/app/page.tsx`).

Aucune base de données locale à lancer : Redis (Redis Cloud) et MongoDB (Atlas) sont déjà hébergés en ligne, sur des tiers gratuits — le backend s'y connecte directement via les URLs présentes dans `backend/.env`.

**Et si Redis ou MongoDB sont injoignables ?** Le backend ne plante pas. `RedisMemoryService` bascule sur un dictionnaire Python en mémoire (les données seront perdues au redémarrage, mais le chat continue de fonctionner). `SearchService` marque simplement `available=False` : la recherche documentaire échouera proprement, mais l'authentification et les réponses directes (non documentaires) continuent de marcher.

---

## Étape 1 — Ouvrir l'application

Quand tu ouvres `http://localhost:3000`, le frontend affiche un écran de connexion/inscription, et interroge en tâche de fond `GET /health` (sans authentification nécessaire) pour savoir si le backend, Redis et MongoDB sont bien vivants. C'est ce qui allume les petites pastilles de statut ("backend", "redis", "mongodb", "model") que tu vois dans l'interface.

## Étape 2 — Créer un compte / se connecter

C'est la première vraie interaction avec le backend, et elle mérite d'être comprise en détail parce qu'elle illustre un pattern qu'on retrouve partout dans ce projet : **stocker dans Redis, jamais en clair**.

1. Tu remplis email + mot de passe, tu cliques "register".
2. Le frontend envoie `POST /api/v1/auth/register`.
3. `AuthService.register_user()` vérifie d'abord si la clé `user:<email>` existe déjà dans Redis (`await memory_service.get_value(...)`).
4. Si non : le mot de passe est haché (`pbkdf2_sha256`, jamais stocké en clair) et l'ensemble `{email, hashed_password}` est écrit dans Redis **sans expiration** (`ttl=-1`) — un compte créé reste valide indéfiniment.
5. Tu cliques ensuite "login" → `POST /api/v1/auth/login` → `AuthService.authenticate_user()` relit la clé, vérifie le mot de passe haché, et si tout est bon, `TokenService.create_access_token()` fabrique un **JWT** signé (un jeton qui prouve ton identité) valable `AUTH_TOKEN_EXPIRY_MINUTES` (120 minutes par défaut).
6. Le frontend garde ce token en mémoire et l'attache à **toutes** les requêtes suivantes dans l'en-tête `Authorization: Bearer <token>`.

**Pourquoi c'est important pour la suite :** chaque route utile du projet (chat, ingestion, historique) est protégée par `Depends(get_current_user)`. Cette dépendance FastAPI lit le header, décode le JWT, puis revérifie dans Redis que l'utilisateur existe toujours (`await auth_service.get_user(email)`) — si tu supprimes le compte, le token devient inutile même s'il n'a pas encore expiré. Si une seule de ces vérifications échoue, tu reçois une `401` immédiate, avant même d'atteindre la logique métier.

## Étape 3 — Ingérer des documents (optionnel, mais nécessaire pour le RAG)

Sans documents indexés, le chat peut quand même répondre (mode direct), mais ne pourra jamais faire de recherche documentaire. Trois façons d'indexer, toutes protégées par authentification :
- `POST /ingest/sample-data` : indexe le CSV d'exemple fourni avec le projet ;
- `POST /ingest/upload` : tu uploades un PDF ou CSV depuis l'interface ;
- `POST /ingest/batch` : le backend parcourt un dossier serveur entier.

Dans tous les cas, la même mécanique se déclenche :

1. Le fichier est lu et transformé en une liste de documents structurés (`title`, `snippet`, `category`, `source`, et pour les PDF : `file_name`/`page_number`).
2. **Avant** l'indexation, `_attach_embeddings()` calcule un vecteur numérique (`embedding`, 384 nombres) pour chaque document, via un appel à HuggingFace (modèle `BAAI/bge-small-en-v1.5`). Un embedding, c'est une représentation mathématique du **sens** du texte — deux textes proches en sens auront des vecteurs proches, même s'ils n'utilisent pas les mêmes mots. C'est ce qui permettra plus tard la recherche "sémantique", pas seulement par mots-clés.
3. Si ce calcul d'embedding échoue (quota, modèle indisponible), l'ingestion continue **quand même**, juste sans ce champ — le document restera cherchable en full-text, mais invisible pour la recherche vectorielle tant qu'il n'est pas ré-ingéré.
4. Les documents (avec ou sans `embedding`) sont insérés dans la même collection MongoDB Atlas (`documents`), via `await search_service.bulk_index_documents(...)`.

Cette **même collection** sert ensuite à deux types de recherche complètement différents (voir Étape 4.5) : un index full-text (mots-clés) et un index vectoriel (sens), tous deux construits sur les documents que tu viens d'indexer.

---

## Étape 4 — Envoyer un message : le trajet complet

C'est le cœur du projet. Tu tapes une question, tu appuies sur Entrée. Voici, dans l'ordre **exact** où le code les exécute, tout ce qui se passe avant que tu voies une réponse.

### 4.0 — Le frontend envoie la requête

`POST /api/v1/chat` avec `{ message, conversation_id, history }`. `conversation_id` est `null` la toute première fois — le backend en génère un nouveau (`uuid4`) et te le renvoie ; le frontend le réutilisera pour tous les messages suivants de la même conversation.

### 4.1 — Vérification de taille

Avant quoi que ce soit d'autre, `ChatWorkflow.run()` vérifie que ton message ne dépasse pas `MAX_USER_MESSAGE_CHARS` (8000 caractères). Si c'est le cas, tu reçois immédiatement une réponse `route="safety"` sans qu'aucun agent ne soit appelé — une protection simple contre les prompts abusifs.

### 4.2 — Vérification du cache

Le backend calcule une clé `chat:<conversation_id>:<message normalisé en minuscules>` et regarde si Redis a déjà une réponse pour **exactement** cette clé (`await cache_service.get_value(...)`).

- **Cache hit** : la réponse stockée est renvoyée telle quelle, `route="cache"`, **aucun agent n'est exécuté**. C'est le chemin le plus rapide du projet.
- **Cache miss** (le cas normal) : on continue.

*Limite à connaître* : la clé est un match exact — poser la même question autrement formulée, ou depuis une autre conversation, ne touchera jamais ce cache.

### 4.3 — MemoryAgent : charger le contexte

Premier agent du graphe. Il regarde s'il y a un historique envoyé par le frontend (`request.history`) — s'il y en a un, il est prioritaire. Sinon, il va chercher l'historique stocké côté serveur (`await memory_service.get_messages(conversation_id)`, une lecture Redis). Le résultat (`conversation_context`) est mis à disposition de tous les agents suivants.

### 4.4 — LLMPlannerAgent : décider quoi faire

C'est l'agent qui **comprend** ta demande. Il envoie ta question au modèle de langage avec un prompt qui lui demande de répondre en JSON structuré : quelle est l'intention (`greeting`, `document_qa`, `summarization`, ...), a-t-on besoin de chercher des documents (`requires_rag`), faut-il vérifier la réponse (`requires_critic`), etc.

**Et si le LLM ne répond pas ou répond n'importe quoi ?** L'agent ne plante pas : il bascule sur une classification par mots-clés, faite en local, sans appel réseau (salutation détectée par une liste de mots comme "bonjour"/"hello", résumé par des mots comme "summarize", sinon `document_qa` par défaut). C'est le filet de sécurité qui garantit que le chat continue de fonctionner même si le fournisseur LLM est en panne.

### 4.5 — ToolRouterAgent : transformer la décision en chemin concret

Le plan produit par le planner est encore abstrait ("il faut de la recherche documentaire"). Cet agent le traduit en une **route** que le graphe sait exécuter : `greeting`, `direct_answer`, `document_qa`, `rag`, ou `fallback`. C'est cette route qui détermine la suite : le graphe part maintenant dans l'une de trois directions.

```text
route = "greeting"        → réponse de salutation statique, on saute direct à l'étape 4.10
route = "direct_answer"   → SummaryAgent (étape 4.9), on saute la recherche documentaire
route = "document_qa/rag" → pipeline documentaire complet (étapes 4.6 à 4.9)
```

### 4.6 — SearchAgent : recherche par mots-clés

*(uniquement si route documentaire)* Ta question part telle quelle vers MongoDB Atlas, via une requête `$search` (l'index Atlas Search, basé sur Lucene) qui cherche les mots de ta question dans les champs `title` (avec un bonus ×2), `snippet` et `category`. Jusqu'à 5 documents reviennent, avec un score de pertinence.

*Depuis le passage à l'I/O asynchrone : cet appel réseau (`await asyncio.to_thread(...)`) ne bloque plus le serveur pendant qu'il attend la réponse de Mongo — d'autres utilisateurs peuvent être servis en parallèle pendant ce temps.*

### 4.7 — HybridRetrieverAgent : ajouter la recherche par le sens

Cet agent va chercher un **second** jeu de résultats, cette fois par similarité de sens plutôt que par mots-clés : il transforme ta question en embedding (même mécanisme qu'à l'ingestion), puis interroge l'index vectoriel MongoDB Atlas (`$vectorSearch`) pour trouver les documents dont l'embedding stocké est le plus proche de celui de ta question. Il fusionne ensuite les deux listes (mots-clés + sens), enlève les doublons (même titre + même fichier/page), trie par score, et garde les 8 meilleurs.

*Pourquoi deux recherches différentes ?* Le mot-clé trouve ce qui contient exactement tes termes ; le sens trouve ce qui **parle du même sujet** même avec d'autres mots. Combiner les deux donne un meilleur rappel qu'une seule méthode.

### 4.8 — RerankerAgent : reclasser par pertinence réelle

Les résultats fusionnés ne sont pas encore dans le meilleur ordre pour répondre. Cet agent recalcule un score combiné pour chaque document : le score de recherche + un bonus si les mots de ta question apparaissent dans le titre/extrait (score "lexical"), plus — si activé (`SEMANTIC_RERANKER_ENABLED=true`) — une similarité de sens entre ta question et chaque document (score "sémantique"). Les documents sont retriés selon ce score combiné, et seuls les `MAX_RAG_DOCUMENTS` (5 par défaut) meilleurs sont gardés pour la suite.

### 4.9 — ContextCompressionAgent : préparer le texte pour le LLM

On ne peut pas envoyer des documents entiers au modèle de langage (coût, limite de taille de prompt). Cet agent réduit chaque extrait à une taille raisonnable, tout en gardant les labels de source (titre, fichier, page) pour que la réponse finale puisse citer ses sources, et respecte une limite globale (`MAX_RAG_CONTEXT_CHARS`, 4000 caractères par défaut).

### 4.9bis — RAGAgent *ou* SummaryAgent : générer la réponse

Deux chemins possibles selon la route décidée à l'étape 4.5 :

- **RAGAgent** (route documentaire) : envoie ta question + le contexte compressé au LLM, avec un prompt qui lui **interdit explicitement** de répondre en dehors des documents fournis. S'il n'y a aucun document disponible, l'agent ne tente même pas d'appeler le LLM — il répond directement qu'il n'a rien trouvé, pour éviter d'halluciner une réponse. Une section `Sources:` est toujours ajoutée à la fin.
- **SummaryAgent** (route directe/salutation/résumé) : répond directement à partir de ta question et du contexte de conversation, sans recherche documentaire.

Dans les deux cas, le résultat est stocké comme `draft_answer` — une réponse "brouillon", pas encore validée.

### 4.10 — LLMCriticAgent : vérifier la réponse avant de la laisser sortir

Cet agent relit la réponse brouillon avec le LLM et lui demande de juger : est-elle pertinente ? claire ? bien ancrée dans les documents s'il y en avait ? Le résultat est un score et un verdict `passed: true/false`.

**Et si le LLM critic échoue ?** Bascule sur `CriticAgent`, un jeu de règles locales déterministes (réponse non vide, longueur suffisante, sources visibles si la route l'exigeait) — pas d'appel réseau, donc pas de nouveau point de défaillance.

**Si le critic refuse la réponse :** le graphe ne s'arrête pas là. Si aucune correction n'a encore été tentée pour cette requête, il relance **une seule fois** l'étape 4.9bis (`RAGAgent` ou `SummaryAgent`, selon la route) pour obtenir une meilleure réponse, puis revient ici. Cette boucle est strictement bornée à un essai — impossible qu'elle tourne indéfiniment.

### 4.11 — SafetyGuardAgent : dernier filtre avant la sortie

Un ultime passage cherche, par expression régulière, des clés API, tokens, mots de passe ou clés privées qui auraient pu se glisser dans la réponse (par exemple si un document indexé en contenait un). Toute correspondance est remplacée par `[REDACTED_SECRET]`.

### 4.12 — FinalAnswerAgent : assembler la réponse finale

Ce dernier agent ne génère rien de nouveau : il choisit la meilleure réponse disponible parmi celles produites jusqu'ici, et y ajoute une note visible si le critic ou le safety guard n'étaient pas satisfaits (pour rester transparent plutôt que de cacher un problème).

### 4.13 — Sauvegarde et retour au frontend

`ChatWorkflow.run()` reprend la main après la fin du graphe : il enregistre ta question et la réponse dans l'historique Redis de la conversation (`await memory_service.append_message(...)`, deux fois), met la réponse en cache pour la prochaine fois (`await cache_service.set_value(...)`), puis renvoie un objet complet au frontend — la réponse, mais aussi la route empruntée, la liste des agents utilisés, le plan du planner, les métriques de retrieval, le score du critic, le statut safety, et un `trace_id`.

### 4.14 — Le frontend affiche tout

La réponse s'affiche dans la conversation. Le **cockpit de debug** (visible dans l'interface) déplie tout le reste : quelle route a été choisie, quels agents ont tourné, le plan, le score du critic, le statut sécurité, les métriques de retrieval, et la sortie brute de chaque agent. C'est volontaire : le projet ne veut pas juste te donner une réponse, il veut te montrer **comment** elle a été construite.

---

## Étape 5 — Vue d'ensemble des filets de sécurité

Un principe traverse tout ce trajet : **aucune panne isolée ne doit faire planter toute la conversation**. Récapitulatif de qui se rattrape comment :

| Si ça échoue... | Alors... |
|---|---|
| Redis (mémoire/cache) | bascule sur un stockage en mémoire locale du process |
| MongoDB (recherche) | le nœud continue avec une liste de résultats vide |
| Recherche vectorielle | continue avec les seuls résultats par mots-clés |
| Calcul d'embedding (rerank) | retombe sur le score par mots-clés seul |
| Planner LLM | bascule sur une classification par mots-clés locale |
| Génération RAG (LLM) | retombe sur les résultats de recherche bruts |
| Critic LLM | bascule sur des règles locales déterministes |
| N'importe quel nœud "swallow_errors" | log l'erreur, produit un résultat de repli explicite, le graphe continue |

---

## Un exemple concret, du premier au dernier pas

Question posée : **"What is Langfuse used for?"**

```text
1.  Frontend → POST /api/v1/chat {message: "What is Langfuse used for?", conversation_id: null}
2.  Backend génère conversation_id = "a1b2c3..."
3.  Longueur du message OK (bien en dessous de 8000 caractères)
4.  Cache miss (première fois qu'on pose cette question dans cette conversation)
5.  MemoryAgent : conversation_context = [] (nouvelle conversation)
6.  LLMPlannerAgent : intent="document_qa", requires_rag=true
7.  ToolRouterAgent : route="rag"
8.  SearchAgent : 5 résultats full-text depuis MongoDB Atlas
9.  HybridRetrieverAgent : + résultats vectoriels → fusion → 8 documents (full_text_count=5, vector_count=8, hybrid_count=8)
10. RerankerAgent : reclassés par score lexical+sémantique → 5 meilleurs gardés
11. ContextCompressionAgent : contexte réduit à < 4000 caractères
12. RAGAgent : appelle le LLM avec la question + le contexte → réponse ancrée + "Sources: ..."
13. LLMCriticAgent : score=0.95, passed=true → pas de retry nécessaire
14. SafetyGuardAgent : aucun secret détecté, passed=true
15. FinalAnswerAgent : choisit la réponse RAG telle quelle
16. Historique + cache mis à jour dans Redis
17. Frontend affiche la réponse + le cockpit (route=rag, 9 agents utilisés, critic_score=0.95, ...)
```

---

## Pour aller plus loin

- [GUIDE_PROJET.md](GUIDE_PROJET.md) — architecture complète, stack technique, configuration, sécurité, limites connues.
- [AGENTS.md](AGENTS.md) — fiche détaillée de chaque agent (entrées/sorties précises dans `GraphState`, code interne).
- [RAG_SYSTEM.md](RAG_SYSTEM.md) — le pipeline documentaire (étapes 4.6 à 4.9) en détail, avec les bugs connus fichier:ligne.
- [EVALUATION.md](EVALUATION.md) — comment le projet teste automatiquement que ce trajet fonctionne comme prévu.
