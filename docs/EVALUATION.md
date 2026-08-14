# Évaluation

Mini framework d'évaluation, sans dépendance externe, dans [`backend/app/evaluation/`](../backend/app/evaluation/). Vue d'ensemble du reste du projet : [GUIDE_PROJET.md](GUIDE_PROJET.md).

## Fichiers

- `cases.py` : `DEFAULT_EVALUATION_CASES`, 6 cas couvrant greeting, question documentaire, question hors périmètre, résumé, correction, demande ambiguë.
- `metrics.py` : `score_response()` vérifie route attendue, réponse non vide, présence de sources (`"Sources:"` dans la réponse ou `sources_used`/`documents` dans les métadonnées d'un agent) et observation du critic.
- `evaluator.py` : `WorkflowEvaluator.run_cases()`, exécuteur branchable directement sur une instance de `ChatWorkflow` — appelle `workflow.run()` pour chaque cas et agrège les métriques.

## Ce Qui Est Vérifié

- route attendue (`expected_route`) ;
- réponse non vide ;
- présence de sources quand `expect_sources=True` ;
- `critic_passed` observé, et comparé à `expect_critic_passed` si le cas le précise ;
- compatibilité `ChatResponse`.

## Limite actuelle

Le framework exécute le vrai `ChatWorkflow` (donc de vrais appels LLM/Redis/MongoDB si branchés) — ce n'est pas un jeu de tests unitaires isolé, mais un outil de vérification de bout en bout à lancer manuellement. Il vérifie le *comportement* (route, présence de réponse, critic observé), pas la *qualité du retrieval* — pour ça, voir la section suivante.

## Benchmark de qualité du retrieval (Precision / Recall / MRR / NDCG)

Le module `evaluator.py` ci-dessus ne dit pas si les **bons documents** remontent, ni dans le **bon ordre** — seulement si une réponse a été produite. `backend/app/evaluation/retrieval_benchmark.py` comble ce manque avec des métriques standard de recherche d'information (IR) mesurées à trois étages du pipeline :

- `full_text` : `SearchAgent` seul (MongoDB Atlas Search, mots-clés) ;
- `hybrid` : + `HybridRetrieverAgent` (fusion avec la recherche vectorielle) ;
- `reranked` : + `RerankerAgent` (score lexical + sémantique, troncature finale — ce qui atteint réellement le LLM).

### Fichiers

- `retrieval_cases.py` : le jeu de référence (`GOLD_RETRIEVAL_CASES`) — 10 questions associées aux titres de documents attendus, construites sur le CSV d'exemple du projet (`backend/data/ai_tooling_catalog.csv`). Deux cas ont plusieurs documents pertinents ou un piège proche en sens (ex: modèle local vs modèle hébergé), pour éviter un jeu de test trop facile.
- `retrieval_metrics.py` : `precision_at_k`, `recall_at_k`, `reciprocal_rank` (→ MRR une fois moyenné), `ndcg_at_k`. Pertinence binaire, sans dépendance externe.
- `retrieval_benchmark.py` : instancie les **vrais** agents de production (`HybridRetrieverAgent`, `RerankerAgent`), câblés exactement comme `ChatWorkflow.__init__`, et les exécute contre MongoDB Atlas pour chaque cas.

### Pourquoi ce n'est pas un test avec des fakes

Un benchmark de qualité du retrieval contre des données simulées ne mesurerait rien de réel — c'est justement le comportement du *vrai* index Atlas Search, du *vrai* index Atlas Vector Search et du *vrai* reranking qui est en jeu. Prérequis avant de lancer :

1. `MONGODB_URI` valide dans `.env` ;
2. le jeu de données d'exemple déjà ingéré : `POST /ingest/sample-data` (ou tes propres documents + tes propres cas ajoutés dans `retrieval_cases.py`).

### Lancer le benchmark

```bash
cd backend
.venv/bin/python -m app.evaluation.retrieval_benchmark            # résumé agrégé par étage
.venv/bin/python -m app.evaluation.retrieval_benchmark --verbose  # + détail par cas (quel titre à quel rang)
.venv/bin/python -m app.evaluation.retrieval_benchmark --k 3      # profondeur d'évaluation différente
```

### Comment lire les résultats

- **Recall@k** et **MRR** sont les métriques les plus parlantes ici : est-ce que le bon document est *quelque part* dans le top-k (recall), et à *quel rang* en moyenne (MRR, 1.0 = toujours en premier) ?
- **Precision@k** est mécaniquement basse sur un petit corpus avec peu de documents pertinents par question (diviseur fixé à `k`, convention IR standard) — normal, pas un signe de mauvaise qualité en soi.
- Comparer les 3 lignes du tableau répond à une question concrète : est-ce que chaque étage **améliore** vraiment le classement ? Sur le corpus d'exemple (10 documents, peu ambigu), les 3 étages atteignent déjà Recall@5=1.00 / MRR=1.00 — le corpus est trop petit/simple pour différencier full-text, hybride et reranking. La valeur du benchmark se révèle sur un corpus plus grand et plus ambigu (le tien) : c'est là que l'hybride et le reranking sémantique doivent démontrer un vrai gain sur le full-text seul.
- C'est aussi l'outil à utiliser pour calibrer `SEMANTIC_WEIGHT` (`reranker_agent.py`) sur des données réelles plutôt qu'à l'aveugle — voir [RAG_SYSTEM.md](RAG_SYSTEM.md), erreur #6.

### Étendre à tes propres documents

Ingère tes documents, puis ajoute des `RetrievalGoldCase(name=..., query=..., relevant_titles=frozenset({...}))` dans `retrieval_cases.py` avec les titres réellement pertinents pour chaque question — le reste du script fonctionne sans modification.

## Tests unitaires (isolés, avec fakes)

Les tests de `backend/tests/test_langgraph_workflow.py` utilisent des fakes (`FakeSearchService`, `FakeLLMService`, ...) pour éviter les vrais appels LLM, Redis ou MongoDB Atlas. Ils couvrent la compilation du graphe, les routes principales (greeting, RAG, safety redaction) et les champs debug.

Commande :

```bash
cd backend
python3 -m unittest discover -s tests
```

Dans un environnement sans dépendances backend installées (`langgraph`, `loguru`), le fichier de test se marque `skipped` proprement (`unittest.SkipTest`) plutôt que d'échouer.
