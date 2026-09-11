"""Asynchronous Redis access with local-memory fallback. User accounts use user:<email> without expiration; owner-scoped conversation histories expire after ttl_seconds. Generic key/value methods also support legacy runtime data. Runtime operations use redis.asyncio; only the disposable startup connectivity probe is synchronous. Fallback data is process-local, lost on restart and not replicated from Redis. Failures are logged so degraded operation remains visible."""

import hashlib
import json
from typing import Dict, List, Optional
from urllib.parse import urlsplit

from app.logger import logger


class RedisMemoryService:
    """Asynchronous Redis wrapper with local-memory fallback on connection failures."""

    def __init__(self, url: str, ttl_seconds: int):
        """Perform a disposable synchronous startup ping, then create the shared asynchronous client. Fall back to local memory if the ping fails."""
        self.url = url
        self.ttl_seconds = ttl_seconds
        self._client = None
        self._available = False
        self._memory_store: Dict[str, List[Dict[str, str]]] = {}
        self._kv_store: Dict[str, str] = {}

        try:
            import importlib

            redis_module = importlib.import_module("redis")
            probe = redis_module.from_url(url, decode_responses=True)
            try:
                probe.ping()
            finally:
                probe.close()

            redis_asyncio_module = importlib.import_module("redis.asyncio")
            self._client = redis_asyncio_module.from_url(url, decode_responses=True)
            self._available = True
            logger.bind(redis_endpoint=self._safe_endpoint(url), ttl_seconds=ttl_seconds).info(
                "Redis connection established."
            )
        except Exception as exc:
            self._client = None
            self._available = False
            logger.bind(redis_endpoint=self._safe_endpoint(url), reason=str(exc)).warning(
                "Redis unavailable, falling back to in-memory storage."
            )

    @staticmethod
    def _safe_endpoint(url: str) -> str:
        """Return a diagnostic endpoint without credentials or query parameters."""
        try:
            parsed = urlsplit(url)
            if not parsed.scheme or not parsed.hostname:
                return "configured"
            host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
            port = f":{parsed.port}" if parsed.port is not None else ""
            return f"{parsed.scheme}://{host}{port}{parsed.path}"
        except (TypeError, ValueError):
            return "configured"

    async def close(self) -> None:
        """Close the asynchronous Redis pool if initialized."""
        if self._client is not None:
            await self._client.aclose()

    def _owner_scope(self, owner_id: Optional[str] = None) -> str:
        """Return a short irreversible scope for per-user isolation."""
        if not owner_id:
            return "shared"
        return hashlib.sha256(owner_id.strip().lower().encode("utf-8")).hexdigest()[:16]

    def conversation_key(self, conversation_id: str, owner_id: Optional[str] = None) -> str:
        """Build the Redis key for a conversation's message list."""
        return f"conversation:{self._owner_scope(owner_id)}:{conversation_id}:messages"

    def user_key(self, email: str) -> str:
        """Build the Redis account key for an email."""
        return f"user:{email}"

    async def get_messages(self, conversation_id: str, owner_id: Optional[str] = None) -> List[Dict[str, str]]:
        """Return the complete role/content history of a conversation."""
        local_key = self.conversation_key(conversation_id, owner_id)
        if self._client:
            try:
                items = await self._client.lrange(local_key, 0, -1)
                return [json.loads(item) for item in items]
            except Exception as exc:
                logger.bind(conversation_id=conversation_id, reason=str(exc)).warning(
                    "Redis read failed, falling back to in-memory store."
                )
                return self._memory_store.get(local_key, [])
        return self._memory_store.get(local_key, [])

    async def append_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        owner_id: Optional[str] = None,
    ) -> None:
        """Append a user/assistant message and refresh conversation expiration."""
        payload = {"role": role, "content": content}
        key = self.conversation_key(conversation_id, owner_id)
        if self._client:
            try:
                await self._client.rpush(key, json.dumps(payload))
                await self._client.expire(key, self.ttl_seconds)
                return
            except Exception as exc:
                logger.bind(conversation_id=conversation_id, reason=str(exc)).warning(
                    "Redis write failed, falling back to in-memory store."
                )
        self._memory_store.setdefault(key, []).append(payload)

    async def clear_messages(self, conversation_id: str, owner_id: Optional[str] = None) -> None:
        """Permanently remove a conversation's history."""
        key = self.conversation_key(conversation_id, owner_id)
        if self._client:
            try:
                await self._client.delete(key)
                return
            except Exception as exc:
                logger.bind(conversation_id=conversation_id, reason=str(exc)).warning(
                    "Redis delete failed, clearing in-memory store instead."
                )
        self._memory_store.pop(key, None)

    async def clear_runtime_data(self, owner_id: Optional[str] = None) -> int:
        """Remove conversations and legacy chat cache while retaining user:* accounts."""
        deleted = 0
        owner_scope = self._owner_scope(owner_id)
        if self._client:
            try:
                keys: list[str] = []
                patterns = (
                    [f"conversation:{owner_scope}:*:messages", f"chat:{owner_scope}:*"]
                    if owner_id
                    else ["conversation:*:messages", "chat:*"]
                )
                for pattern in patterns:
                    async for key in self._client.scan_iter(match=pattern):
                        keys.append(key)
                if keys:
                    deleted = int(await self._client.delete(*keys))
            except Exception as exc:
                logger.bind(reason=str(exc)).warning(
                    "Redis runtime reset failed; clearing local runtime data only."
                )

        if owner_id:
            conversation_prefix = f"conversation:{owner_scope}:"
            chat_prefix = f"chat:{owner_scope}:"
            memory_keys = [key for key in self._memory_store if key.startswith(conversation_prefix)]
            for key in memory_keys:
                deleted += len(self._memory_store.pop(key))
            chat_keys = [key for key in self._kv_store if key.startswith(chat_prefix)]
            for key in chat_keys:
                self._kv_store.pop(key, None)
            deleted += len(chat_keys)
        else:
            deleted += sum(len(messages) for messages in self._memory_store.values())
            deleted += sum(1 for key in self._kv_store if key.startswith("chat:"))
            self._memory_store.clear()
            self._kv_store = {
                key: value for key, value in self._kv_store.items() if not key.startswith("chat:")
            }
        return deleted

    async def get_value(self, key: str) -> Optional[str]:
        """Read a scalar value, including account and legacy runtime records."""
        if self._client:
            try:
                return await self._client.get(key)
            except Exception as exc:
                logger.bind(key=key, reason=str(exc)).warning(
                    "Redis read failed, falling back to in-memory store."
                )
                return self._kv_store.get(key)
        return self._kv_store.get(key)

    async def set_value(self, key: str, value: str, ttl: Optional[int] = None) -> None:
        """
        Set a key-value pair in Redis or in-memory store.

        Args:
            key: The key to store
            value: The value to store
            ttl: Time to live in seconds. If None, uses default ttl_seconds.
                 If -1, stores permanently without expiration.
        """
        if self._client:
            try:
                if ttl == -1:
                    await self._client.set(key, value)
                else:
                    expiry = ttl if ttl is not None else self.ttl_seconds
                    await self._client.setex(key, expiry, value)
                return
            except Exception as exc:
                logger.bind(key=key, reason=str(exc)).warning(
                    "Redis write failed, falling back to in-memory store."
                )
        self._kv_store[key] = value

    async def increment_value(self, key: str, ttl: Optional[int] = None) -> int:
        """Increment an integer used for runtime state versioning."""
        if self._client:
            try:
                value = int(await self._client.incr(key))
                if ttl is not None and value == 1:
                    await self._client.expire(key, ttl)
                return value
            except Exception as exc:
                logger.bind(key=key, reason=str(exc)).warning(
                    "Redis increment failed, falling back to in-memory store."
                )
        current = int(self._kv_store.get(key, "0") or "0") + 1
        self._kv_store[key] = str(current)
        return current

    @property
    def using_redis(self) -> bool:
        """Whether the startup Redis connection succeeded, as reported by /health."""
        return self._available
