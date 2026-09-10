# Évaluer le projet

Le parcours courant utilise Hugging Face et quatre agents : planification → recherche → synthèse → vérification, puis contrôles locaux. Le chercheur fournit preuves et brouillon ; le synthétiseur peut s’abstenir, et le vérificateur peut refuser la publication. Budget global avec une correction maximum : 13 appels LLM et 90 secondes par défaut. Voir [ARCHITECTURE_AGENT.md](ARCHITECTURE_AGENT.md).

État du 10 septembre 2026, après simplification. Séparer trois questions : le code fonctionne-t-il, les bons documents remontent-ils, les réponses sont-elles justes ?

## 1. Tests de contrats sans fournisseurs

```sh
make test
```

La suite vérifie ingestion, isolation, indexation, calcul, sélection des sources, citations et parcours LangGraph. Les tests du graphe utilisent des doubles de MongoDB/Redis/LLM : ils vérifient la baseline avec au plus une génération, l’agent avec ses limites de quatre recherches/six outils/treize appels LLM pour l’équipe avec une correction maximum, ses permissions, ses timeouts, son contrat JSON, la clarification, les chemins sans LLM, l'historique, les pannes, le choix de fournisseur et l'abstention. Ils ne mesurent pas la qualité réelle d'un modèle.

Pour garantir un lancement local sans observabilité distante :

```sh
cd backend
APP_ENV=test LANGFUSE_ENABLED=false LANGFUSE_TRACING_ENABLED=false HUGGINGFACE_API_KEY='' MONGODB_URI='' .venv/bin/python -m unittest discover -s tests
```

## 2. Diagnostic et retrieval réel

```sh
cd backend
.venv/bin/python -m app.evaluation.index_health
.venv/bin/python -m app.evaluation.retrieval_benchmark --verbose --k 5
```

Le diagnostic est en lecture seule ; il vérifie index présents/queryable, dimension déclarée et champs de préfiltre, compte des documents vectorisés et provenance du modèle.

Le benchmark complet utilise Atlas et HuggingFace. Le CSV de référence doit être ingéré au préalable et les index prêts. En mode propriétaire, préciser `--owner-id <propriétaire-du-corpus>`. L'outil mesure Precision@k, Recall@k, MRR et NDCG@k sur full-text, hybride et reranking avec le même câblage que le chat. Il échoue explicitement si un étage vectoriel requis est indisponible.

Les doublons conservent leur place mais ne gagnent pas deux fois de pertinence. Precision@k divise toujours par k. Les dix cas du catalogue utilisent des titres comme référence : pour un vrai corpus de fragments, passer à des IDs/page/passage annotés. Ces scores ne mesurent ni compression ni génération.

## 3. Réponse et abstention

`WorkflowEvaluator` reçoit une instance de `ChatWorkflow`. Chaque `EvaluationCase` définit route, mode (`auto/documents/general`), sources attendues et `expected_status` (`answered`, `clarification_requested` ou `abstained`). Un cas sans réponse doit récompenser une abstention correcte ; il ne doit pas exiger artificiellement `critic_passed=true`.

Les résultats incluent la réponse pour permettre sa relecture. Les contrôles portent sur route, non-vide, état attendu, citations, contrôles locaux et succès de génération. Un texte non vide n'est pas une preuve de réponse correcte.

Le champ `critic_score` vaut `null` et `factuality_evaluated=false` dans le parcours courant. Un agent de vérification intervient en ligne ; son avis ne constitue pas une mesure indépendante de factualité. Les composants de planification, CRAG et critique sont conservés dans `evaluation/experimental/` pour des expériences séparées ; ils n'exposent pas à eux seuls une mesure de qualité validée.

## Protocole de comparaison

Créer un corpus versionné de questions françaises/anglaises avec réponses, pages et citations attendues, cas sans preuve et cas de droits d'accès. Réserver un jeu non utilisé pour le réglage. Mesurer :

- exactitude des réponses et adéquation des citations, par annotation indépendante ;
- abstentions correctes et abusives ;
- Recall@k et qualité du classement ;
- latence p50/p95, appels fournisseurs et coût ;
- résultats séparés sur PDF, tableaux, paraphrases et questions conversationnelles.

Comparer l’agent courant au parcours simple conservé :

```sh
cd backend
.venv/bin/python -m app.evaluation.compare_workflows --cases cases.json --owner-id <propriétaire-du-corpus>
```

Le fichier JSON contient une liste d’objets `EvaluationCase`. Sans `--cases`, les cas fonctionnels du catalogue sont utilisés. Le comparateur alterne l’ordre des stratégies et conserve réponses, statuts, latences et compteurs. L’historique reste en mémoire, sans écriture dans Redis. L’exécution réelle utilise Atlas et les fournisseurs configurés ; elle peut transmettre questions et passages au fournisseur de génération ou d’embeddings.

`contracts_passed` mesure les contrats logiciels, pas la factualité. Les compteurs LLM/outils ne sont pas un coût monétaire. Les résultats doivent être annotés indépendamment pour établir un gain métier. Le comparateur et les budgets ont été testés localement avec des doubles ; aucune amélioration de qualité auprès d’un fournisseur réel n’est affirmée.

Introduire ensuite une variation à la fois : reranking, paramètres de recherche ou budget. Les chiffres de l’audit initial ne sont pas une validation sémantique de cette architecture. Voir [ARCHITECTURE_AGENT.md](ARCHITECTURE_AGENT.md).

La recherche web optionnelle `rechercher_web` utilise Tavily en mode automatique avec `TAVILY_API_KEY`. Elle partage le budget de deux recherches par passe (quatre maximum avec correction) avec la recherche documentaire. Les URL rejoignent les sources de synthèse et de vérification ; les tests couvrent les pannes, l’absence de clé, le budget partagé et le blocage en mode documents. Voir [ARCHITECTURE_AGENT.md](ARCHITECTURE_AGENT.md#recherche-internet-avec-tavily).

La collaboration utilise un sous-graphe LangGraph à quatre nœuds, avec retours conditionnels vers le chercheur ou le synthétiseur. Les échanges sont affichés dans le frontend via `evaluation.collaboration`. Le nouveau planificateur est `PlanningAgent` ; les classes historiques du dossier expérimental restent hors ligne.
