# Documentation — Agentic RAG Platform

Cette documentation décrit l'état réel du projet sur la branche
`feature/async-io-performance-fix`, vérifié contre le code le **18 août 2026**.

## Parcours conseillé

1. [FONCTIONNEMENT.md](FONCTIONNEMENT.md) — suivre une utilisation complète,
   du démarrage jusqu'à l'affichage de la réponse.
2. [GUIDE_PROJET.md](GUIDE_PROJET.md) — comprendre l'architecture, l'API, la
   configuration, les données, la sécurité et les limites opérationnelles.
3. [AGENTS.md](AGENTS.md) — connaître le rôle, les entrées, les sorties et les
   fallbacks de chaque agent LangGraph.
4. [RAG_SYSTEM.md](RAG_SYSTEM.md) — approfondir l'ingestion, le retrieval
   hybride, le reranking, les citations et les limites de qualité.
5. [EVALUATION.md](EVALUATION.md) — exécuter les tests et mesurer la qualité du
   retrieval.

## Ce qui est réellement implémenté

- API FastAPI protégée par JWT pour le chat, l'ingestion et la gestion du
  contexte conversationnel.
- Graphe LangGraph de 17 nœuds, compilé une fois par processus backend.
- Planning LLM structuré avec fallback déterministe.
- Recherche MongoDB Atlas full-text et vectorielle, puis reranking lexical et
  sémantique.
- Génération RAG avec consignes de grounding et citations dans le texte, puis
  ajout automatique d'une section `Sources:`.
- Mémoire, comptes et cache via Redis, avec fallback local en mémoire.
- Critic LLM avec fallback déterministe et garde-fou de sortie par regex.
- Registre borné de trois outils déterministes : calculatrice arithmétique,
  inventaire documentaire et validation structurelle des citations.
- Frontend Next.js avec authentification, validation de session, upload PDF/CSV,
  ingestion par dossier, reset des données et cockpit de debug.
- I/O réseau asynchrones pour le LLM et Redis ; appels PyMongo déportés dans des
  threads pour ne pas bloquer l'event loop.

## Ce qui n'est pas garanti

- `LLM_PROVIDER=ollama` est accepté par la configuration, mais Ollama n'est pas
  branché dans `LLMService` : le chemin LLM réel utilise Hugging Face.
- La pastille `model` du frontend ne sonde pas le fournisseur LLM ; elle reflète
  seulement la configuration retournée par `/health`.
- Le safety guard n'est pas une solution DLP complète et ne traite pas à lui
  seul les prompt injections.
- Le validateur de citations contrôle les labels `[n]`, pas le support
  sémantique de chaque affirmation.
- Le cache n'est ni sémantique ni sensible à la version du corpus ou du modèle.
- Le projet n'a pas encore de tests frontend, de tests de charge, de benchmark
  de génération/groundedness automatisé, ni de rate limiting distribué.

## Règle de maintenance

Lorsqu'un changement touche `backend/app/workflows/`, `backend/app/agents/`, les
routes API, les modèles de réponse, la configuration ou les actions du frontend,
mettre à jour le document spécialisé correspondant et la date de vérification.
Les affirmations de cette documentation distinguent volontairement :

- le chemin nominal ;
- le mode dégradé ou fallback ;
- le code disponible mais non activé ;
- les limites ou anomalies connues.
