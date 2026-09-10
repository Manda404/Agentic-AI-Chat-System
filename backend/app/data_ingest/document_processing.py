"""Règles communes : découpage sans perte et identité documentaire."""

import hashlib
import json


def text_chunks(text: str, size: int, overlap: int = 150) -> list[str]:
    if size <= 0:
        raise ValueError("Chunk size must be positive.")
    overlap = min(overlap, size // 5)
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return chunks


def stable_document_id(document: dict) -> str:
    # Le propriétaire fait partie de l'identité même pour un document partagé.
    keys = ("owner_id", "visibility", "source", "file_name", "page_number", "title", "snippet", "chunk_index")
    identity = [str(document.get(key) or "").strip() for key in keys]
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode("utf-8")).hexdigest()


def with_document_id(document: dict) -> dict:
    item = dict(document)
    document_id = str(item.get("document_id") or item.get("_id") or stable_document_id(item))
    item.update(document_id=document_id, _id=document_id)
    return item
