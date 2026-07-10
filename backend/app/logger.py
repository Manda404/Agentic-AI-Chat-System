"""
Logger centralisé de l'application, basé sur Loguru.

C'est le SEUL endroit du projet où le logger est configuré (niveau,
format, destinations). Partout ailleurs dans le backend, on importe
l'objet déjà prêt à l'emploi :

    from app.logger import logger

    logger.info("Quelque chose s'est passé")
    logger.bind(user_id=email).warning("Tentative suspecte")

Pourquoi Loguru plutôt que le module `logging` standard ?
- Un seul objet `logger` à importer partout, pas besoin de faire
  `logging.getLogger(__name__)` dans chaque fichier.
- Ajout de contexte structuré très simple avec `.bind(cle=valeur)`.
- Rotation de fichiers de logs intégrée, sans configuration compliquée.

Destinations des logs :
- Console (stdout), colorée en développement, en JSON si LOG_FORMAT_JSON=true.
- Fichier, dans le dossier `logs/` (créé automatiquement à la racine du
  backend), avec rotation automatique pour ne jamais avoir un fichier
  de logs énorme.

Contexte de requête (session_id, transaction_id, agent_type, user_id, route) :
Ce contexte permet de retrouver, dans les logs, TOUT le parcours d'une
requête de chat : de la réception HTTP jusqu'à la réponse finale de
l'agent, même si plusieurs requêtes s'exécutent en même temps.
Utilisation typique (voir `workflows/chat_workflow.py`) :

    set_log_context(thread_id=conversation_id, agent_type="workflow")
    ...
    update_log_context(route=state.route)
    ...
    clear_log_context()

Le contexte est stocké dans une `ContextVar` (donc isolé par requête/tâche
asyncio) et injecté automatiquement dans chaque log via `logger.patch(...)`.
"""

import contextvars
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger as _logger

# --- Configuration (surchargeable via variables d'environnement) ----------

LOG_DIR = Path(os.getenv("LOG_DIR", "logs"))
LOG_FILE_NAME = os.getenv("LOG_FILE", "multi-agent-backend.log")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FORMAT_JSON = os.getenv("LOG_FORMAT_JSON", "false").lower() == "true"
LOG_ROTATION = os.getenv("LOG_ROTATION", "10 MB")
# Nombre de fichiers de logs archivés à conserver (Loguru attend un int ici,
# pas une chaîne du type "3 files").
LOG_RETENTION = int(os.getenv("LOG_RETENTION", "3"))
LOG_TO_CONSOLE = os.getenv("LOG_TO_CONSOLE", "true").lower() == "true"
LOG_TO_FILE = os.getenv("LOG_TO_FILE", "true").lower() == "true"

# Valeurs par défaut du contexte quand aucune requête n'est en cours
# (ex: logs émis au démarrage de l'application).
_DEFAULT_CONTEXT: Dict[str, str] = {
    "session_id": "-",
    "transaction_id": "-",
    "agent_type": "-",
    "user_id": "-",
    "route": "-",
}

_log_context: contextvars.ContextVar[Dict[str, str]] = contextvars.ContextVar(
    "log_context", default={}
)


def _inject_context(record: Dict[str, Any]) -> None:
    """Fusionne le contexte de requête courant dans chaque log émis."""
    record["extra"].update({**_DEFAULT_CONTEXT, **_log_context.get()})


def _render_extra_fields(record: Dict[str, Any]) -> str:
    """
    Formate les champs ajoutés via `logger.bind(cle=valeur)` (en plus du
    contexte fixe session/txn/agent/user/route), pour qu'ils soient
    directement visibles dans le message, sans avoir besoin du mode JSON.
    """
    extra_keys = set(record["extra"].keys()) - set(_DEFAULT_CONTEXT.keys())
    if not extra_keys:
        return ""
    rendered = " ".join(f"{key}={record['extra'][key]}" for key in sorted(extra_keys))
    # échappe les accolades pour ne pas casser le formatage de Loguru
    return rendered.replace("{", "{{").replace("}", "}}")


def _console_format(record: Dict[str, Any]) -> str:
    extra_fields = _render_extra_fields(record)
    extra_suffix = f" <dim>({extra_fields})</dim>" if extra_fields else ""
    return (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<magenta>session={extra[session_id]}</magenta> "
        "<magenta>txn={extra[transaction_id]}</magenta> "
        "<yellow>agent={extra[agent_type]}</yellow> "
        "user={extra[user_id]} "
        "<blue>route={extra[route]}</blue> - "
        f"<level>{{message}}</level>{extra_suffix}\n{{exception}}"
    )


def _file_format(record: Dict[str, Any]) -> str:
    extra_fields = _render_extra_fields(record)
    extra_suffix = f" ({extra_fields})" if extra_fields else ""
    return (
        "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | "
        "session={extra[session_id]} txn={extra[transaction_id]} "
        "agent={extra[agent_type]} user={extra[user_id]} route={extra[route]} - "
        f"{{message}}{extra_suffix}\n{{exception}}"
    )


# Objet logger final à importer partout ailleurs dans le projet.
logger = _logger.patch(_inject_context)

_configured = False


def configure_logger() -> None:
    """
    Configure les destinations et le format des logs.

    Doit être appelée une seule fois, au tout début du démarrage de
    l'application (voir `app/main.py`). Un appel répété est sans danger :
    la fonction ne fait rien si elle a déjà été exécutée.
    """
    global _configured
    if _configured:
        return

    logger.remove()  # retire le handler par défaut de Loguru (stderr brut)

    if LOG_TO_CONSOLE:
        if LOG_FORMAT_JSON:
            logger.add(sys.stdout, level=LOG_LEVEL, serialize=True)
        else:
            logger.add(
                sys.stdout,
                level=LOG_LEVEL,
                format=_console_format,
                colorize=True,
            )

    if LOG_TO_FILE:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        logger.add(
            LOG_DIR / LOG_FILE_NAME,
            level=LOG_LEVEL,
            format="{message}" if LOG_FORMAT_JSON else _file_format,
            serialize=LOG_FORMAT_JSON,
            rotation=LOG_ROTATION,
            retention=LOG_RETENTION,
            enqueue=True,  # écriture thread/async-safe
            encoding="utf-8",
        )

    _configured = True
    logger.info(
        "Logger configuré.",
        log_dir=str(LOG_DIR.resolve()) if LOG_TO_FILE else "disabled",
        level=LOG_LEVEL,
        json_format=LOG_FORMAT_JSON,
    )


def set_log_context(
    thread_id: str,
    agent_type: Optional[str] = None,
    user_id: Optional[str] = None,
    route: Optional[str] = None,
) -> None:
    """
    Démarre un nouveau contexte de log pour une requête/conversation.

    `thread_id` devient le `session_id` de tous les logs suivants émis
    dans cette même tâche asyncio, jusqu'à l'appel de `clear_log_context()`.
    Un `transaction_id` unique est généré pour distinguer deux passages
    dans le workflow pour la même conversation.
    """
    context: Dict[str, str] = {
        "session_id": thread_id,
        "transaction_id": str(uuid.uuid4()),
    }
    if agent_type:
        context["agent_type"] = agent_type
    if user_id:
        context["user_id"] = user_id
    if route:
        context["route"] = route
    _log_context.set(context)


def update_log_context(**kwargs: Any) -> None:
    """Met à jour une ou plusieurs clés du contexte de log courant."""
    current_context = _log_context.get().copy()
    current_context.update(kwargs)
    _log_context.set(current_context)


def clear_log_context() -> None:
    """Réinitialise le contexte de log (à appeler en fin de requête)."""
    _log_context.set({})
