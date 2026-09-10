# Pipeline documentaire courant

Le parcours courant utilise Hugging Face et quatre agents : planification → recherche → synthèse → vérification, puis contrôles locaux. Le chercheur fournit preuves et brouillon ; le synthétiseur peut s’abstenir, et le vérificateur peut refuser la publication. Budget global avec une correction maximum : 13 appels LLM et 90 secondes par défaut. Voir [ARCHITECTURE_AGENT.md](ARCHITECTURE_AGENT.md).

État du 10 septembre 2026, après simplification. Voir [ARCHITECTURE_AGENT.md](ARCHITECTURE_AGENT.md) pour les décisions du graphe.

## Ingestion

Les routes `sample-data`, `upload` et `batch` partagent la normalisation et la préparation des documents. Les PDF sont extraits par page ; les CSV doivent contenir `title`, `snippet` et `category`, avec `source` optionnel. Le texte long est découpé avec recouvrement sans supprimer sa fin. Les fragments portent propriétaire, visibilité, page, nom logique, ID stable et, si la vectorisation réussit, embedding et modèle d'embedding.

Les embeddings sont demandés par lots de 32 et vérifiés : nombre, dimension, valeurs numériques finies et vecteur non nul. Une défaillance laisse un mode textuel dégradé annoncé via `warnings` et `embedded_count`. Une ingestion réussie signifie écriture MongoDB, pas synchronisation immédiate des index Atlas.

Les écritures utilisent un upsert sans doubler `matched_count` et `modified_count`. Une réingestion identique peut conserver un vecteur existant si le fournisseur échoue ; `embedded_count` décrit les vecteurs préparés pour cette requête, pas un recomptage de la base. Le diagnostic d'index sert à vérifier les données persistées.

Le cache de réponses n'existe plus : les routes d'ingestion ne dépendent plus de Redis pour incrémenter une version de cache. Redis reste utilisé par l'authentification et par le reset de l'historique.

## Retrieval commun au chat et au benchmark

`services/retrieval_pipeline.py` assemble quatre composants :

1. **Full-text** : Atlas Search sur titre, snippet et catégorie ; cinq résultats au maximum, droits appliqués.
2. **Hybride** : recherche vectorielle avec préfiltre propriétaire/partagé, fusion RRF et huit résultats au maximum. Un document a au plus un vote par branche. `vector_error` distingue une panne d'une absence de hits.
3. **Reranking** : classement lexical, éventuellement complété par une similarité cosinus si `SEMANTIC_RERANKER_ENABLED=true`. Les embeddings stockés sont réutilisés ; les dimensions incompatibles déclenchent le repli lexical. La sélection finale est bornée par `MAX_RAG_DOCUMENTS`.
4. **Compression** : sélection extractive locale sous `MAX_RAG_CONTEXT_CHARS`. Les labels conservés déterminent la liste documentaire réellement utilisée par le générateur et le validateur.

Il n'y a pas de grader CRAG en ligne. Aucun de ces quatre composants ne génère de réponse via un LLM ; les embeddings restent des appels réseau distincts.

## Génération et validation

L’agent reçoit la question, l’historique, les observations et les passages sélectionnés. Il choisit entre recherche, lecture d’un fragment découvert, réponse, précision et abstention. Le code limite le parcours à quatre recherches, six outils et treize appels LLM au total, correction comprise. Le timeout est de 90 secondes par défaut. Le workflow de référence `baseline` conserve au plus une génération. Les labels `[n]` sont contrôlés avant publication. Les outils de calcul et d'inventaire sont locaux/déterministes et ne passent pas par le générateur.

Le contrôle des citations vérifie présence et plage, avec un signal lexical optionnel contrôlé par `CITATION_SUPPORT_REQUIRED`. Il ne prouve pas l'implication sémantique. Le validateur de contrat n'attribue aucun score de vérité. Un échec produit une abstention, sans régénération automatique.

## Index et migration

```sh
cd backend
.venv/bin/python -m app.evaluation.index_health
.venv/bin/python -m app.evaluation.index_health --vector-definition
```

Le vector index doit avoir `embedding` avec la bonne dimension et les champs `owner_id`/`visibility` de type `filter` pour le mode propriétaire. Documents et requêtes doivent utiliser le même modèle. Voir le [stage MongoDB Vector Search](https://www.mongodb.com/docs/vector-search/query/aggregation-stages/vector-search-stage/).

La simplification du graphe ne modifie pas les IDs ni le stockage. La migration des anciens IDs introduite par l'audit initial reste distincte : relire [AUDIT_2026-09-10.md](AUDIT_2026-09-10.md) avant toute réingestion du corpus existant.

## Limites actuelles

Pas d'OCR ni de reconstruction robuste de tableaux PDF. Le découpage est en caractères, pas en tokens. Le modèle d'embedding par défaut et certaines heuristiques lexicales sont orientés anglais. L’agent peut utiliser l’historique pour reformuler une recherche, mais la qualité de cette résolution conversationnelle reste à évaluer. Les seuils et limites de candidats doivent être calibrés sur un corpus métier. Les changements de versions de fichiers ne retirent pas automatiquement leurs anciens fragments.

Le reranking sémantique et les composants expérimentaux doivent être évalués par comparaison au même parcours textuel/hybride de référence ; leur présence ne garantit pas un gain de qualité.

La recherche web optionnelle `rechercher_web` utilise Tavily en mode automatique avec `TAVILY_API_KEY`. Elle partage le budget de deux recherches par passe (quatre maximum avec correction) avec la recherche documentaire. Les URL rejoignent les sources de synthèse et de vérification ; les tests couvrent les pannes, l’absence de clé, le budget partagé et le blocage en mode documents. Voir [ARCHITECTURE_AGENT.md](ARCHITECTURE_AGENT.md#recherche-internet-avec-tavily).

La collaboration utilise un sous-graphe LangGraph à quatre nœuds, avec retours conditionnels vers le chercheur ou le synthétiseur. Les échanges sont affichés dans le frontend via `evaluation.collaboration`. Le nouveau planificateur est `PlanningAgent` ; les classes historiques du dossier expérimental restent hors ligne.
