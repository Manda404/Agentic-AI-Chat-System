"""
Routes d'authentification : inscription, connexion et validation de session.

L'inscription et la connexion sont les SEULS endpoints publics du backend
(pas de JWT requis). La route `/me` est protégée et sert au frontend à
valider une session sauvegardée avant d'ouvrir le workspace.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from app.config.settings import settings
from app.dependencies.auth_dependencies import get_current_user
from app.dependencies.services import get_auth_service
from app.logger import logger
from app.models.auth_models import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from app.services.auth_service import AuthService
from app.services.token_service import TokenService


router = APIRouter(prefix=settings.api_prefix + "/auth", tags=["auth"])

token_service = TokenService()


@router.get("/me", response_model=UserResponse)
async def get_authenticated_user(
    current_user: UserResponse = Depends(get_current_user),
) -> UserResponse:
    """Valide le JWT fourni et retourne l'utilisateur de la session courante."""
    return current_user


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    request: RegisterRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> UserResponse:
    """Crée un nouveau compte utilisateur (email + mot de passe hashé) dans Redis."""
    logger.bind(user_id=request.email).info("Register request received.")
    try:
        user = await auth_service.register_user(request)
        logger.bind(user_id=request.email).info("Register request completed.")
        return user
    except ValueError as exc:
        logger.bind(user_id=request.email, reason=str(exc)).warning("Register request failed.")
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/login", response_model=TokenResponse)
async def login(
    request: LoginRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    """Vérifie les identifiants et retourne un token JWT valable `AUTH_TOKEN_EXPIRY_MINUTES` minutes."""
    logger.bind(user_id=request.email).info("Login request received.")
    user = await auth_service.authenticate_user(request)
    if not user:
        logger.bind(user_id=request.email).warning("Login request rejected.")
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    token = token_service.create_access_token(user.email)
    logger.bind(user_id=user.email).info("Login request completed.")
    return TokenResponse(access_token=token, email=user.email)
