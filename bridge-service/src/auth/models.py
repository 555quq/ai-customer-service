"""Authentication data models."""

from typing import Literal, Optional

from pydantic import BaseModel


Role = Literal["agent", "admin", "widget"]
TokenType = Literal["access", "refresh", "widget"]


class AuthUser(BaseModel):
    """Authenticated identity carried by application tokens."""

    id: str
    username: str
    role: Role


class TokenClaims(BaseModel):
    """Validated JWT claims used by the Bridge Service."""

    sub: str
    username: str
    role: Role
    type: TokenType
    jti: str
    iat: int
    exp: int
    iss: str
    aud: str
    session_id: Optional[str] = None
    family_id: Optional[str] = None
    conversation_id: Optional[str] = None
    chatwoot_conversation_id: Optional[str] = None
    site_id: Optional[str] = None
