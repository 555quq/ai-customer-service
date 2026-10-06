"""Refresh-token session storage with rotation and replay detection."""

from asyncio import Lock
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
from typing import Any, Optional


class SessionError(ValueError):
    """Base refresh-session error."""


class SessionNotFound(SessionError):
    """The refresh session is absent, expired, or revoked."""


class RefreshReuseDetected(SessionError):
    """A previously consumed refresh token was presented again."""


@dataclass
class RefreshSession:
    jti: str
    session_id: str
    family_id: str
    user_id: str
    username: str
    role: str
    token_hash: str
    created_at: int
    expires_at: int

    @classmethod
    def from_json(cls, value: str) -> "RefreshSession":
        return cls(**json.loads(value))

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AuthSessionStore:
    """Redis-backed store with a concurrency-safe in-memory development mode."""

    def __init__(self, redis_client: Optional[Any] = None, require_redis: bool = False):
        if require_redis and redis_client is None:
            raise RuntimeError("Redis is required for authentication sessions")
        self.redis = redis_client
        self._sessions: dict[str, RefreshSession] = {}
        self._used: dict[str, str] = {}
        self._families: dict[str, set[str]] = {}
        self._identities: dict[str, set[str]] = {}
        self._lock = Lock()

    @staticmethod
    def _session_key(jti: str) -> str:
        return f"auth:refresh:{jti}"

    @staticmethod
    def _used_key(jti: str) -> str:
        return f"auth:refresh:used:{jti}"

    @staticmethod
    def _family_key(family_id: str) -> str:
        return f"auth:refresh:family:{family_id}"

    @staticmethod
    def _identity_key(role: str, user_id: str) -> str:
        return f"auth:refresh:identity:{role}:{user_id}"

    async def create(self, session: RefreshSession) -> None:
        ttl = max(1, session.expires_at - int(datetime.now(timezone.utc).timestamp()))
        if self.redis is not None:
            await self.redis.setex(self._session_key(session.jti), ttl, session.to_json())
            await self.redis.sadd(self._family_key(session.family_id), session.jti)
            await self.redis.expire(self._family_key(session.family_id), ttl)
            identity_key = self._identity_key(session.role, session.user_id)
            await self.redis.sadd(identity_key, session.family_id)
            await self.redis.expire(identity_key, ttl)
            return

        async with self._lock:
            self._sessions[session.jti] = session
            self._families.setdefault(session.family_id, set()).add(session.jti)
            identity_key = self._identity_key(session.role, session.user_id)
            self._identities.setdefault(identity_key, set()).add(session.family_id)

    async def consume(self, jti: str, raw_token: str) -> RefreshSession:
        """Atomically consume a refresh session before issuing its replacement."""
        if self.redis is not None:
            raw = await self.redis.getdel(self._session_key(jti))
            if raw is None:
                family_id = await self.redis.get(self._used_key(jti))
                if family_id:
                    await self.revoke_family(str(family_id))
                    raise RefreshReuseDetected("Refresh token reuse detected")
                raise SessionNotFound("Refresh session not found")
            session = RefreshSession.from_json(raw)
            await self.redis.setex(
                self._used_key(jti),
                max(1, session.expires_at - int(datetime.now(timezone.utc).timestamp())),
                session.family_id,
            )
        else:
            async with self._lock:
                session = self._sessions.pop(jti, None)
                if session is None:
                    family_id = self._used.get(jti)
                    if family_id:
                        await self._revoke_memory_family(family_id)
                        raise RefreshReuseDetected("Refresh token reuse detected")
                    raise SessionNotFound("Refresh session not found")
                self._used[jti] = session.family_id

        if session.expires_at <= int(datetime.now(timezone.utc).timestamp()):
            raise SessionNotFound("Refresh session expired")
        if not hmac.compare_digest(session.token_hash, hash_refresh_token(raw_token)):
            await self.revoke_family(session.family_id)
            raise RefreshReuseDetected("Refresh token does not match its session")
        return session

    async def revoke(self, jti: str) -> None:
        if self.redis is not None:
            await self.redis.delete(self._session_key(jti))
            return
        async with self._lock:
            self._sessions.pop(jti, None)

    async def _revoke_memory_family(self, family_id: str) -> None:
        for member in self._families.pop(family_id, set()):
            self._sessions.pop(member, None)

    async def revoke_family(self, family_id: str) -> None:
        if self.redis is not None:
            key = self._family_key(family_id)
            members = await self.redis.smembers(key)
            if members:
                await self.redis.delete(*(self._session_key(str(item)) for item in members))
            await self.redis.delete(key)
            return
        async with self._lock:
            await self._revoke_memory_family(family_id)

    async def revoke_identity(self, role: str, user_id: str) -> None:
        """Revoke every refresh-token family issued to one configured identity."""
        identity_key = self._identity_key(role, user_id)
        if self.redis is not None:
            families = await self.redis.smembers(identity_key)
            for family_id in families or ():
                if isinstance(family_id, bytes):
                    family_id = family_id.decode("utf-8")
                await self.revoke_family(str(family_id))
            await self.redis.delete(identity_key)
            return

        async with self._lock:
            for family_id in self._identities.pop(identity_key, set()):
                await self._revoke_memory_family(family_id)
