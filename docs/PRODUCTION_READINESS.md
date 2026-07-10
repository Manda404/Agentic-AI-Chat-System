# Production Readiness

## Déjà Amélioré

- Graphe LangGraph réel.
- Planner LLM avec validation Pydantic et fallback.
- Tool router explicite.
- Retrieval avancé extensible.
- Reranking heuristique.
- Compression de contexte.
- Critic LLM avec fallback déterministe.
- Safety guard anti-secret.
- Métriques retrieval exposées.
- Champs debug frontend.
- Checkpoint LangGraph optionnel en mémoire.

## Configuration Importante

```env
AUTH_SECRET_KEY=change-me-in-real-projects-use-long-random-string
MAX_USER_MESSAGE_CHARS=8000
MAX_RAG_CONTEXT_CHARS=4000
MAX_RAG_DOCUMENTS=5
LLM_TIMEOUT_SECONDS=60
LANGGRAPH_CHECKPOINT_ENABLED=false
LANGGRAPH_CHECKPOINT_BACKEND=memory
```

## Points À Durcir Avant Production

- Rendre `AUTH_SECRET_KEY` obligatoire hors développement.
- Ajouter un vrai timeout HTTP côté client LLM.
- Brancher un store vectoriel réel.
- Ajouter un reranker cross-encoder ou LLM optionnel.
- Ajouter un framework d'évaluation continu.
- Ajouter des métriques Prometheus/OpenTelemetry si besoin.
- Ajouter un checkpointer persistant si les workflows deviennent longs.
- Réviser CORS et rate limiting selon l'environnement.

## Sécurité

Le `SafetyGuardAgent` masque les secrets évidents dans les réponses. Il ne remplace pas :
- une gestion stricte des secrets ;
- des logs sans données sensibles ;
- des politiques d'accès ;
- une revue sécurité applicative complète.
