"""
Logique métier de l'authentification : inscription, connexion, lookup.

Les comptes utilisateurs sont stockés dans Redis (via `RedisMemoryService`)
sous la clé `user:<email>`, en JSON, SANS expiration (`ttl=-1`) : un
compte créé reste valide indéfiniment. Le mot de passe n'est jamais
stocké en clair (voir `app.utils.security.hash_password`).
"""

import json
from typing import Optional

from app.logger import logger
from app.memory.redis_memory import RedisMemoryService
from app.models.auth_models import LoginRequest, RegisterRequest, UserResponse
from app.utils.security import hash_password, verify_password

class AuthService:
    """Gère le cycle de vie des comptes utilisateurs stockés dans Redis."""

    def __init__(self,memory_service: RedisMemoryService):
        self.memory_service = memory_service

    def register_user(self,request:RegisterRequest)->UserResponse:
        """Crée un compte si l'email n'existe pas déjà, sinon lève `ValueError`."""
        key = self.memory_service.user_key(request.email)
        existing = self.memory_service.get_value(key)

        if existing:
            logger.bind(user_id=request.email).debug("Registration rejected: user already exists.")
            raise ValueError("User Already Exists.")

        payload = {
            "email": request.email,
            "hashed_password": hash_password(request.password)
        }

        self.memory_service.set_value(key, json.dumps(payload),ttl=-1)
        logger.bind(user_id=request.email, storage_key=key).info("User account created and stored.")
        return UserResponse(email=request.email)

    def authenticate_user(self, request: LoginRequest) -> Optional[UserResponse]:
        """Vérifie l'email + mot de passe, retourne `None` si l'un des deux est invalide."""
        key = self.memory_service.user_key(request.email)
        stored_user = self.memory_service.get_value(key)
        if not stored_user:
            logger.bind(user_id=request.email).debug("Authentication failed: unknown email.")
            return None

        payload = json.loads(stored_user)
        if not verify_password(request.password, payload["hashed_password"]):
            logger.bind(user_id=request.email).debug("Authentication failed: wrong password.")
            return None
        return UserResponse(email=request.email)


    def get_user(self, email: str) -> Optional[UserResponse]:
        """Récupère un utilisateur par email, utilisé pour valider un token JWT décodé."""
        key = self.memory_service.user_key(email)
        stored_user = self.memory_service.get_value(key)
        if not stored_user:
            return None
        payload = json.loads(stored_user)
        return UserResponse(email=payload["email"])
