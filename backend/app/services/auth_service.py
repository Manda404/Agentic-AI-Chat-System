"""Registration, authentication and account lookup. Redis stores JSON accounts under user:<email> without expiration (ttl=-1). Passwords are hashed through app.utils.security and are never stored in plaintext."""

import json
from typing import Optional

from app.logger import logger
from app.memory.redis_memory import RedisMemoryService
from app.models.auth_models import LoginRequest, RegisterRequest, UserResponse
from app.utils.security import hash_password, verify_password

class AuthService:
    """Manage the lifecycle of Redis-backed user accounts."""

    def __init__(self,memory_service: RedisMemoryService):
        self.memory_service = memory_service

    async def register_user(self,request:RegisterRequest)->UserResponse:
        """Create an account unless the email already exists; raise ValueError on duplicates."""
        key = self.memory_service.user_key(request.email)
        existing = await self.memory_service.get_value(key)

        if existing:
            logger.bind(user_id=request.email).debug("Registration rejected: user already exists.")
            raise ValueError("User Already Exists.")

        payload = {
            "email": request.email,
            "hashed_password": hash_password(request.password)
        }

        await self.memory_service.set_value(key, json.dumps(payload),ttl=-1)
        logger.bind(user_id=request.email, storage_key=key).info("User account created and stored.")
        return UserResponse(email=request.email)

    async def authenticate_user(self, request: LoginRequest) -> Optional[UserResponse]:
        """Validate email and password; return None when either is invalid."""
        key = self.memory_service.user_key(request.email)
        stored_user = await self.memory_service.get_value(key)
        if not stored_user:
            logger.bind(user_id=request.email).debug("Authentication failed: unknown email.")
            return None

        payload = json.loads(stored_user)
        if not verify_password(request.password, payload["hashed_password"]):
            logger.bind(user_id=request.email).debug("Authentication failed: wrong password.")
            return None
        return UserResponse(email=request.email)


    async def get_user(self, email: str) -> Optional[UserResponse]:
        """Look up an email account when validating a decoded JWT."""
        key = self.memory_service.user_key(email)
        stored_user = await self.memory_service.get_value(key)
        if not stored_user:
            return None
        payload = json.loads(stored_user)
        return UserResponse(email=payload["email"])
