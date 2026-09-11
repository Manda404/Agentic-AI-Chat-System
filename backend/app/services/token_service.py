"""Create and decode JWT bearer tokens for request authentication. There is no token revocation: a token remains valid until expiry even after frontend logout."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import jwt

from app.config.settings import settings
from app.logger import logger

class TokenService:
    """Sign and verify JWTs with the application secret."""

    def create_access_token(self, subject: str) -> str:
        """Generate a signed JWT whose subject is the user's email."""
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
        """Validate JWT signature and expiry; raise an exception for invalid tokens."""
        return jwt.decode(token, settings.auth_secret_key, algorithms=[settings.auth_algorithm])