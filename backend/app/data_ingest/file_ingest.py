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
from app.config.settings import settings

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
    recursive: bool = False,
    errors: list[str] | None = None,
) -> Dict[str, List[Dict[str, str]]]:
    """
    Parcourt un dossier et charge tous les PDF/CSV trouvés.

    Avec une liste `errors`, les erreurs de parsing y sont collectées ;
    sans collecteur, la première erreur interrompt le chargement
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

    allowed = {f".{kind.lower()}" for kind in file_types}
    if not allowed <= {".pdf", ".csv"}:
        raise ValueError("Supported file types: pdf, csv.")
    candidates = []
    paths = dir_path.rglob("*") if recursive else dir_path.glob("*")
    for path in paths:
        if not path.is_file() or path.suffix.lower() not in allowed:
            continue
        if dir_path.resolve() not in path.resolve().parents:
            raise ValueError("Batch files must remain inside the requested directory (symlink rejected).")
        if path.stat().st_size > settings.max_upload_bytes:
            raise ValueError(f"File exceeds MAX_UPLOAD_BYTES: {path.name}")
        candidates.append(path)
        if len(candidates) > settings.max_batch_files:
            raise ValueError("Batch exceeds MAX_BATCH_FILES.")
    for file_path in sorted(candidates):
        try:
            documents = load_documents_from_file(str(file_path))
            results[str(file_path)] = documents
        except Exception as exc:
            message = f"Failed to parse {file_path.name}: {exc}"
            if errors is None:
                raise ValueError(message) from exc
            errors.append(message)

    total_docs = sum(len(docs) for docs in results.values())
    logger.info(f"Loaded {total_docs} total documents from {len(results)} files in {directory_path}")

    return results


def get_supported_file_types() -> List[str]:
    """Liste des extensions actuellement supportées par l'ingestion."""
    return [".pdf", ".csv"]