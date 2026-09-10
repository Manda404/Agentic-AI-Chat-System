# Fonctionnement pas à pas

Le parcours courant utilise Hugging Face et quatre agents : planification → recherche → synthèse → vérification, puis contrôles locaux. Le chercheur fournit preuves et brouillon ; le synthétiseur peut s’abstenir, et le vérificateur peut refuser la publication. Budget global avec une correction maximum : 13 appels LLM et 90 secondes par défaut. Voir [ARCHITECTURE_AGENT.md](ARCHITECTURE_AGENT.md).

Architecture courante du 10 septembre 2026 : quatre agents documentaires et trois outils de recherche/lecture.

1. Au démarrage, `ApplicationServices` construit les services de mémoire, recherche, embeddings, génération et authentification, puis compile le graphe à cinq étapes.
2. L'utilisateur s'authentifie et importe des fichiers PDF/CSV. Le backend extrait le texte, le découpe, ajoute la propriété/visibilité, génère les embeddings et écrit les fragments dans MongoDB. Les échecs vectoriels sont annoncés ; les PDF sans texte sont refusés.
3. À la réception d'une question, le backend charge l'historique existant avant d'enregistrer le message courant. L'historique est isolé par propriétaire ; il n'existe ni cache de réponse ni checkpoint conversationnel parallèle.
4. Le routeur respecte le mode : `documents` impose la recherche ; `general` autorise une réponse non documentaire ; `auto` privilégie les documents sauf salutation, calcul autonome, inventaire explicite ou transformation de texte fourni.
5. Pour une question documentaire, l’agent choisit ses actions sous budget. `rechercher` appelle le pipeline full-text/vectoriel, fusion RRF, reranking et compression. Une seconde recherche permet une reformulation. `lire_passage` relit un fragment déjà découvert, en revérifiant ses permissions.
6. L’agent reçoit les observations et extraits, puis décide de répondre avec des labels `[n]`, de demander une précision ou de s’abstenir. Il dispose au maximum de deux recherches, trois outils et quatre appels LLM par passe de recherche ; une seule correction est autorisée, pour treize appels LLM maximum au total. Une réponse documentaire sans extrait est bloquée. Les chemins de salutation, calcul et inventaire restent sans génération.
7. Les contrôles locaux vérifient le brouillon, les succès des outils et les citations. Une citation existante ne suffit pas à démontrer la vérité d'une affirmation ; la validation expose explicitement cette limite.
8. Le système publie la réponse validée ou un message d'abstention. Le filtre de secrets s'applique au texte final. La réponse et les traces sont retournées, puis l'historique contient le tour complet.

La boucle outil → observation → décision se trouve dans le nœud `documentary`. Une synthèse et une revue LLM indépendantes suivent la recherche. Le synthétiseur et le vérificateur peuvent demander une seule correction ciblée ; un échec du validateur local ne relance pas la génération. Les métriques `evaluation.documentary_agent`, `evaluation.latency_ms`, `evaluation.component_latency_ms`, `retrieval_metrics` et `evaluation.answer` permettent de localiser les problèmes.

Le statut distingue réponse, demande de précision et abstention. Le parcours déterministe précédent est conservé avec `strategy="baseline"` pour comparaison. Voir [ARCHITECTURE_AGENT.md](ARCHITECTURE_AGENT.md) pour les contrats et limites.

La recherche web optionnelle `rechercher_web` utilise Tavily en mode automatique avec `TAVILY_API_KEY`. Elle partage le budget de deux recherches par passe (quatre maximum avec correction) avec la recherche documentaire. Les URL rejoignent les sources de synthèse et de vérification ; les tests couvrent les pannes, l’absence de clé, le budget partagé et le blocage en mode documents. Voir [ARCHITECTURE_AGENT.md](ARCHITECTURE_AGENT.md#recherche-internet-avec-tavily).

La collaboration utilise un sous-graphe LangGraph à quatre nœuds, avec retours conditionnels vers le chercheur ou le synthétiseur. Les échanges sont affichés dans le frontend via `evaluation.collaboration`. Le nouveau planificateur est `PlanningAgent` ; les classes historiques du dossier expérimental restent hors ligne.
