"""FastAPI authentication and role dependencies."""

from collections.abc import Callable
from typing import Annotated, Optional

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..config import settings
from ..utils.auth import verify_api_key
from .models import AuthUser, Role
from .tokens import AuthConfigurationError, TokenValidationError, decode_token


bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[
        Optional[HTTPAuthorizationCredentials], Depends(bearer_scheme)
    ] = None,
    api_key: Annotated[Optional[str], Header(alias="X-API-Key")] = None,
) -> AuthUser:
    """Resolve an authenticated UI user from a short-lived Access Token."""
    if credentials and credentials.scheme.lower() == "bearer":
        try:
            claims = decode_token(credentials.credentials, "access")
        except AuthConfigurationError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication is not configured",
            ) from exc
        except TokenValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired access token",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        if claims.role not in {"agent", "admin"}:
            raise HTTPException(status_code=403, detail="User role is not permitted")
        return AuthUser(id=claims.sub, username=claims.username, role=claims.role)

    if settings.enable_dev_api_key_compat and api_key:
        await verify_api_key(api_key)
        return AuthUser(id="dev-api-key", username="dev-api-key", role="admin")

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing access token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_roles(*allowed_roles: Role) -> Callable:
    """Build a dependency that enforces one of the supplied roles."""
    async def dependency(user: AuthUser = Depends(get_current_user)) -> AuthUser:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return user

    return dependency


require_agent = require_roles("agent", "admin")
require_admin = require_roles("admin")
