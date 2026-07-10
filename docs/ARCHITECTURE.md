# Architecture

## Vue D'Ensemble

Le projet expose un chat IA via un frontend Next.js et un backend FastAPI. Le backend conserve le contrat `/api/v1/chat`, mais l'exécution interne passe par un graphe LangGraph.

```text
Frontend Next.js
  -> Backend FastAPI
  -> ChatWorkflow LangGraph
  -> MemoryAgent
  -> SupervisorAgent
  -> LLMPlannerAgent
  -> ToolRouterAgent
  -> Search / Retrieval / RAG / Direct Answer
  -> LLMCriticAgent
  -> SafetyGuardAgent
  -> FinalAnswerAgent
  -> Redis history/cache
  -> ChatResponse
```

## Compatibilité API

Les champs historiques restent présents :
- `conversation_id`
- `answer`
- `route`
- `agents_used`
- `agent_results`
- `cached`
- `context_messages`

Les champs debug ajoutés sont optionnels :
- `plan`
- `critic_feedback`
- `critic_passed`
- `critic_score`
- `retrieval_metrics`
- `safety_feedback`
- `safety_passed`
- `evaluation`
- `trace_id`

## Checkpointing

Le checkpoint LangGraph est désactivé par défaut.

```env
LANGGRAPH_CHECKPOINT_ENABLED=false
LANGGRAPH_CHECKPOINT_BACKEND=memory
```

Quand il est activé en mode `memory`, le workflow compile le graphe avec `MemorySaver` et passe `thread_id=conversation_id` à l'exécution.
