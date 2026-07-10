"""
Accès unifié à Redis, avec repli automatique en mémoire si Redis est
injoignable.

Cette classe est réutilisée pour TROIS usages différents dans le
projet (voir les appelants) :
1. Stockage des comptes utilisateurs (`user:<email>`), sans expiration.
2. Historique de conversation (`conversation:<id>:messages`), qui expire
   après `ttl_seconds` (1h par défaut).
3. Cache des réponses de chat déjà générées (clé `chat:<id>:<message>`).

Important : si Redis n'est pas disponible au démarrage (mauvaise URL,
service arrêté...), TOUTES les méthodes basculent silencieusement sur
un dictionnaire Python en mémoire (`_memory_store` / `_kv_store`). Le
backend continue donc de fonctionner sans Redis, mais :
- les données sont perdues au redémarrage du process ;
- elles ne sont PAS partagées entre plusieurs workers/instances.
Chaque bascule est loguée en `warning` pour que ce mode dégradé soit
visible dans les logs plutôt que silencieux.
"""

import json
from typing import Dict, List, Optional

from app.logger import logger


class RedisMemoryService:
    """Wrapper Redis avec repli en mémoire locale en cas d'indisponibilité."""

    def __init__(self,url:str, ttl_seconds:int):
        """Tente une connexion Redis (`PING`) ; bascule en mode mémoire si elle échoue."""
        self.url = url
        self.ttl_seconds = ttl_seconds
        self._client = None
        self._memory_store: Dict[str, List[Dict[str, str]]] = {}
        self._kv_store: Dict[str, str] = {}

        try:
            import importlib

            redis_module = importlib.import_module("redis")
            self._client = redis_module.from_url(url, decode_responses=True)
            self._client.ping()
            logger.bind(redis_url=url, ttl_seconds=ttl_seconds).info(
                "Redis connection established."
            )
        except Exception as exc:
            self._client = None
            logger.bind(redis_url=url, reason=str(exc)).warning(
                "Redis unavailable, falling back to in-memory storage."
            )

    def conversation_key(self, conversation_id: str) -> str:
        """Clé Redis pour la liste des messages d'une conversation."""
        return f"conversation:{conversation_id}:messages"

    def user_key(self, email: str) -> str:
        """Clé Redis pour le compte utilisateur associé à un email."""
        return f"user:{email}"

    def get_messages(self, conversation_id: str) -> List[Dict[str, str]]:
        """Retourne tout l'historique (rôle + contenu) d'une conversation."""
        if self._client:
            try:
                items = self._client.lrange(self.conversation_key(conversation_id), 0, -1)
                return [json.loads(item) for item in items]
            except Exception as exc:
                logger.bind(conversation_id=conversation_id, reason=str(exc)).warning(
                    "Redis read failed, falling back to in-memory store."
                )
                return self._memory_store.get(conversation_id, [])
        return self._memory_store.get(conversation_id, [])

    def append_message(self, conversation_id: str, role: str, content: str) -> None:
        """Ajoute un message (user/assistant) à l'historique et rafraîchit son expiration."""
        payload = {"role": role, "content": content}
        if self._client:
            try:
                key = self.conversation_key(conversation_id)
                self._client.rpush(key, json.dumps(payload))
                self._client.expire(key, self.ttl_seconds)
                return
            except Exception as exc:
                logger.bind(conversation_id=conversation_id, reason=str(exc)).warning(
                    "Redis write failed, falling back to in-memory store."
                )
        self._memory_store.setdefault(conversation_id, []).append(payload)

    def clear_messages(self, conversation_id: str) -> None:
        """Supprime définitivement l'historique d'une conversation."""
        if self._client:
            try:
                self._client.delete(self.conversation_key(conversation_id))
                return
            except Exception as exc:
                logger.bind(conversation_id=conversation_id, reason=str(exc)).warning(
                    "Redis delete failed, clearing in-memory store instead."
                )
        self._memory_store.pop(conversation_id, None)

    def get_value(self, key: str) -> Optional[str]:
        """Lit une valeur simple (utilisé pour les comptes utilisateurs et le cache de chat)."""
        if self._client:
            try:
                return self._client.get(key)
            except Exception as exc:
                logger.bind(key=key, reason=str(exc)).warning(
                    "Redis read failed, falling back to in-memory store."
                )
                return self._kv_store.get(key)
        return self._kv_store.get(key)

    def set_value(self, key: str, value: str, ttl: Optional[int] = None) -> None:
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
                    self._client.set(key, value)
                else:
                    expiry = ttl if ttl is not None else self.ttl_seconds
                    self._client.setex(key, expiry, value)
                return
            except Exception as exc:
                logger.bind(key=key, reason=str(exc)).warning(
                    "Redis write failed, falling back to in-memory store."
                )
        self._kv_store[key] = value

    @property
    def using_redis(self) -> bool:
        """True si la connexion Redis a réussi au démarrage (utilisé par `/health`)."""
        return self._client is not None