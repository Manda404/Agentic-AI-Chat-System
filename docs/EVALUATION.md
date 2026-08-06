# Évaluation

Le mini framework d'évaluation est dans `backend/app/evaluation`.

## Fichiers

- `cases.py` : cas d'évaluation.
- `metrics.py` : métriques simples.
- `evaluator.py` : exécuteur branchable sur `ChatWorkflow`.

## Ce Qui Est Vérifié

- route attendue ;
- réponse non vide ;
- présence de sources quand nécessaire ;
- critic observé ;
- compatibilité `ChatResponse`.

## Tests

Les tests unitaires utilisent des fakes pour éviter les vrais appels LLM, Redis ou MongoDB Atlas.

Commande :

```bash
cd backend
python3 -m unittest discover -s tests
```

Dans un environnement sans dépendances backend installées, le fichier de test se marque skipped proprement.
