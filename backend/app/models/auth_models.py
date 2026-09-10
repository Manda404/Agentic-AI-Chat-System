"""Pydantic authentication schemas for auth_router."""

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    """Request body for POST /api/v1/auth/register."""
    email: EmailStr
    password: str = Field(min_length=6)


class LoginRequest(BaseModel):
    """Request body for POST /api/v1/auth/login."""
    email: EmailStr
    password: str = Field(min_length=6)


class TokenResponse(BaseModel):
    """Successful login response containing a JWT for Authorization: Bearer."""
    access_token: str
    token_type: str = "bearer"
    email: EmailStr


class UserResponse(BaseModel):
    """Minimal authenticated-user representation."""
    email: EmailStr


