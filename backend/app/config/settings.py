"""
Configuration centralisée de l'application, lue depuis les variables
d'environnement (`.env`, chargé par `load_dotenv()`).

C'est le SEUL endroit du projet où `os.getenv(...)` doit être appelé :
tout le reste du code importe l'objet `settings` déjà construit.
Chaque champ a une valeur par défaut raisonnable pour le développement
local ; voir `backend/.env.example` pour la liste complète et des
commentaires sur chaque variable.
"""

import os
from typing import List, Literal
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

APP_ENV_VALUE = os.getenv("APP_ENV", "development")
IS_LOCAL_ENV = APP_ENV_VALUE.lower() in {"development", "local", "test"}


class Settings(BaseModel):
    """Toutes les variables de configuration du backend, avec leurs valeurs par défaut."""
    app_name: str = os.getenv("APP_NAME", "Agentic RAG Platform Backend")
    app_env: str = APP_ENV_VALUE
    api_prefix: str = os.getenv("API_PREFIX", "/api/v1")
    backend_cors_origins: List[str] = [
        item.strip()
        for item in os.getenv(
            "BACKEND_CORS_ORIGINS",
            "http://localhost:3000,http://127.0.0.1:3000",
        ).split(",")
        if item.strip()
    ]
    # En développement uniquement, autorise aussi le frontend lorsqu'il est
    # ouvert via l'adresse privée de la machine (Wi-Fi/Ethernet).
    backend_cors_dev_origin_regex: str = os.getenv(
        "BACKEND_CORS_DEV_ORIGIN_REGEX",
        r"^https?://(?:localhost|127\.0\.0\.1|10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})(?::\d+)?$",
    )
    
    llm_provider: Literal["ollama", "huggingface"] = os.getenv("LLM_PROVIDER", "ollama") 
    
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
    
    huggingface_api_key: str = os.getenv("HUGGINGFACE_API_KEY", "")
    huggingface_model: str = os.getenv("HUGGINGFACE_MODEL", "mistralai/Mistral-7B-Instruct-v0.3")
    
    model_summarization: str = os.getenv("MODEL_SUMMARIZATION", "")
    model_code_generation: str = os.getenv("MODEL_CODE_GENERATION", "")
    model_question_answering: str = os.getenv("MODEL_QUESTION_ANSWERING", "")
    model_reasoning: str = os.getenv("MODEL_REASONING", "")
    embedding_model: str = os.getenv("MODEL_EMBEDDING", "BAAI/bge-small-en-v1.5")
    semantic_reranker_enabled: bool = os.getenv("SEMANTIC_RERANKER_ENABLED", "true").lower() == "true"
    
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    redis_ttl_seconds: int = int(os.getenv("REDIS_TTL_SECONDS", "3600"))
    
    mongodb_uri: str = os.getenv("MONGODB_URI", "")
    mongodb_db_name: str = os.getenv("MONGODB_DB_NAME", "agentic_rag")
    mongodb_collection: str = os.getenv("MONGODB_COLLECTION", "documents")
    mongodb_search_index: str = os.getenv("MONGODB_SEARCH_INDEX", "documents_search")
    mongodb_vector_index: str = os.getenv("MONGODB_VECTOR_INDEX", "documents_vector")
    embedding_dimensions: int = int(os.getenv("EMBEDDING_DIMENSIONS", "384"))
    document_scope_mode: Literal["shared", "owner"] = os.getenv(
        "DOCUMENT_SCOPE_MODE",
        "shared" if IS_LOCAL_ENV else "owner",
    )
    document_default_visibility: Literal["shared", "private"] = os.getenv(
        "DOCUMENT_DEFAULT_VISIBILITY",
        "shared" if IS_LOCAL_ENV else "private",
    )
    batch_ingest_root: str = os.getenv("BATCH_INGEST_ROOT", "data")
    max_upload_bytes: int = int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
    max_batch_files: int = int(os.getenv("MAX_BATCH_FILES", "20"))
    max_ingest_documents: int = int(os.getenv("MAX_INGEST_DOCUMENTS", "500"))
    max_ingested_snippet_chars: int = int(os.getenv("MAX_INGESTED_SNIPPET_CHARS", "5000"))
    admin_emails: List[str] = [
        item.strip().lower()
        for item in os.getenv("ADMIN_EMAILS", "").split(",")
        if item.strip()
    ]
    reset_requires_admin: bool = os.getenv(
        "RESET_REQUIRES_ADMIN",
        "false" if IS_LOCAL_ENV else "true",
    ).lower() == "true"
    batch_ingest_requires_admin: bool = os.getenv(
        "BATCH_INGEST_REQUIRES_ADMIN",
        "false" if IS_LOCAL_ENV else "true",
    ).lower() == "true"
    
    langfuse_host: str = os.getenv("LANGFUSE_HOST", "http://localhost:3001")
    langfuse_public_key: str = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    langfuse_secret_key: str = os.getenv("LANGFUSE_SECRET_KEY", "")
    langfuse_env: str = os.getenv("LANGFUSE_ENV", "local")
    langfuse_user_id: str = os.getenv("LANGFUSE_USER_ID", "local-dev")
    langfuse_enabled: bool = os.getenv("LANGFUSE_ENABLED", "false").lower() == "true"

    langgraph_checkpoint_enabled: bool = os.getenv("LANGGRAPH_CHECKPOINT_ENABLED", "false").lower() == "true"
    langgraph_checkpoint_backend: Literal["memory"] = os.getenv("LANGGRAPH_CHECKPOINT_BACKEND", "memory")
    max_user_message_chars: int = int(os.getenv("MAX_USER_MESSAGE_CHARS", "8000"))
    max_rag_context_chars: int = int(os.getenv("MAX_RAG_CONTEXT_CHARS", "4000"))
    max_rag_documents: int = int(os.getenv("MAX_RAG_DOCUMENTS", "5"))
    rate_limit_requests_per_minute: int = int(os.getenv("RATE_LIMIT_REQUESTS_PER_MINUTE", "60"))
    critic_enabled: bool = os.getenv("CRITIC_ENABLED", "true").lower() == "true"
    critic_routes: str = os.getenv(
        "CRITIC_ROUTES",
        "rag,direct_answer,summary,analysis,correction,planning",
    )
    safety_enabled: bool = os.getenv("SAFETY_ENABLED", "true").lower() == "true"
    citation_support_required: bool = os.getenv("CITATION_SUPPORT_REQUIRED", "false").lower() == "true"
    citation_support_min_overlap: int = int(os.getenv("CITATION_SUPPORT_MIN_OVERLAP", "1"))
    llm_timeout_seconds: int = int(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
    
    auth_secret_key: str = os.getenv("AUTH_SECRET_KEY", "change-me-in-real-projects")
    auth_algorithm: str = os.getenv("AUTH_ALGORITHM", "HS256")
    auth_token_expiry_minutes: int = int(os.getenv("AUTH_TOKEN_EXPIRY_MINUTES", "120"))
    
settings :Settings = Settings()
