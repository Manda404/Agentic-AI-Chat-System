"""Diagnostic Atlas en lecture seule : python -m app.evaluation.index_health."""
import argparse
import json

import certifi
from pymongo import MongoClient
from app.config.settings import settings


def expected_vector_definition() -> dict:
    return {"fields": [
        {"type": "vector", "path": "embedding", "numDimensions": settings.embedding_dimensions, "similarity": "cosine"},
        {"type": "filter", "path": "owner_id"},
        {"type": "filter", "path": "visibility"},
    ]}


def inspect_collection(collection) -> dict:
    """Ne retourne aucun texte documentaire, identifiant utilisateur ou secret."""
    indexes = {item['name']: item for item in collection.list_search_indexes()}
    checks, problems = {}, []
    for kind, name in (("text", settings.mongodb_search_index), ("vector", settings.mongodb_vector_index)):
        index = indexes.get(name, {})
        checks[kind] = {"name": name, "present": bool(index), "status": index.get('status'), "queryable": index.get('queryable', False)}
        if not index or not index.get('queryable'):
            problems.append(f"{kind}_index_not_queryable")
        if kind == 'vector' and index:
            fields = index.get('latestDefinition', {}).get('fields', [])
            if not any(field.get('type') == 'vector' and field.get('path') == 'embedding' and field.get('numDimensions') == settings.embedding_dimensions for field in fields):
                problems.append('vector_index_dimensions_mismatch')
            filters = {field.get('path') for field in fields if field.get('type') == 'filter'}
            if settings.document_scope_mode == 'owner' and not {'owner_id', 'visibility'} <= filters:
                problems.append('vector_access_filter_fields_missing')
    total = collection.count_documents({})
    embedded = collection.count_documents({'embedding': {'$type': 'array'}})
    matching_model = collection.count_documents({'embedding_model': settings.embedding_model, 'embedding': {'$type': 'array'}})
    if not total:
        problems.append('empty_corpus')
    if embedded != total:
        problems.append('documents_without_embeddings')
    if matching_model != embedded:
        problems.append('unknown_or_different_embedding_model')
    return {"ok": not problems, "indexes": checks, "documents": total, "embedded_documents": embedded,
            "configured_model_documents": matching_model, "problems": problems}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vector-definition', action='store_true', help='Print the expected Atlas index definition without connecting.')
    args = parser.parse_args()
    if args.vector_definition:
        print(json.dumps(expected_vector_definition(), indent=2))
        return 0
    if not settings.mongodb_uri:
        print(json.dumps({"ok": False, "error": "MONGODB_URI_missing"}))
        return 1
    try:
        with MongoClient(settings.mongodb_uri, tls=True, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=5000, connectTimeoutMS=5000, socketTimeoutMS=10000) as client:
            report = inspect_collection(client[settings.mongodb_db_name][settings.mongodb_collection])
        print(json.dumps(report, indent=2))
        return 0 if report['ok'] else 1
    except Exception as exc:
        print(json.dumps({"ok": False, "error_type": type(exc).__name__, "error": "Atlas diagnostic unavailable; check connectivity and listSearchIndexes permissions."}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
