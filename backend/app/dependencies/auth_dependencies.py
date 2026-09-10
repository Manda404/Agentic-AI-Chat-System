"""JWT-protected FastAPI dependency: Depends(get_current_user). Read the Authorization bearer token, validate it and resolve the authenticated account."""

from fastapi import Header, HTTPException

from fastapi import Depends

from app.dependencies.services import get_auth_service
from app.logger import logger
from app.models.auth_models import UserResponse
from app.services.auth_service import AuthService
from app.services.token_service import TokenService

token_service = TokenService()


async def get_current_user(
    authorization: str = Header(default=""),
    auth_service: AuthService = Depends(get_auth_service),
) -> UserResponse:
    """Validate Authorization: Bearer <token> and return the current user."""
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
        user = await auth_service.get_user(email)
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

