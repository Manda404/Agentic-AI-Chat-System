"""
Création et décodage des tokens JWT utilisés pour authentifier les
requêtes (`Authorization: Bearer <token>`).

Attention : il n'y a pas de mécanisme de révocation. Un token reste
valide jusqu'à son expiration (`AUTH_TOKEN_EXPIRY_MINUTES`), même si
l'utilisateur se déconnecte côté frontend.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import jwt

from app.config.settings import settings
from app.logger import logger

class TokenService:
    """Encapsule la signature/vérification des JWT avec le secret applicatif."""

    def create_access_token(self, subject: str) -> str:
        """Génère un JWT signé dont le sujet (`sub`) est l'email de l'utilisateur."""
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.auth_token_expiry_minutes)
        payload: Dict[str, Any] = {
            "sub": subject,
            "exp": expires_at,
        }
        logger.bind(user_id=subject, expires_in_minutes=settings.auth_token_expiry_minutes).info(
            "Access token issued."
        )
        return jwt.encode(payload, settings.auth_secret_key, algorithm=settings.auth_algorithm)

    def decode_access_token(self, token: str) -> Dict[str, Any]:
        """Décode et valide la signature/expiration d'un JWT. Lève une exception si invalide."""
        return jwt.decode(token, settings.auth_secret_key, algorithms=[settings.auth_algorithm])