"""
Dépendance FastAPI qui protège les routes nécessitant un utilisateur
authentifié : `Depends(get_current_user)`.

Lit l'en-tête `Authorization: Bearer <jwt>`, décode/valide le token,
puis vérifie que l'utilisateur existe toujours dans Redis. Toute
défaillance (en-tête absent, token invalide/expiré, utilisateur
introuvable) se traduit par une `HTTPException(401)`.
"""

from fastapi import Header, HTTPException

from app.config.settings import settings
from app.logger import logger
from app.memory.redis_memory import RedisMemoryService
from app.models.auth_models import UserResponse
from app.services.auth_service import AuthService
from app.services.token_service import TokenService

memory_service = RedisMemoryService(settings.redis_url, settings.redis_ttl_seconds)
auth_service = AuthService(memory_service)
token_service = TokenService()


def get_current_user(authorization: str = Header(default="")) -> UserResponse:
    """Valide le header `Authorization: Bearer <token>` et retourne l'utilisateur courant."""
    if not authorization.startswith("Bearer "):
        logger.bind(authorization_header_present=bool(authorization)).warning(
            "Rejected request: missing or malformed Authorization header."
        )
        raise HTTPException(status_code=401, detail="Missing or invalid bearer token.")

    token = authorization.replace("Bearer ", "", 1).strip()
    try:
        payload = token_service.decode_access_token(token)
        email = payload.get("sub")
        if not email:
            raise HTTPException(status_code=401, detail="Token subject is missing.")
        user = auth_service.get_user(email)
        if not user:
            logger.bind(user_id=email).warning("Token valid but user no longer exists.")
            raise HTTPException(status_code=401, detail="User not found.")
        logger.bind(user_id=email).debug("Authenticated request accepted.")
        return user
    except HTTPException:
        raise
    except Exception as exc:
        logger.bind(reason=str(exc)).warning("Rejected request: invalid or expired token.")
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}") from exc


