"""Durable, visitor-bound handoff state stored in Redis."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any


class HandoffStoreError(RuntimeError):
    """Base class for handoff state failures."""


class HandoffStoreUnavailable(HandoffStoreError):
    """Raised when handoff state cannot be read or written safely."""


class HandoffVisitorMismatch(HandoffStoreError):
    """Raised when a visitor tries to restore another visitor's handoff."""


class HandoffSessionNotRestorable(HandoffStoreError):
    """Raised for legacy handoffs that have no visitor binding."""


@dataclass(frozen=True)
class HandoffRecord:
    chatwoot_conversation_id: str


class HandoffStore:
    """Persist handoff routing and a non-reversible visitor binding."""

    def __init__(
        self,
        redis_client: Any,
        *,
        fingerprint_secret: str,
        ttl_seconds: int = 86400,
    ) -> None:
        self.client = redis_client
        self._secret = fingerprint_secret.encode("utf-8")
        self.ttl_seconds = ttl_seconds

    @staticmethod
    def _handoff_key(conversation_id: str) -> str:
        return f"handoff:{conversation_id}"

    @staticmethod
    def _visitor_key(conversation_id: str) -> str:
        return f"handoff_visitor:{conversation_id}"

    @staticmethod
    def _text(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)

    def _fingerprint(self, visitor_id: str) -> str:
        return hmac.new(
            self._secret,
            visitor_id.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _require_client(self) -> Any:
        if self.client is None:
            raise HandoffStoreUnavailable("Handoff store is unavailable")
        return self.client

    async def save(
        self,
        conversation_id: str,
        visitor_id: str,
        chatwoot_conversation_id: str,
    ) -> None:
        client = self._require_client()
        try:
            async with client.pipeline(transaction=True) as pipeline:
                pipeline.setex(
                    self._handoff_key(conversation_id),
                    self.ttl_seconds,
                    str(chatwoot_conversation_id),
                )
                pipeline.setex(
                    self._visitor_key(conversation_id),
                    self.ttl_seconds,
                    self._fingerprint(visitor_id),
                )
                results = await pipeline.execute()
                if len(results) != 2 or not all(results):
                    raise HandoffStoreUnavailable("Handoff state transaction was incomplete")
        except HandoffStoreError:
            raise
        except Exception as exc:
            raise HandoffStoreUnavailable("Unable to save handoff state") from exc

    async def resolve(
        self,
        conversation_id: str,
        visitor_id: str,
    ) -> HandoffRecord | None:
        client = self._require_client()
        try:
            raw_handoff, raw_visitor = await client.mget(
                [
                    self._handoff_key(conversation_id),
                    self._visitor_key(conversation_id),
                ]
            )
        except Exception as exc:
            raise HandoffStoreUnavailable("Unable to read handoff state") from exc

        chatwoot_conversation_id = self._text(raw_handoff)
        visitor_fingerprint = self._text(raw_visitor)
        if chatwoot_conversation_id is None and visitor_fingerprint is None:
            return None
        if chatwoot_conversation_id is None:
            raise HandoffStoreUnavailable("Handoff state is incomplete")
        if visitor_fingerprint is None:
            raise HandoffSessionNotRestorable("Legacy handoff has no visitor binding")
        if not hmac.compare_digest(visitor_fingerprint, self._fingerprint(visitor_id)):
            raise HandoffVisitorMismatch("Handoff visitor does not match")
        return HandoffRecord(chatwoot_conversation_id=chatwoot_conversation_id)

    async def get_chatwoot_conversation_id(self, conversation_id: str) -> str | None:
        client = self._require_client()
        try:
            return self._text(await client.get(self._handoff_key(conversation_id)))
        except Exception as exc:
            raise HandoffStoreUnavailable("Unable to read handoff route") from exc
