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

L'ingestion ajoute aussi `owner_id`/`visibility`, des IDs stables et des limites
de taille pour réduire les doublons et les risques d'abus.

Toutes ces routes nécessitent un utilisateur authentifié.
"""

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
import asyncio
import hashlib
import shutil
from pathlib import Path
from typing import Any, Dict, List
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


def _is_admin(user: UserResponse) -> bool:
    """Vérifie si l'utilisateur courant est autorisé pour les opérations globales."""
    return user.email.lower() in settings.admin_emails


def _require_admin_if_enabled(user: UserResponse, enabled: bool, operation: str) -> None:
    """Bloque les opérations dangereuses en production sans casser le mode local."""
    if enabled and not _is_admin(user):
        raise HTTPException(
            status_code=403,
            detail=f"{operation} requires an admin account. Configure ADMIN_EMAILS.",
        )


def _batch_root() -> Path:
    """Racine serveur autorisée pour l'ingestion batch."""
    root = Path(settings.batch_ingest_root)
    if not root.is_absolute():
        root = BACKEND_ROOT / root
    return root.resolve()


def _resolve_batch_directory(directory_path: str) -> Path:
    """Normalise le dossier batch et interdit de sortir de la racine configurée."""
    requested = Path(directory_path or settings.batch_ingest_root)
    if not requested.is_absolute():
        requested = BACKEND_ROOT / requested
    resolved = requested.resolve()
    root = _batch_root()
    if resolved != root and root not in resolved.parents:
        raise HTTPException(
            status_code=400,
            detail=f"Batch ingest directory must stay under {root}.",
        )
    return resolved


def _available_upload_path(filename: str) -> Path:
    """Construit un chemin sûr sans écraser un document déjà enregistré."""
    safe_name = Path(filename).name
    destination = UPLOAD_DIRECTORY / safe_name
    if destination.exists():
        destination = UPLOAD_DIRECTORY / f"{destination.stem}-{uuid4().hex[:8]}{destination.suffix}"
    return destination


def _persist_upload(source, destination: Path, max_bytes: int) -> None:
    """Copie le fichier temporaire de Starlette vers le stockage local permanent."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    source.seek(0)
    bytes_written = 0
    with destination.open("wb") as target:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            bytes_written += len(chunk)
            if bytes_written > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"Uploaded file exceeds {max_bytes} bytes.",
                )
            target.write(chunk)


def _discard_failed_upload(destination: Path) -> None:
    """Supprime un fichier uploadé qui n'a pas pu être indexé."""
    try:
        if destination.exists():
            destination.unlink()
    except Exception as exc:
        logger.bind(path=str(destination), reason=str(exc)).warning(
            "Failed upload cleanup did not complete."
        )


def _clean_text(value: Any, limit: int | None = None) -> str:
    """Nettoie un champ texte avant stockage/indexation."""
    text = str(value or "").replace("\x00", "").strip()
    if limit is not None and len(text) > limit:
        return text[:limit]
    return text


def _stable_document_id(document: Dict[str, Any]) -> str:
    """Construit un identifiant stable pour éviter les doublons à la réingestion."""
    identity_owner = (
        _clean_text(document.get("owner_id")).lower()
        if document.get("visibility") == "private"
        else ""
    )
    identity = "|".join(
        [identity_owner]
        + [
            str(document.get(key, "") or "").strip()
            for key in ("source", "file_name", "page_number", "title", "snippet")
        ]
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _attach_document_ids(documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ajoute `document_id` et `_id` MongoDB déterministes à chaque document."""
    for document in documents:
        document_id = str(document.get("document_id") or _stable_document_id(document))
        document["document_id"] = document_id
        document["_id"] = document_id
    return documents


def _normalize_documents(documents: List[Dict[str, Any]], owner_id: str) -> List[Dict[str, Any]]:
    """Ajoute les métadonnées d'accès et borne les champs indexés."""
    normalized: list[dict[str, Any]] = []
    for document in documents:
        item = dict(document)
        item["title"] = _clean_text(item.get("title") or item.get("file_name") or "Untitled", 300)
        item["snippet"] = _clean_text(item.get("snippet"), settings.max_ingested_snippet_chars)
        item["category"] = _clean_text(item.get("category") or "document", 120)
        item["source"] = _clean_text(item.get("source") or "ingest", 300)
        item["file_name"] = _clean_text(item.get("file_name"), 300) or None
        item["owner_id"] = owner_id
        item["visibility"] = settings.document_default_visibility
        if item["snippet"]:
            normalized.append(item)
    return normalized


def _enforce_document_limit(documents: List[Dict[str, Any]], source_label: str) -> None:
    """Refuse une ingestion qui produirait trop de fragments en une requête."""
    if len(documents) > settings.max_ingest_documents:
        raise HTTPException(
            status_code=413,
            detail=(
                f"{source_label} produced {len(documents)} documents; "
                f"maximum is {settings.max_ingest_documents}."
            ),
        )


async def _prepare_documents(
    documents: List[Dict[str, Any]],
    embedding_service: HuggingFaceEmbeddingService,
    owner_id: str,
    source_label: str,
) -> List[Dict[str, Any]]:
    """Normalise, limite, vectorise, puis ajoute les identifiants stables."""
    normalized = _normalize_documents(documents, owner_id=owner_id)
    _enforce_document_limit(normalized, source_label)
    return _attach_document_ids(await _attach_embeddings(normalized, embedding_service))


async def _bump_document_version(memory_service: RedisMemoryService) -> None:
    """Invalide les clés de cache dépendantes du corpus documentaire."""
    await memory_service.increment_value("documents:version")


async def _attach_embeddings(
    documents: List[Dict[str, Any]],
    embedding_service: HuggingFaceEmbeddingService,
) -> List[Dict[str, Any]]:
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
        _require_admin_if_enabled(current_user, settings.reset_requires_admin, "Data reset")
        owner_id = None if _is_admin(current_user) or settings.document_scope_mode == "shared" else current_user.email
        mongodb_deleted = await search_service.clear_documents(owner_id=owner_id)
        redis_deleted = await memory_service.clear_runtime_data(owner_id=owner_id)
        await _bump_document_version(memory_service)
        logger.bind(
            user_id=current_user.email,
            mongodb_documents_deleted=mongodb_deleted,
            redis_runtime_entries_deleted=redis_deleted,
        ).warning("Application data reset completed; user accounts preserved.")
        return DataResetResponse(
            mongodb_documents_deleted=mongodb_deleted,
            redis_runtime_entries_deleted=redis_deleted,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.bind(user_id=current_user.email).exception("Application data reset failed.")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/ingest/sample-data", response_model=IngestResponse)
async def ingest_sample_data(
    current_user: UserResponse = Depends(get_current_user),
    search_service: SearchService = Depends(get_search_service),
    embedding_service: HuggingFaceEmbeddingService = Depends(get_embedding_service),
    memory_service: RedisMemoryService = Depends(get_memory_service),
) -> IngestResponse:
    """Charge et indexe le CSV d'exemple `backend/data/ai_tooling_catalog.csv`."""
    logger.bind(user_id=current_user.email).info("Sample ingest requested.")
    try:
        documents = await asyncio.to_thread(load_documents_from_csv, "data/ai_tooling_catalog.csv")
        logger.bind(user_id=current_user.email, document_count=len(documents)).info(
            "CSV documents loaded for ingest."
        )
        documents = await _prepare_documents(
            documents,
            embedding_service,
            owner_id=current_user.email,
            source_label="Sample data",
        )
        indexed_count = await search_service.bulk_index_documents(documents)
        if indexed_count:
            await _bump_document_version(memory_service)
        logger.bind(user_id=current_user.email, indexed_count=indexed_count).info(
            "Sample ingest completed."
        )
        return IngestResponse(
            indexed_count=indexed_count,
            index_name=settings.mongodb_collection,
            source_file="data/ai_tooling_catalog.csv",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.bind(user_id=current_user.email).exception("Sample ingest failed.")
        raise HTTPException(status_code=500, detail=str(exc)) from exc



@router.post("/ingest/upload", response_model=FileIngestResponse)
async def ingest_uploaded_file(
    file: UploadFile = File(...),
    current_user: UserResponse = Depends(get_current_user),
    search_service: SearchService = Depends(get_search_service),
    embedding_service: HuggingFaceEmbeddingService = Depends(get_embedding_service),
    memory_service: RedisMemoryService = Depends(get_memory_service),
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
        await asyncio.to_thread(_persist_upload, file.file, destination, settings.max_upload_bytes)

        logger.bind(user_id=current_user.email).info(
            f"Uploaded file saved: {destination.relative_to(BACKEND_ROOT)}"
        )

        documents = await asyncio.to_thread(load_documents_from_file, str(destination), file_type)

        logger.bind(user_id=current_user.email, document_count=len(documents)).info(
            f"Loaded {len(documents)} documents from {file.filename}"
        )

        documents = await _prepare_documents(
            documents,
            embedding_service,
            owner_id=current_user.email,
            source_label=file.filename,
        )
        indexed_count = await search_service.bulk_index_documents(documents)
        if indexed_count:
            await _bump_document_version(memory_service)

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

    except HTTPException:
        _discard_failed_upload(destination)
        raise
    except Exception as exc:
        _discard_failed_upload(destination)
        logger.bind(user_id=current_user.email).exception(f"File ingest failed: {file.filename}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/ingest/batch", response_model=BatchIngestResponse)
async def ingest_batch_from_directory(
    current_user: UserResponse = Depends(get_current_user),
    request: IngestRequest = Body(default=IngestRequest()),
    search_service: SearchService = Depends(get_search_service),
    embedding_service: HuggingFaceEmbeddingService = Depends(get_embedding_service),
    memory_service: RedisMemoryService = Depends(get_memory_service),
) -> BatchIngestResponse:
    """Parcourt un dossier serveur, indexe chaque PDF/CSV trouvé, et retourne un résumé par fichier."""
    _require_admin_if_enabled(current_user, settings.batch_ingest_requires_admin, "Batch ingest")
    directory_path = _resolve_batch_directory(request.directory_path)
    logger.bind(user_id=current_user.email).info(
        f"Batch ingest requested from directory: {directory_path}"
    )

    try:
        file_types_list = request.file_types if request.file_types else None
        results = await asyncio.to_thread(
            load_documents_from_directory,
            str(directory_path),
            file_types_list,  # type: ignore[arg-type]
            request.recursive,
        )
        if len(results) > settings.max_batch_files:
            raise HTTPException(
                status_code=413,
                detail=f"Batch contains {len(results)} files; maximum is {settings.max_batch_files}.",
            )
        total_loaded_documents = sum(len(documents) for documents in results.values())
        if total_loaded_documents > settings.max_ingest_documents:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Batch produced {total_loaded_documents} documents; "
                    f"maximum is {settings.max_ingest_documents}."
                ),
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
                documents = await _prepare_documents(
                    documents,
                    embedding_service,
                    owner_id=current_user.email,
                    source_label=file_path,
                )
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
        if total_indexed:
            await _bump_document_version(memory_service)

        return BatchIngestResponse(
            total_files_processed=len(results),
            total_documents_indexed=total_indexed,
            index_name=settings.mongodb_collection,
            files_summary=files_summary,
            errors=errors if errors else None
        )

    except HTTPException:
        raise
    except FileNotFoundError as exc:
        logger.bind(user_id=current_user.email).error(
            f"Directory not found: {directory_path}"
        )
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    except Exception as exc:
        logger.bind(user_id=current_user.email).exception(
            f"Batch ingest failed from directory: {request.directory_path}"
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc
