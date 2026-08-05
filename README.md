<div align="center">

# Agentic RAG Platform

**Une plateforme RAG agentique, multi-agent et observable, construite avec FastAPI, LangGraph, Redis, Elasticsearch et Next.js.**

<img src="gitimg/1.png" alt="Chat Interface" width="600"/>

<img src="gitimg/Architecture-v2.png" alt="System Overview" width="600"/>

</div>

## Problématique

Les assistants IA classiques répondent souvent de manière trop générique : ils ne savent pas toujours quand chercher dans des documents, quand répondre directement, quand citer leurs sources, ni comment vérifier la qualité ou la sécurité de leur réponse.

Ce projet cherche à résoudre cette problématique : **comment construire un assistant conversationnel capable de router une demande, exploiter une base documentaire, produire une réponse sourcée, vérifier sa qualité et rester inspectable par le développeur ?**

## Problème Traité

Le système répond à trois besoins concrets :

- **Répondre à des questions utilisateur** avec une interface web simple.
- **Exploiter des documents internes** grâce à un pipeline RAG basé sur Elasticsearch.
- **Rendre l’exécution transparente** grâce à un cockpit de debug qui affiche la route, les agents appelés, les résultats bruts, le plan, les métriques de retrieval, le critic et le safety guard.

L’objectif n’est pas seulement de faire un chatbot, mais de montrer une architecture agentique structurée, progressive et proche d’un système production-grade.

## Méthode De Résolution

Le projet résout le problème avec un workflow multi-agent orchestré par **LangGraph** :

```text
Utilisateur
  -> Frontend Next.js
  -> Backend FastAPI
  -> MemoryAgent
  -> LLMPlannerAgent
  -> ToolRouterAgent
  -> Search / RAG / Direct Answer
  -> LLMCriticAgent
  -> SafetyGuardAgent
  -> FinalAnswerAgent
  -> ChatResponse
```

La méthode est la suivante :

1. **Comprendre la demande** : le planner LLM identifie l’intention (avec fallback déterministe si le LLM échoue).
2. **Choisir les bons outils** : le tool router décide si la réponse doit être directe, documentaire ou RAG.
3. **Chercher les sources** : Elasticsearch récupère les documents pertinents.
4. **Améliorer le contexte** : retrieval hybride préparé, reranking lexical + sémantique (embeddings HuggingFace) et compression de contexte.
5. **Générer une réponse** : le RAGAgent répond à partir des documents disponibles.
6. **Contrôler la réponse** : le critic vérifie qualité, clarté et grounding.
7. **Sécuriser la sortie** : le safety guard masque les secrets évidents.
8. **Retourner une réponse compatible frontend** : avec réponse finale, agents utilisés, métriques et traces debug.

## Architecture En Bref

**Backend**
- FastAPI pour l’API HTTP.
- LangGraph pour l’orchestration multi-agent.
- Redis pour l’historique conversationnel et le cache.
- Elasticsearch pour la recherche documentaire.
- HuggingFace Router compatible OpenAI pour les appels LLM.
- Loguru et Langfuse optionnel pour l’observabilité.

**Frontend**
- Next.js / React / TypeScript.
- Interface de chat.
- Cockpit de debug : route, agents, sorties brutes, plan, critic, safety, retrieval metrics.

**Agents Principaux**
- `MemoryAgent`
- `LLMPlannerAgent`
- `ToolRouterAgent`
- `SearchAgent`
- `HybridRetrieverAgent`
- `RerankerAgent`
- `ContextCompressionAgent`
- `RAGAgent`
- `LLMCriticAgent`
- `SafetyGuardAgent`
- `FinalAnswerAgent`

## Ce Que Le Projet Démontre

- Une architecture multi-agent claire et extensible.
- Un workflow LangGraph réel, pas seulement une orchestration manuelle.
- Un RAG progressif : recherche, reranking, compression, réponse sourcée.
- Une compatibilité API stable avec `/api/v1/chat`.
- Des champs debug utiles : `plan`, `critic_score`, `retrieval_metrics`, `safety_feedback`, `trace_id`.
- Une base pédagogique pour aller vers un système agentique plus robuste.

## Démarrage Rapide

1. Copier les fichiers `.env.example` et renseigner les clés nécessaires.
2. Démarrer Redis et Elasticsearch :

```bash
podman-compose up -d
```

3. Démarrer le backend :

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

4. Démarrer le frontend :

```bash
cd frontend
npm install
npm run dev
```

5. Ouvrir :

```text
http://localhost:3000
```

## Documentation

Pour aller plus loin :

- [Architecture](docs/ARCHITECTURE.md)
- [Agents](docs/AGENTS.md)
- [RAG](docs/RAG.md)
- [RAG — détail du pipeline et limites connues](backend/app/agents/RAG_SYSTEM.md)
- [Evaluation](docs/EVALUATION.md)
- [Production Readiness](docs/PRODUCTION_READINESS.md)
- [État de l’art](ETAT_DE_L_ART.md)

## Positionnement

Ce projet est un **starter production-grade avancé** : il reste lisible et pédagogique, mais il introduit déjà les patterns importants des systèmes agentiques modernes.

Il n’est pas encore une plateforme d’entreprise complète : le store vectoriel réel, le reranker cross-encoder, le checkpoint persistant et l’évaluation continue restent des pistes d’évolution.
