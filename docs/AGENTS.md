# Agent et composants LangGraph

Le parcours courant utilise Hugging Face et quatre agents : planification → recherche → synthèse → vérification, puis contrôles locaux. Le chercheur fournit preuves et brouillon ; le synthétiseur peut s’abstenir, et le vérificateur peut refuser la publication. Budget global avec une correction maximum : 13 appels LLM et 90 secondes par défaut. Voir [ARCHITECTURE_AGENT.md](ARCHITECTURE_AGENT.md).

Architecture courante du 10 septembre 2026. Le parcours documentaire est piloté par **une équipe de quatre agents**, dans un graphe de cinq nœuds. Voir [ARCHITECTURE_AGENT.md](ARCHITECTURE_AGENT.md).

| Nœud | Responsabilité |
|---|---|
| `route` | Orientation locale selon la question et le mode explicite |
| `documentary` | Agent : choisir une recherche, lire un passage découvert, répondre, demander une précision ou s’abstenir |
| `answer` | Chemins directs : salutation, calcul, inventaire, général ou transformation de texte |
| `validate` | Contrôle indépendant du brouillon et des citations |
| `finalize` | Publication ou abstention, puis filtre de secrets |

Le parcours documentaire traverse `route → documentary → validate → finalize`. Les cinq nœuds ne sont donc pas cinq appels LLM successifs. La boucle interne de recherche est bornée à deux recherches, trois outils et quatre appels LLM par passe de recherche ; une seule correction est autorisée, pour treize appels LLM maximum au total. Le timeout vaut 90 secondes par défaut.

`DocumentaryTools` expose seulement `rechercher(query)` et `lire_passage(passage_id)`. Le serveur impose les permissions et refuse la lecture d’un ID non découvert. `RetrievalPipeline` assemble SearchAgent, HybridRetrieverAgent, RerankerAgent et ContextCompressionAgent : ces composants ne sont pas des agents autonomes supplémentaires.

Pour une réponse, `GraphState.selected_documents` contient les extraits exacts du dernier contexte présenté au modèle. Les labels sont ceux de cette décision. La validation locale contrôle les références ; elle ne prouve pas la vérité des affirmations. `critic_score` vaut `null` et `factuality_evaluated=false`.

`evaluation.answer.status` distingue `answered`, `clarification_requested` et `abstained`. Les compteurs et actions sont exposés dans les diagnostics, sans raisonnement interne du modèle.

## Référence et expériences

`ChatWorkflow(strategy="baseline")` conserve le parcours déterministe `route → retrieve → answer → validate → finalize`, avec au plus une génération. Cette stratégie sert à comparer coût et qualité avec l’agent.

`evaluation/experimental/` contient LLMPlannerAgent, CorrectiveRAGAgent et LLMCriticAgent. Ils ne sont ni importés ni instanciés par le graphe HTTP.

## Modifier le parcours

Préférer une modification du composant responsable à l’ajout d’un nœud. Garder la compatibilité de `ChatResponse`, la sélection documentaire commune et les budgets imposés par le code. Tester comportements, pannes, permissions et abstention. Mettre à jour ce document, [FONCTIONNEMENT.md](FONCTIONNEMENT.md), [RAG_SYSTEM.md](RAG_SYSTEM.md) et [ARCHITECTURE_AGENT.md](ARCHITECTURE_AGENT.md) si le contrat change.

La recherche web optionnelle `rechercher_web` utilise Tavily en mode automatique avec `TAVILY_API_KEY`. Elle partage le budget de deux recherches par passe (quatre maximum avec correction) avec la recherche documentaire. Les URL rejoignent les sources de synthèse et de vérification ; les tests couvrent les pannes, l’absence de clé, le budget partagé et le blocage en mode documents. Voir [ARCHITECTURE_AGENT.md](ARCHITECTURE_AGENT.md#recherche-internet-avec-tavily).

La collaboration utilise un sous-graphe LangGraph à quatre nœuds, avec retours conditionnels vers le chercheur ou le synthétiseur. Les échanges sont affichés dans le frontend via `evaluation.collaboration`. Le nouveau planificateur est `PlanningAgent` ; les classes historiques du dossier expérimental restent hors ligne.
