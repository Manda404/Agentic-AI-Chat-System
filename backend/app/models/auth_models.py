"""
Schémas Pydantic pour l'authentification (`auth_router.py`).
"""

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    """Corps attendu par `POST /api/v1/auth/register`."""
    email: EmailStr
    password: str = Field(min_length=6)


class LoginRequest(BaseModel):
    """Corps attendu par `POST /api/v1/auth/login`."""
    email: EmailStr
    password: str = Field(min_length=6)


class TokenResponse(BaseModel):
    """Réponse renvoyée après une connexion réussie : le JWT à utiliser en `Authorization: Bearer`."""
    access_token: str
    token_type: str = "bearer"
    email: EmailStr


class UserResponse(BaseModel):
    """Représentation minimale d'un utilisateur authentifié."""
    email: EmailStr


