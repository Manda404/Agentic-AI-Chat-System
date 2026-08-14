"""
Routes d'ingestion de documents dans MongoDB Atlas.

Trois façons d'indexer des documents :
- `POST /ingest/sample-data` : indexe le CSV d'exemple fourni avec le projet.
- `POST /ingest/upload` : upload d'un fichier unique (PDF ou CSV) depuis le frontend.
- `POST /ingest/batch` : parcourt un dossier serveur et indexe tous les PDF/CSV trouvés.

Chaque document reçoit aussi un embedding (calculé via `HuggingFaceEmbeddingService`,
le même service que celui utilisé pour le reranking sémantique) avant d'être inséré,
afin d'alimenter à la fois l'index Atlas Search (full-text) et l'index Atlas Vector
Search (sémantique) sur la même collection.

Toutes ces routes nécessitent un utilisateur authentifié.
"""

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
import asyncio
import shutil
from pathlib import Path
from typing import Dict, List
from uuid import uuid4
from app.config.settings import settings
from app.data_ingest.file_ingest import (
    detect_file_type,
    load_documents_from_directory,
    load_documents_from_file,
    load_documents_from_csv
)
from app.dependencies.auth_dependencies import get_current_user
from app.dependencies.services import get_embedding_service, get_memory_service, get_search_service
from app.logger import logger
from app.memory.redis_memory import RedisMemoryService
from app.models.auth_models import UserResponse
from app.models.ingest_models import (
    BatchIngestResponse,
    DataResetResponse,
    FileIngestResponse,
    IngestRequest,
    IngestResponse,
)
from app.services.embedding_service import HuggingFaceEmbeddingService
from app.services.search_service import SearchService

router = APIRouter(prefix=settings.api_prefix, tags=["ingest"])

BACKEND_ROOT = Path(__file__).resolve().parents[2]
UPLOAD_DIRECTORY = BACKEND_ROOT / "data"


def _available_upload_path(filename: str) -> Path:
    """Construit un chemin sûr sans écraser un document déjà enregistré."""
    safe_name = Path(filename).name
    destination = UPLOAD_DIRECTORY / safe_name
    if destination.exists():
        destination = UPLOAD_DIRECTORY / f"{destination.stem}-{uuid4().hex[:8]}{destination.suffix}"
    return destination


def _persist_upload(source, destination: Path) -> None:
    """Copie le fichier temporaire de Starlette vers le stockage local permanent."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    source.seek(0)
    with destination.open("wb") as target:
        shutil.copyfileobj(source, target)


async def _attach_embeddings(
    documents: List[Dict[str, str]],
    embedding_service: HuggingFaceEmbeddingService,
) -> List[Dict[str, str]]:
    """
    Calcule un embedding par document (title + snippet) pour la recherche vectorielle.

    Non bloquant : si le fournisseur d'embeddings échoue (quota, modèle
    indisponible, timeout), l'ingestion continue sans le champ `embedding`.
    Ces documents restent cherchables en full-text (Atlas Search), ils
    seront simplement absents des résultats de recherche vectorielle
    jusqu'à ré-ingestion avec un fournisseur d'embeddings disponible.
    """
    if not documents:
        return documents
    texts = [f"{document.get('title', '')}. {document.get('snippet', '')}" for document in documents]
    try:
        embeddings = await embedding_service.embed_texts(texts)
    except Exception as exc:
        logger.bind(reason=str(exc), document_count=len(documents)).warning(
            "Embedding computation failed; indexing documents without vectors."
        )
        return documents
    for document, embedding in zip(documents, embeddings):
        document["embedding"] = embedding
    return documents


@router.delete("/data/reset", response_model=DataResetResponse)
async def reset_application_data(
    current_user: UserResponse = Depends(get_current_user),
    search_service: SearchService = Depends(get_search_service),
    memory_service: RedisMemoryService = Depends(get_memory_service),
) -> DataResetResponse:
    """Vide la base documentaire et les données Redis temporaires, en conservant les comptes."""
    logger.bind(user_id=current_user.email).warning("Application data reset requested.")
    try:
        mongodb_deleted = await search_service.clear_documents()
        redis_deleted = await memory_service.clear_runtime_data()
        logger.bind(
            user_id=current_user.email,
            mongodb_documents_deleted=mongodb_deleted,
            redis_runtime_entries_deleted=redis_deleted,
        ).warning("Application data reset completed; user accounts preserved.")
        return DataResetResponse(
            mongodb_documents_deleted=mongodb_deleted,
            redis_runtime_entries_deleted=redis_deleted,
        )
    except Exception as exc:
        logger.bind(user_id=current_user.email).exception("Application data reset failed.")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/ingest/sample-data", response_model=IngestResponse)
async def ingest_sample_data(
    current_user: UserResponse = Depends(get_current_user),
    search_service: SearchService = Depends(get_search_service),
    embedding_service: HuggingFaceEmbeddingService = Depends(get_embedding_service),
) -> IngestResponse:
    """Charge et indexe le CSV d'exemple `backend/data/ai_tooling_catalog.csv`."""
    logger.bind(user_id=current_user.email).info("Sample ingest requested.")
    try:
        documents = load_documents_from_csv("data/ai_tooling_catalog.csv")
        logger.bind(user_id=current_user.email, document_count=len(documents)).info(
            "CSV documents loaded for ingest."
        )
        documents = await _attach_embeddings(documents, embedding_service)
        indexed_count = await search_service.bulk_index_documents(documents)
        logger.bind(user_id=current_user.email, indexed_count=indexed_count).info(
            "Sample ingest completed."
        )
        return IngestResponse(
            indexed_count=indexed_count,
            index_name=settings.mongodb_collection,
            source_file="data/ai_tooling_catalog.csv",
        )
    except Exception as exc:
        logger.bind(user_id=current_user.email).exception("Sample ingest failed.")
        raise HTTPException(status_code=500, detail=str(exc)) from exc



@router.post("/ingest/upload", response_model=FileIngestResponse)
async def ingest_uploaded_file(
    file: UploadFile = File(...),
    current_user: UserResponse = Depends(get_current_user),
    search_service: SearchService = Depends(get_search_service),
    embedding_service: HuggingFaceEmbeddingService = Depends(get_embedding_service),
) -> FileIngestResponse:
    """Enregistre durablement un PDF/CSV directement dans `data`, puis l'indexe."""
    logger.bind(user_id=current_user.email).info(f"File upload ingest requested: {file.filename}")

    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    try:
        file_type = detect_file_type(file.filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    destination = _available_upload_path(file.filename)
    try:
        await asyncio.to_thread(_persist_upload, file.file, destination)

        logger.bind(user_id=current_user.email).info(
            f"Uploaded file saved: {destination.relative_to(BACKEND_ROOT)}"
        )

        documents = load_documents_from_file(str(destination), file_type)

        logger.bind(user_id=current_user.email, document_count=len(documents)).info(
            f"Loaded {len(documents)} documents from {file.filename}"
        )

        documents = await _attach_embeddings(documents, embedding_service)
        indexed_count = await search_service.bulk_index_documents(documents)

        logger.bind(user_id=current_user.email, indexed_count=indexed_count).info(
            f"File ingest completed: {file.filename}"
        )

        return FileIngestResponse(
            indexed_count=indexed_count,
            index_name=settings.mongodb_collection,
            file_name=file.filename,
            file_type=file_type,
            documents_processed=len(documents),
            stored_path=str(destination.relative_to(BACKEND_ROOT)),
        )

    except Exception as exc:
        logger.bind(user_id=current_user.email).exception(f"File ingest failed: {file.filename}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/ingest/batch", response_model=BatchIngestResponse)
async def ingest_batch_from_directory(
    current_user: UserResponse = Depends(get_current_user),
    request: IngestRequest = Body(default=IngestRequest()),
    search_service: SearchService = Depends(get_search_service),
    embedding_service: HuggingFaceEmbeddingService = Depends(get_embedding_service),
) -> BatchIngestResponse:
    """Parcourt un dossier serveur, indexe chaque PDF/CSV trouvé, et retourne un résumé par fichier."""
    logger.bind(user_id=current_user.email).info(
        f"Batch ingest requested from directory: {request.directory_path}"
    )

    try:
        file_types_list = request.file_types if request.file_types else None
        results = load_documents_from_directory(
            request.directory_path,
            file_types=file_types_list,  # type: ignore
            recursive=request.recursive
        )

        if not results:
            logger.bind(user_id=current_user.email).warning(
                f"No files found in directory: {request.directory_path}"
            )
            return BatchIngestResponse(
                total_files_processed=0,
                total_documents_indexed=0,
                index_name=settings.mongodb_collection,
                files_summary=[],
                errors=["No files found in the specified directory"]
            )

        files_summary = []
        errors = []
        total_indexed = 0

        for file_path, documents in results.items():
            try:
                documents = await _attach_embeddings(documents, embedding_service)
                indexed_count = await search_service.bulk_index_documents(documents)
                total_indexed += indexed_count

                files_summary.append({
                    "file_path": file_path,
                    "documents_processed": len(documents),
                    "documents_indexed": indexed_count,
                    "status": "success"
                })

                logger.bind(user_id=current_user.email).info(
                    f"Indexed {indexed_count} documents from {file_path}"
                )

            except Exception as e:
                error_msg = f"Failed to index {file_path}: {str(e)}"
                errors.append(error_msg)
                logger.bind(user_id=current_user.email).error(error_msg)

                files_summary.append({
                    "file_path": file_path,
                    "documents_processed": len(documents),
                    "documents_indexed": 0,
                    "status": "failed",
                    "error": str(e)
                })

        logger.bind(user_id=current_user.email).info(
            f"Batch ingest completed: {len(results)} files, {total_indexed} documents"
        )

        return BatchIngestResponse(
            total_files_processed=len(results),
            total_documents_indexed=total_indexed,
            index_name=settings.mongodb_collection,
            files_summary=files_summary,
            errors=errors if errors else None
        )

    except FileNotFoundError as exc:
        logger.bind(user_id=current_user.email).error(
            f"Directory not found: {request.directory_path}"
        )
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    except Exception as exc:
        logger.bind(user_id=current_user.email).exception(
            f"Batch ingest failed from directory: {request.directory_path}"
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc
