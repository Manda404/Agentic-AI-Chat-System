"""Central Loguru configuration. Import `logger` from this module everywhere else. Console output supports development colors or LOG_FORMAT_JSON; rotating files are configured through settings. Use logger.bind(key=value) for structured fields. Request context (session, transaction, agent, user and route) lives in a ContextVar, isolated per asynchronous task and injected by logger.patch. Call set_log_context at request entry, update_log_context as routing progresses, and clear_log_context on exit."""

import contextvars
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger as _logger

# --- Configuration (overridable through environment variables) ----------

LOG_DIR = Path(os.getenv("LOG_DIR", "logs"))
LOG_FILE_NAME = os.getenv("LOG_FILE", "multi-agent-backend.log")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FORMAT_JSON = os.getenv("LOG_FORMAT_JSON", "false").lower() == "true"
LOG_ROTATION = os.getenv("LOG_ROTATION", "10 MB")
# Number of archived log files to keep (Loguru expects an integer,
# not a string such as "3 files").
LOG_RETENTION = int(os.getenv("LOG_RETENTION", "3"))
LOG_TO_CONSOLE = os.getenv("LOG_TO_CONSOLE", "true").lower() == "true"
LOG_TO_FILE = os.getenv("LOG_TO_FILE", "true").lower() == "true"

# Default context when no request is active
# (for example, application startup logs).
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
    """Merge the current request context into each emitted log record."""
    record["extra"].update({**_DEFAULT_CONTEXT, **_log_context.get()})


def _render_extra_fields(record: Dict[str, Any]) -> str:
    """Render fields added with logger.bind alongside the fixed request context in non-JSON output."""
    extra_keys = set(record["extra"].keys()) - set(_DEFAULT_CONTEXT.keys())
    if not extra_keys:
        return ""
    rendered = " ".join(f"{key}={record['extra'][key]}" for key in sorted(extra_keys))
    # escape braces to preserve Loguru formatting
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


# Configured logger to import elsewhere in the project.
logger = _logger.patch(_inject_context)

_configured = False


def configure_logger() -> None:
    """Configure log destinations and formatting at application startup. Repeated calls are harmless."""
    global _configured
    if _configured:
        return

    logger.remove()  # remove the default Loguru stderr handler

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
            enqueue=True,  # thread-safe and async-safe writes
            encoding="utf-8",
        )

    _configured = True
    logger.info(
        "Logger configured.",
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
    """Start request logging context: thread_id becomes session_id and a fresh transaction ID distinguishes runs in the same conversation. Clear the context on request exit."""
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
    """Update keys in the current logging context."""
    current_context = _log_context.get().copy()
    current_context.update(kwargs)
    _log_context.set(current_context)


def clear_log_context() -> None:
    """Reset logging context at the end of the request."""
    _log_context.set({})
