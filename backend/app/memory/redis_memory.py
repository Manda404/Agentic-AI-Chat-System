"""
Accès unifié à Redis (client ASYNCHRONE), avec repli automatique en mémoire
si Redis est injoignable.

Cette classe est réutilisée pour TROIS usages différents dans le
projet (voir les appelants) :
1. Stockage des comptes utilisateurs (`user:<email>`), sans expiration.
2. Historique de conversation (`conversation:<owner_hash>:<id>:messages`), qui
   expire après `ttl_seconds` (1h par défaut).
3. Cache des réponses de chat déjà générées
   (`chat:<owner_hash>:<id>:docs:<version>:<message>`).

Toutes les opérations d'exécution (`get_messages`, `append_message`, ...)
utilisent `redis.asyncio` : ce sont des méthodes `async def` appelées depuis
des agents/routes déjà async, et un client Redis synchrone bloquerait
l'event loop le temps de l'aller-retour réseau. Seule la vérification de
connectivité au démarrage (`__init__`) reste un ping synchrone bref, sur un
client jetable, avant que l'event loop ne serve de vraies requêtes.

Important : si Redis n'est pas disponible au démarrage (mauvaise URL,
service arrêté...), TOUTES les méthodes basculent silencieusement sur
un dictionnaire Python en mémoire (`_memory_store` / `_kv_store`). Le
backend continue donc de fonctionner sans Redis, mais :
- les données sont perdues au redémarrage du process ;
- elles ne sont PAS partagées entre plusieurs workers/instances.
Chaque bascule est loguée en `warning` pour que ce mode dégradé soit
visible dans les logs plutôt que silencieux.
"""

import hashlib
import json
from typing import Dict, List, Optional
from urllib.parse import urlsplit

from app.logger import logger


class RedisMemoryService:
    """Wrapper Redis asynchrone avec repli en mémoire locale en cas d'indisponibilité."""

    def __init__(self, url: str, ttl_seconds: int):
        """
        Vérifie la connectivité Redis avec un ping synchrone unique et
        jetable, puis crée le client asynchrone réutilisé par toutes les
        méthodes. Bascule en mode mémoire si le ping échoue.
        """
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
        """Retourne un endpoint utile au diagnostic sans identifiants ni paramètres."""
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
        """Ferme le pool asynchrone Redis, s'il a été créé."""
        if self._client is not None:
            await self._client.aclose()

    def _owner_scope(self, owner_id: Optional[str] = None) -> str:
        """Retourne un scope court non réversible pour isoler les données par utilisateur."""
        if not owner_id:
            return "shared"
        return hashlib.sha256(owner_id.strip().lower().encode("utf-8")).hexdigest()[:16]

    def conversation_key(self, conversation_id: str, owner_id: Optional[str] = None) -> str:
        """Clé Redis pour la liste des messages d'une conversation."""
        return f"conversation:{self._owner_scope(owner_id)}:{conversation_id}:messages"

    def user_key(self, email: str) -> str:
        """Clé Redis pour le compte utilisateur associé à un email."""
        return f"user:{email}"

    async def get_messages(self, conversation_id: str, owner_id: Optional[str] = None) -> List[Dict[str, str]]:
        """Retourne tout l'historique (rôle + contenu) d'une conversation."""
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
        """Ajoute un message (user/assistant) à l'historique et rafraîchit son expiration."""
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
        """Supprime définitivement l'historique d'une conversation."""
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
        """Supprime conversations et cache de chat, sans toucher aux comptes `user:*`."""
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
        """Lit une valeur simple (utilisé pour les comptes utilisateurs et le cache de chat)."""
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
        """Incrémente une valeur entière utilisée pour versionner un état runtime."""
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
        """True si la connexion Redis a réussi au démarrage (utilisé par `/health`)."""
        return self._available
