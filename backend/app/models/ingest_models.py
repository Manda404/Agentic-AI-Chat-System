"""Pydantic schemas for document ingestion."""

from typing import List, Optional

from pydantic import BaseModel, Field

class EmbeddingSummary(BaseModel):
    embedded_count: int = 0
    warnings: List[str] = Field(default_factory=list)


class IngestResponse(EmbeddingSummary):
    """Response from POST /ingest/sample-data."""
    indexed_count: int
    index_name: str
    source_file: str

class FileIngestResponse(EmbeddingSummary):
    """Response from POST /ingest/upload for a single file."""
    indexed_count: int
    index_name: str
    file_name: str
    file_type: str
    documents_processed: int
    stored_path: str

class BatchIngestResponse(BaseModel):
    """Response from POST /ingest/batch with per-file success or failure."""
    total_files_processed: int
    total_documents_indexed: int
    index_name: str
    files_summary: List[dict] = Field(default_factory=list)
    errors: Optional[List[str]] = Field(default_factory=list)

class DataResetResponse(BaseModel):
    """Application-data reset result, excluding user accounts."""
    mongodb_documents_deleted: int
    redis_runtime_entries_deleted: int
    user_accounts_preserved: bool = True

class IngestRequest(BaseModel):
    """Request body for POST /ingest/batch."""
    directory_path: str = Field(default="data", description="Directory path to ingest files from")
    file_types: Optional[List[str]] = Field(default=None, description="File types to process (pdf, csv)")
    recursive: bool = Field(default=False, description="Whether to search subdirectories recursively")
