"""
Schémas Pydantic pour l'ingestion de documents (`ingest_router.py`).
"""

from typing import List, Optional

from pydantic import BaseModel, Field

class IngestResponse(BaseModel):
    """Réponse de `POST /ingest/sample-data`."""
    indexed_count: int
    index_name: str
    source_file: str

class FileIngestResponse(BaseModel):
    """Réponse de `POST /ingest/upload` (un seul fichier)."""
    indexed_count: int
    index_name: str
    file_name: str
    file_type: str
    documents_processed: int
    stored_path: str

class BatchIngestResponse(BaseModel):
    """Réponse de `POST /ingest/batch`, avec un résumé succès/échec par fichier traité."""
    total_files_processed: int
    total_documents_indexed: int
    index_name: str
    files_summary: List[dict] = Field(default_factory=list)
    errors: Optional[List[str]] = Field(default_factory=list)

class DataResetResponse(BaseModel):
    """Résultat du reset des données applicatives, comptes utilisateurs exclus."""
    mongodb_documents_deleted: int
    redis_runtime_entries_deleted: int
    user_accounts_preserved: bool = True

class IngestRequest(BaseModel):
    """Corps attendu par `POST /ingest/batch`."""
    directory_path: str = Field(default="data", description="Directory path to ingest files from")
    file_types: Optional[List[str]] = Field(default=None, description="File types to process (pdf, csv)")
    recursive: bool = Field(default=False, description="Whether to search subdirectories recursively")
