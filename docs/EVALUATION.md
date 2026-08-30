# Tests et évaluation

> Inventaire vérifié et commandes exécutées le **30 août 2026**.

## 1. État vérifié

```bash
make test
# Ran 32 tests ... OK

cd frontend
npm run build
# compilation, lint/type checking et génération statique : OK
```

Le build frontend n'est pas un test fonctionnel du navigateur. Il vérifie la
compilation Next.js et les types, pas les appels à l'API ni les interactions UI.

## 2. Tests backend isolés

La suite utilise `unittest` et `IsolatedAsyncioTestCase`.

| Fichier | Couverture réelle |
|---|---|
| `test_langgraph_workflow.py` | compilation, appels d'agents, greeting, chemins RAG/outils, citation validator, retry direct, critic/safety, rédaction de secret |
| `test_data_reset.py` | reset Redis global et owner-scoped en conservant les comptes, suppression MongoDB sans supprimer collection/index |
| `test_prompt_contracts.py` | inventaire des prompts, JSON structuré, résumé documentaire via RAG, contraintes compressor/reranker |
| `test_rag_prompt.py` | séparation question/documents/historique, grounding, citations, langue, calculs et injection indirecte |
| `test_tools.py` | calcul AST sûr, refus d'exécution de code, inventaire documentaire et validation structurelle + support lexical des citations |
| `test_retrieval_improvements.py` | fusion RRF, réutilisation embeddings, compression sélective, IDs stables, filtres owner, métadonnées d'ingestion |

Les tests du workflow utilisent des fakes pour le LLM, la mémoire et le search.
Ils ne contactent normalement ni Redis ni MongoDB et ne mesurent pas la qualité
des réponses d'un vrai modèle.

### Langfuse pendant les tests

Si le fichier `backend/.env` contient `LANGFUSE_ENABLED=true`, les décorateurs
sont activés dès l'import des modules. Même avec des fakes, une tentative
d'export de traces peut apparaître en fin de test. Pour une exécution isolée :

```bash
LANGFUSE_ENABLED=false make test
```

### Ce qui n'est pas couvert

- routes FastAPI avec un vrai client HTTP ;
- JWT expiré, `/auth/me` et restauration de session frontend ;
- cache hit et invalidation via API HTTP ;
- exécution complète d'un second appel LLM pendant les retries critic ;
- panne Redis après démarrage ;
- ingestion réelle PDF/CSV, limites upload/batch et erreurs de parsing ;
- CORS, rate limit Redis et headers ;
- composants/interactions frontend ;
- charge, concurrence et régression de performance async.

## 3. Évaluateur bout en bout du workflow

Fichiers :

- `backend/app/evaluation/cases.py` ;
- `backend/app/evaluation/metrics.py` ;
- `backend/app/evaluation/evaluator.py`.

`DEFAULT_EVALUATION_CASES` contient 6 scénarios : greeting, question
documentaire, hors corpus, résumé, correction et demande ambiguë.
`WorkflowEvaluator.run_cases()` appelle une vraie instance de `ChatWorkflow` et
évalue :

- égalité de route ;
- réponse non vide ;
- présence de sources lorsque demandée ;
- verdict critic attendu lorsque le cas le précise.

Il n'existe pas actuellement de CLI ou de cible Make dédiée à cet évaluateur.
Il faut l'instancier depuis un script ou un test.

### `critic_observed`

`score_response()` calcule :

```python
any(result.agent in {"critic", "critic_skipped"} for result in response.agent_results)
```

La métrique vérifie donc maintenant que le critic a été exécuté ou explicitement
sauté par politique, au lieu de s'appuyer seulement sur le booléen
`critic_passed`.

### Limites générales

- les routes produites par un vrai planner LLM peuvent varier ;
- les résultats dépendent des données et services externes ;
- aucune réponse de référence n'est comparée ;
- aucune mesure de factualité, style ou groundedness n'est calculée.

## 4. Benchmark de retrieval

Fichiers :

- `retrieval_cases.py` : 10 questions et titres pertinents ;
- `retrieval_metrics.py` : Precision@k, Recall@k, reciprocal rank et NDCG@k ;
- `retrieval_benchmark.py` : exécution des vrais services/agents.

Le benchmark mesure trois étages :

| Étage | Exécution |
|---|---|
| `full_text` | `SearchService.search()` |
| `hybrid` | + `HybridRetrieverAgent` et Atlas Vector Search |
| `reranked` | + `RerankerAgent` lexical/sémantique |

### Prérequis

1. `MONGODB_URI` valide ;
2. index Atlas Search et Vector Search créés ;
3. `HUGGINGFACE_API_KEY` valide pour la branche dense/sémantique ;
4. catalogue `backend/data/ai_tooling_catalog.csv` déjà ingéré via
   `/api/v1/ingest/sample-data` ;
5. idéalement, corpus de test propre pour éviter que des documents hors jeu
   d'évaluation influencent les scores.

La cible `/ingest/sample-data` exige un JWT. Le bouton `INGESTION DATA` du
frontend appelle plutôt `/ingest/batch`, qui ingère tout le dossier `data`.

### Commandes

Depuis la racine :

```bash
make eval-retrieval
```

Ou :

```bash
cd backend
.venv/bin/python -m app.evaluation.retrieval_benchmark
.venv/bin/python -m app.evaluation.retrieval_benchmark --verbose
.venv/bin/python -m app.evaluation.retrieval_benchmark --k 3
```

Le `k` par défaut vaut `MAX_RAG_DOCUMENTS`.

## 5. Interprétation des métriques

- **Precision@k** : proportion de documents pertinents dans les `k` places. Le
  dénominateur reste `k`, même si moins de résultats sont retournés.
- **Recall@k** : proportion de tous les documents pertinents retrouvés dans le
  top-k.
- **MRR** : moyenne de l'inverse du rang du premier document pertinent. `1.0`
  signifie qu'un document pertinent est toujours premier.
- **NDCG@k** : récompense les documents pertinents placés tôt et normalise par le
  classement idéal.

Le benchmark déduplique les titres avant le calcul, car `SearchService` peut
retourner plusieurs copies après réingestion. Cette déduplication par titre peut
elle-même masquer deux documents distincts ayant le même titre.

Sur le petit catalogue fourni, les questions sont proches des textes et les
scores peuvent saturer. Une égalité entre full-text, hybride et reranking ne
démontre pas que les étapes supplémentaires sont inutiles ; elle signifie que le
jeu est trop simple pour les distinguer.

## 6. Étendre le jeu de vérité terrain

Pour un corpus métier :

1. stabiliser des identifiants documentaires, plutôt que le titre seul ;
2. créer des requêtes naturelles, ambiguës, multilingues et avec synonymes ;
3. annoter tous les documents pertinents, pas seulement un résultat attendu ;
4. ajouter des cas sans résultat pertinent ;
5. séparer un jeu de calibration et un jeu de validation ;
6. mesurer par type de document, langue et longueur ;
7. comparer les distributions avant/après chaque changement de score.

Les cas actuels utilisent `relevant_titles`; modifier ce contrat serait utile
avant un corpus où les titres ne sont pas uniques.

## 7. Évaluation de génération à ajouter

Le benchmark retrieval ne dit pas si la réponse finale est correcte. Une suite
complète devrait mesurer :

- exactitude par rapport à une réponse de référence ;
- couverture des éléments attendus ;
- groundedness de chaque affirmation ;
- validité et précision des citations `[n]` ;
- taux de refus correct lorsque le corpus ne répond pas ;
- langue et respect du format demandé ;
- fuite de secrets et résistance aux instructions dans les documents ;
- latence p50/p95, appels HF, tokens et coût ;
- taux de fallback planner/critic/RAG ;
- stabilité du résultat sur plusieurs exécutions.

## 8. Tests frontend et intégration à ajouter

Priorités recommandées :

1. test du démarrage avec backend inaccessible et message utilisateur clair ;
2. register → login automatique → restauration via `/auth/me` ;
3. expiration JWT et logout ;
4. upload PDF/CSV, rejet d'extension et reset confirmé/annulé ;
5. envoi `Cmd/Ctrl+Enter`, état loading et rendu des citations ;
6. cockpit alimenté par un `ChatResponse` complet ;
7. statuts health distinguant configuration et disponibilité LLM ;
8. test API de cache miss/hit et invalidation après ingestion/reset.

## 9. Critère minimal avant fusion d'un changement RAG

```text
1. make test passe
2. npm run build passe
3. benchmark retrieval exécuté sur un corpus propre
4. métriques avant/après conservées dans la PR
5. aucun recul inexpliqué de Recall@k, MRR ou NDCG@k
6. cas de fallback et absence de documents vérifiés
7. documentation RAG et configuration mises à jour
```
