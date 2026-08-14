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

Le framework exécute le vrai `ChatWorkflow` (donc de vrais appels LLM/Redis/MongoDB si branchés) — ce n'est pas un jeu de tests unitaires isolé, mais un outil de vérification de bout en bout à lancer manuellement. Il n'y a pas encore de jeu de données de référence ni de métriques de groundedness/hallucination.

## Tests unitaires (isolés, avec fakes)

Les tests de `backend/tests/test_langgraph_workflow.py` utilisent des fakes (`FakeSearchService`, `FakeLLMService`, ...) pour éviter les vrais appels LLM, Redis ou MongoDB Atlas. Ils couvrent la compilation du graphe, les routes principales (greeting, RAG, safety redaction) et les champs debug.

Commande :

```bash
cd backend
python3 -m unittest discover -s tests
```

Dans un environnement sans dépendances backend installées (`langgraph`, `loguru`), le fichier de test se marque `skipped` proprement (`unittest.SkipTest`) plutôt que d'échouer.
