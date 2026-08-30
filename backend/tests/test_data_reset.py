import unittest

from app.memory.redis_memory import RedisMemoryService
from app.services.search_service import SearchService


class _DeleteResult:
    deleted_count = 7


class _FakeCollection:
    def __init__(self):
        self.filter = None

    def delete_many(self, filter_query):
        self.filter = filter_query
        return _DeleteResult()


class DataResetTests(unittest.IsolatedAsyncioTestCase):
    async def test_redis_reset_preserves_user_accounts(self):
        service = RedisMemoryService.__new__(RedisMemoryService)
        owner_scope = service._owner_scope("person@example.com")
        service._client = None
        service._memory_store = {
            f"conversation:{owner_scope}:one:messages": [{"role": "user", "content": "hello"}],
        }
        service._kv_store = {
            "user:person@example.com": "account",
            f"chat:{owner_scope}:conversation:question": "cached answer",
        }

        deleted = await service.clear_runtime_data()

        self.assertEqual(deleted, 2)
        self.assertEqual(service._memory_store, {})
        self.assertEqual(service._kv_store, {"user:person@example.com": "account"})

    async def test_redis_owner_reset_only_clears_that_owner(self):
        service = RedisMemoryService.__new__(RedisMemoryService)
        service._client = None
        alice_scope = service._owner_scope("alice@example.com")
        bob_scope = service._owner_scope("bob@example.com")
        service._memory_store = {
            f"conversation:{alice_scope}:one:messages": [{"role": "user", "content": "hello"}],
            f"conversation:{bob_scope}:one:messages": [{"role": "user", "content": "bonjour"}],
        }
        service._kv_store = {
            f"chat:{alice_scope}:thread:question": "cached answer",
            f"chat:{bob_scope}:thread:question": "cached answer",
        }

        deleted = await service.clear_runtime_data(owner_id="alice@example.com")

        self.assertEqual(deleted, 2)
        self.assertEqual(list(service._memory_store), [f"conversation:{bob_scope}:one:messages"])
        self.assertEqual(list(service._kv_store), [f"chat:{bob_scope}:thread:question"])

    async def test_mongodb_reset_keeps_collection_and_indexes(self):
        collection = _FakeCollection()
        service = SearchService.__new__(SearchService)
        service._collection = collection
        service.index_name = "documents"

        deleted = await service.clear_documents()

        self.assertEqual(deleted, 7)
        self.assertEqual(collection.filter, {})


if __name__ == "__main__":
    unittest.main()
