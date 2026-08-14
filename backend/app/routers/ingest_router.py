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
import os
import tempfile
from pathlib import Path
from typing import Dict, List
from app.config.settings import settings
from app.data_ingest.file_ingest import (
    detect_file_type,
    load_documents_from_directory,
    load_documents_from_file,
    load_documents_from_csv
)
from app.dependencies.auth_dependencies import get_current_user
from app.logger import logger
from app.models.auth_models import UserResponse
from app.models.ingest_models import (
    BatchIngestResponse,
    FileIngestResponse,
    IngestRequest,
    IngestResponse,
)
from app.services.embedding_service import HuggingFaceEmbeddingService
from app.services.search_service import SearchService

router = APIRouter(prefix=settings.api_prefix, tags=["ingest"])

search_service = SearchService()
embedding_service = HuggingFaceEmbeddingService()


async def _attach_embeddings(documents: List[Dict[str, str]]) -> List[Dict[str, str]]:
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


@router.post("/ingest/sample-data", response_model=IngestResponse)
async def ingest_sample_data(current_user: UserResponse = Depends(get_current_user)) -> IngestResponse:
    """Charge et indexe le CSV d'exemple `backend/data/ai_tooling_catalog.csv`."""
    logger.bind(user_id=current_user.email).info("Sample ingest requested.")
    try:
        documents = load_documents_from_csv("data/ai_tooling_catalog.csv")
        logger.bind(user_id=current_user.email, document_count=len(documents)).info(
            "CSV documents loaded for ingest."
        )
        documents = await _attach_embeddings(documents)
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
    current_user: UserResponse = Depends(get_current_user)
) -> FileIngestResponse:
    """Reçoit un fichier PDF/CSV, l'écrit dans un fichier temporaire, l'indexe, puis nettoie le disque."""
    logger.bind(user_id=current_user.email).info(f"File upload ingest requested: {file.filename}")

    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    try:
        file_type = detect_file_type(file.filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    temp_file = None
    temp_file_path = ""
    try:
        suffix = Path(file.filename).suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            content = await file.read()
            temp_file.write(content)
            temp_file_path = temp_file.name

        logger.bind(user_id=current_user.email).info(
            f"File saved to temporary location: {temp_file_path}"
        )

        documents = load_documents_from_file(temp_file_path, file_type)

        logger.bind(user_id=current_user.email, document_count=len(documents)).info(
            f"Loaded {len(documents)} documents from {file.filename}"
        )

        documents = await _attach_embeddings(documents)
        indexed_count = await search_service.bulk_index_documents(documents)

        logger.bind(user_id=current_user.email, indexed_count=indexed_count).info(
            f"File ingest completed: {file.filename}"
        )

        return FileIngestResponse(
            indexed_count=indexed_count,
            index_name=settings.mongodb_collection,
            file_name=file.filename,
            file_type=file_type,
            documents_processed=len(documents)
        )

    except Exception as exc:
        logger.bind(user_id=current_user.email).exception(f"File ingest failed: {file.filename}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    finally:
        if temp_file and os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
                logger.debug(f"Cleaned up temporary file: {temp_file_path}")
            except Exception as e:
                logger.warning(f"Failed to clean up temporary file: {e}")


@router.post("/ingest/batch", response_model=BatchIngestResponse)
async def ingest_batch_from_directory(
    current_user: UserResponse = Depends(get_current_user),
    request: IngestRequest = Body(default=IngestRequest())
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
                documents = await _attach_embeddings(documents)
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

