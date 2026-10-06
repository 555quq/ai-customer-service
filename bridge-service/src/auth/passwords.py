"""Password hashing and configured-user authentication."""

import hmac

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from loguru import logger

from ..config import settings
from ..utils.config_manager import config_manager
from .models import AuthUser, Role
from .tokens import AuthConfigurationError


_password_hasher = PasswordHasher()


class AgentCredentialsNotConfigured(AuthConfigurationError):
    """Raised when an initialized deployment has not provisioned Agent auth."""


def hash_password(password: str) -> str:
    """Create an Argon2id password hash for deployment configuration."""
    return _password_hasher.hash(password)


def _is_production() -> bool:
    return str(settings.environment).lower() in {"production", "prod"}


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (InvalidHashError, VerificationError):
        return False


def authenticate_configured_user(
    username: str,
    password: str,
    role: Role,
) -> AuthUser | None:
    """Authenticate one of the configured Agent/Admin identities."""
    if role not in {"agent", "admin"}:
        return None

    runtime_auth = config_manager.get("auth", {}) or {}
    runtime_role = runtime_auth.get(role, {}) if isinstance(runtime_auth, dict) else {}
    if (
        role == "agent"
        and config_manager.get("setup.initialized", False)
        and not runtime_role.get("password_hash")
    ):
        raise AgentCredentialsNotConfigured(
            "Agent credentials must be configured by an administrator"
        )
    expected_username = runtime_role.get("username") or getattr(settings, f"{role}_username")
    password_hash = runtime_role.get("password_hash") or getattr(settings, f"{role}_password_hash", None)
    plaintext_password = getattr(settings, f"{role}_password", None)

    if not hmac.compare_digest(username, str(expected_username)):
        return None

    if password_hash:
        valid = verify_password(password, password_hash)
    else:
        if not plaintext_password:
            raise AuthConfigurationError(
                f"{role.upper()} credentials are not configured"
            )
        if _is_production():
            raise AuthConfigurationError(
                f"{role.upper()}_PASSWORD_HASH is required in production"
            )
        logger.warning("Development plaintext password compatibility is enabled")
        valid = bool(plaintext_password) and hmac.compare_digest(
            password,
            str(plaintext_password),
        )

    if not valid:
        return None
    return AuthUser(id=f"configured-{role}", username=username, role=role)
