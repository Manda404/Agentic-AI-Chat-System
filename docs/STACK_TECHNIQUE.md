# Stack technique du projet — rôle de chaque technologie

## 1. Vue d’ensemble

Ce projet est une application de chat avec IA qui combine :
- un backend Python pour orchestrer plusieurs agents,
- un frontend web pour l’interface utilisateur,
- des services d’infrastructure pour la mémoire, la recherche documentaire et l’observabilité.

L’objectif est de permettre à un utilisateur de poser une question, de récupérer des informations dans des documents indexés, et d’obtenir une réponse générée par un modèle de langage.

---

## 2. Backend : ce que chaque technologie fait

### 2.1 FastAPI
- Rôle principal : framework backend Python utilisé pour exposer les API HTTP.
- À quoi ça sert ici : recevoir les requêtes du frontend, traiter les messages de chat, gérer l’authentification et les routes d’ingestion de documents.
- Pourquoi il est utilisé : il est moderne, rapide, simple à lire, et bien adapté aux APIs asynchrones.

### 2.2 Uvicorn
- Rôle principal : serveur ASGI pour exécuter l’application FastAPI.
- À quoi ça sert ici : démarrer le backend localement pour servir l’API.

### 2.3 Pydantic
- Rôle principal : validation et sérialisation des données.
- À quoi ça sert ici : garantir que les requêtes et réponses respectent un format défini, par exemple pour l’authentification ou le chat.
- Pourquoi c’est important : cela évite beaucoup d’erreurs liées aux structures de données.

### 2.4 Python-dotenv
- Rôle principal : charger les variables d’environnement depuis un fichier .env.
- À quoi ça sert ici : configurer les clés API, les URIs Redis Cloud/MongoDB Atlas, les secrets JWT, etc.

### 2.5 OpenAI Python client
- Rôle principal : client HTTP compatible avec l’API OpenAI.
- À quoi ça sert ici : envoyer des prompts au modèle de langage via le routeur Hugging Face.
- Pourquoi il est utilisé : le projet utilise une API compatible OpenAI pour dialoguer avec des modèles LLM.

### 2.6 Loguru
- Rôle principal : système de logging avancé.
- À quoi ça sert ici : tracer les événements du backend, les erreurs, les requêtes, les opérations d’ingestion, etc.
- Pourquoi c’est utile : il simplifie le debugging et l’observabilité du système.

### 2.7 PyJWT
- Rôle principal : gestion des tokens JWT.
- À quoi ça sert ici : créer et vérifier les tokens d’authentification des utilisateurs.

### 2.8 Passlib
- Rôle principal : hachage sécurisé des mots de passe.
- À quoi ça sert ici : stocker des mots de passe de manière sûre au lieu de les conserver en clair.

### 2.9 Python-multipart
- Rôle principal : parser des fichiers envoyés via des formulaires HTTP.
- À quoi ça sert ici : permettre l’upload de fichiers PDF ou CSV depuis le frontend vers le backend.

### 2.10 PyPDF2
- Rôle principal : extraction de texte depuis des fichiers PDF.
- À quoi ça sert ici : convertir le contenu d’un PDF en texte exploitable pour l’indexation et la recherche.

### 2.11 Redis (Redis Cloud)
- Rôle principal : base de données clé-valeur en mémoire / cache, hébergée en managé sur Redis Cloud (tier gratuit).
- À quoi ça sert ici : stocker l’historique des conversations, mettre en cache les réponses, et conserver des données utilisateur de manière temporaire ou rapide.
- Pourquoi c’est utile : cela rend le système plus réactif et permet de conserver des informations de session, sans avoir à héberger de serveur Redis soi-même.

### 2.12 MongoDB Atlas (Atlas Search + Atlas Vector Search)
- Rôle principal : base de données documents managée, avec deux index construits sur la même collection : un index full-text (Atlas Search, basé sur Lucene) et un index vectoriel (Atlas Vector Search).
- À quoi ça sert ici : stocker les documents ingérés (CSV/PDF) et retrouver les informations pertinentes à partir d’une requête utilisateur, à la fois par mots-clés et par similarité sémantique — les deux résultats sont ensuite fusionnés par `HybridRetrieverAgent`.
- Pourquoi c’est utile : c’est la base du mécanisme RAG hybride du projet, sans avoir à faire tourner ni synchroniser deux bases de données séparées (une pour le full-text, une pour les vecteurs).

### 2.13 Langfuse
- Rôle principal : outil d’observabilité et de traçage des appels LLM.
- À quoi ça sert ici : suivre les prompts, les réponses, la latence et les performances des appels au modèle.
- Pourquoi c’est utile : pour mieux comprendre et debuguer les interactions avec le LLM.

### 2.14 LangGraph
- Rôle principal : bibliothèque d’orchestration de workflows agentiques sous forme de graphe d’états.
- À quoi ça sert ici : `backend/app/workflows/chat_workflow.py` construit un vrai `StateGraph` — chaque agent (mémoire, planner, recherche, retrieval hybride, reranking, compression, RAG, critic, safety, réponse finale) est un nœud du graphe, avec des transitions conditionnelles (routage, boucle de correction bornée).
- Ce qu’il faut retenir : l’orchestration n’est pas faite à la main — LangGraph exécute réellement le graphe compilé, avec état partagé (`GraphState`) et checkpointing optionnel.

### 2.15 Embeddings HuggingFace
- Rôle principal : vecteurs numériques représentant le sens d’un texte.
- À quoi ça sert ici : calculés via la route `pipeline/feature-extraction` du HuggingFace Router (le endpoint `/v1/embeddings` compatible OpenAI ne dessert aucun modèle d'embedding testé). Utilisés à deux endroits : à l'ingestion, pour peupler le champ `embedding` de chaque document (indexé par Atlas Vector Search) ; à la requête, par `RerankerAgent` pour un score de similarité sémantique en complément du score lexical, et par `MongoVectorStore` pour la recherche vectorielle elle-même.
- Pourquoi c’est utile : le classement et le recall des documents ne dépendent plus uniquement du recouvrement de mots-clés.

---

## 3. Frontend : ce que chaque technologie fait

### 3.1 Next.js
- Rôle principal : framework React pour construire l’interface web.
- À quoi ça sert ici : servir la page principale de l’application, gérer le routage côté application, et fournir un environnement moderne pour l’UI.

### 3.2 React
- Rôle principal : bibliothèque pour construire l’interface utilisateur.
- À quoi ça sert ici : afficher les messages du chat, gérer les formulaires d’authentification, et mettre à jour l’interface en fonction des réponses backend.

### 3.3 TypeScript
- Rôle principal : langage typé qui améliore la sécurité et la maintenabilité du code.
- À quoi ça sert ici : rendre le frontend plus robuste, plus lisible et plus facile à évoluer.

### 3.4 Lucide React
- Rôle principal : bibliothèque d’icônes.
- À quoi ça sert ici : enrichir l’interface utilisateur avec des icônes visuelles.

### 3.5 Node.js / npm
- Rôle principal : environnement d’exécution JavaScript et gestionnaire de dépendances.
- À quoi ça sert ici : installer les dépendances du frontend et lancer le serveur de développement.

---

## 4. Infrastructure et services externes

Aucun service d'infrastructure n'est auto-hébergé : Redis et MongoDB tournent
tous les deux en cloud, sur des tiers gratuits, aussi bien en développement
local qu'en production. Il n'y a donc plus de `podman-compose`/`docker-compose`
dans le projet.

### 4.1 Redis Cloud
- Rôle principal : instance Redis managée (tier gratuit, 30 Mo).
- À quoi ça sert ici : fournir la mémoire du système (historique de conversation, cache, rate limiting), accessible depuis n'importe quel environnement (dev local ou déploiement) via `REDIS_URL`.

### 4.2 MongoDB Atlas
- Rôle principal : cluster MongoDB managé (tier gratuit M0), avec Atlas Search et Atlas Vector Search activés sur la même collection.
- À quoi ça sert ici : héberger les documents indexés (full-text + vecteurs) et répondre aux requêtes de recherche hybride, via `MONGODB_URI`.

### 4.3 Makefile
- Rôle principal : lancer backend et frontend ensemble en local.
- À quoi ça sert ici : `make install` installe les dépendances (venv Python + npm), `make dev` démarre les deux serveurs en parallèle.

---

## 5. Composants fonctionnels du projet

### 5.1 Les agents
Le workflow LangGraph enchaîne 12 agents spécialisés (rôle détaillé dans
[GUIDE_PROJET.md](GUIDE_PROJET.md#9-les-agents-rôle-par-rôle)) :
- `MemoryAgent` : charge le contexte de conversation.
- `LLMPlannerAgent` : décide de l’intention et du plan (avec fallback déterministe par mots-clés — il n’y a plus d’agent superviseur séparé, cette étape a été fusionnée dans le planner).
- `ToolRouterAgent` : convertit le plan en route concrète pour le graphe.
- `SearchAgent` : récupère des documents pertinents dans MongoDB Atlas (full-text, Atlas Search).
- `HybridRetrieverAgent` : fusionne/déduplique les résultats full-text avec ceux de la recherche vectorielle (MongoDB Atlas Vector Search, via `MongoVectorStore`).
- `RerankerAgent` : réordonne les documents (score lexical + score sémantique via embeddings).
- `ContextCompressionAgent` : réduit le contexte avant envoi au LLM.
- `SummaryAgent` : produit une réponse directe (hors RAG).
- `RAGAgent` : génère une réponse ancrée dans les documents.
- `LLMCriticAgent` : évalue la qualité de la réponse.
- `SafetyGuardAgent` : masque les secrets évidents avant finalisation.
- `FinalAnswerAgent` : assemble la réponse finale.

### 5.2 Le workflow de chat
- Rôle principal : orchestrer l’exécution des agents selon la demande utilisateur, via un `StateGraph` LangGraph compilé une seule fois.
- À quoi ça sert ici : transformer une question simple en une réponse cohérente, parfois en combinant recherche et génération.

### 5.3 Le moteur RAG
- Rôle principal : combiner recherche documentaire et génération par LLM.
- À quoi ça sert ici : répondre aux questions avec un contexte récupéré dans les documents ingérés, au lieu de répondre de manière purement “générative”. Détail complet du pipeline et des limites connues : [backend/app/agents/RAG_SYSTEM.md](backend/app/agents/RAG_SYSTEM.md).

---

## 6. Résumé simple : à quoi sert chaque famille de technologie

- FastAPI / Uvicorn : exposer l’API backend.
- LangGraph : orchestrer le workflow multi-agent en graphe d’états.
- Pydantic : valider les données.
- Redis Cloud : mémoire, cache et historique.
- MongoDB Atlas : recherche documentaire hybride (full-text + vecteurs) et indexation.
- HuggingFace Router / OpenAI client : appels au modèle LLM et aux embeddings.
- Loguru / Langfuse : logs et observabilité.
- Next.js / React / TypeScript : interface utilisateur.
- Makefile : lancer backend + frontend ensemble en local.

---

## 7. En une phrase

Le projet utilise un stack moderne composé de Python pour le backend agentique, de Redis Cloud et MongoDB Atlas pour la mémoire et la recherche hybride, d’un modèle LLM pour la génération, et de Next.js/React pour l’interface utilisateur.
