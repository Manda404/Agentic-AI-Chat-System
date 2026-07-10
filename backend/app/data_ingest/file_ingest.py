"""
Point d'entrée générique de l'ingestion de fichiers : détecte le type
de fichier (PDF/CSV) et délègue au parseur spécialisé approprié
(`pdf_ingest.py` ou `csv_ingest.py`). Utilisé par les trois routes
d'ingestion (`sample-data`, `upload`, `batch`) dans `ingest_router.py`.
"""

from pathlib import Path
from typing import Dict, List, Literal

from app.data_ingest.csv_ingest import load_documents_from_csv
from app.data_ingest.pdf_ingest import load_documents_from_pdf
from app.logger import logger

FileType = Literal["pdf", "csv"]


def detect_file_type(file_path: str) -> FileType:
    """Déduit le type de fichier ("pdf"/"csv") depuis son extension, ou lève `ValueError`."""
    suffix = Path(file_path).suffix.lower()

    if suffix == ".pdf":
        return "pdf"
    elif suffix == ".csv":
        return "csv"
    else:
        raise ValueError(f"Unsupported file type: {suffix}. Supported types: .pdf, .csv")


def load_documents_from_file(file_path: str, file_type: FileType | None = None) -> List[Dict[str, str]]:
    """Charge un fichier unique (PDF ou CSV) et le transforme en documents indexables."""
    file_path_obj = Path(file_path)

    if not file_path_obj.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    if file_type is None:
        file_type = detect_file_type(file_path)

    logger.info(f"Loading documents from {file_type.upper()} file: {file_path}")

    if file_type == "pdf":
        return load_documents_from_pdf(file_path)
    elif file_type == "csv":
        return load_documents_from_csv(file_path)
    else:
        raise ValueError(f"Unsupported file type: {file_type}")


def load_documents_from_directory(
    directory_path: str,
    file_types: List[FileType] | None = None,
    recursive: bool = False
) -> Dict[str, List[Dict[str, str]]]:
    """
    Parcourt un dossier et charge tous les PDF/CSV trouvés.

    Un fichier en erreur n'interrompt pas les autres : l'erreur est
    loguée et le fichier est simplement absent du résultat retourné
    (voir `ingest_router.py::ingest_batch_from_directory` pour le résumé
    par fichier renvoyé à l'appelant).
    """
    dir_path = Path(directory_path)

    if not dir_path.exists():
        raise FileNotFoundError(f"Directory not found: {directory_path}")

    if not dir_path.is_dir():
        raise ValueError(f"Path is not a directory: {directory_path}")

    if file_types is None:
        file_types = ["pdf", "csv"]

    results: Dict[str, List[Dict[str, str]]] = {}

    patterns = []
    if "pdf" in file_types:
        patterns.append("*.pdf")
    if "csv" in file_types:
        patterns.append("*.csv")

    for pattern in patterns:
        if recursive:
            files = dir_path.rglob(pattern)
        else:
            files = dir_path.glob(pattern)

        for file_path in files:
            try:
                logger.info(f"Processing file: {file_path}")
                documents = load_documents_from_file(str(file_path))
                results[str(file_path)] = documents
                logger.info(f"Successfully loaded {len(documents)} documents from {file_path.name}")
            except Exception as e:
                logger.error(f"Error processing file {file_path}: {str(e)}")
                continue

    total_docs = sum(len(docs) for docs in results.values())
    logger.info(f"Loaded {total_docs} total documents from {len(results)} files in {directory_path}")

    return results


def get_supported_file_types() -> List[str]:
    """Liste des extensions actuellement supportées par l'ingestion."""
    return [".pdf", ".csv"]