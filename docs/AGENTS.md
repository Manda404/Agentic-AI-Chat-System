# Agents

## MemoryAgent

Charge l'historique depuis Redis ou depuis l'historique envoyé par le frontend.

## SupervisorAgent

Produit une route initiale rapide : `greeting`, `search`, `summary`, `rag`, `planning`, `correction`.

## LLMPlannerAgent

Produit un `PlannerDecision` validé par Pydantic :
- intent ;
- besoin de retrieval ;
- besoin de RAG ;
- étapes ;
- outils ;
- raison.

Si le LLM échoue ou renvoie un JSON invalide, l'agent utilise un fallback déterministe.

## ToolRouterAgent

Convertit le plan en route LangGraph sûre :
- `greeting`
- `direct_answer`
- `document_qa`
- `rag`
- `fallback`

## SearchAgent

Interroge Elasticsearch et conserve les métadonnées source.

## HybridRetrieverAgent

Fusionne les résultats Elasticsearch avec une recherche vectorielle optionnelle. Le port vectoriel est prêt, mais le fallback par défaut ne force aucune dépendance lourde.

## RerankerAgent

Rerank heuristique basé sur le score Elasticsearch et le recouvrement lexical avec la question.

## ContextCompressionAgent

Réduit les snippets envoyés au LLM et conserve les labels sources.

## RAGAgent

Génère une réponse ancrée dans les documents rerankés/compressés et conserve les sources.

## LLMCriticAgent

Évalue la réponse avec un LLM et produit un `CriticReview`. Si le LLM est indisponible, il bascule vers le critic déterministe.

## SafetyGuardAgent

Détecte les secrets évidents, tokens, clés API et clés privées. Il peut aussi appeler un safety review LLM si activé.

## FinalAnswerAgent

Normalise la réponse finale et ajoute les notes de critic/safety si nécessaire.
