"""
Agents IA orchestrés par `ChatWorkflow` : mémoire, planification LLM,
tool routing/execution, recherche hybride, reranking, compression de contexte,
RAG, validation des citations, critique, sécurité et réponse finale.

Chaque fichier de ce package représente un nœud ou un composant réutilisable du
graphe LangGraph. Les agents lisent et modifient `GraphState`, retournent un
`AgentResult` visible dans le cockpit frontend, et gardent des fallbacks simples
pour que le projet reste pédagogique et robuste en local.
"""
