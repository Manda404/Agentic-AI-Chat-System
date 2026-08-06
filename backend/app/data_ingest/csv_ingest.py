"""
Lecture de fichiers CSV pour l'indexation MongoDB Atlas.

Le CSV doit avoir les colonnes `title`, `snippet`, `category` (obligatoires)
et `source` (optionnelle). Chaque ligne devient un document indexable.
Voir `backend/data/ai_tooling_catalog.csv` pour un exemple concret.
"""

import csv
from typing import Dict, List

from app.logger import logger


def load_documents_from_csv(file_path: str) -> List[Dict[str, str]]:
    """Lit un CSV ligne par ligne et retourne une liste de documents (title/snippet/category/source)."""
    documents: List[Dict[str, str]] = []
    with open(file_path, newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            documents.append(
                {
                    "title": row["title"],
                    "snippet": row["snippet"],
                    "category": row["category"],
                    "source": row.get("source", "csv-ingest"),
                }
            )
    logger.bind(file_path=file_path, document_count=len(documents)).info(
        "CSV file parsed into documents."
    )
    return documents


