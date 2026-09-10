"""Unit tests for the LRU cache strategy."""

import threading

import pytest

from mellea_skills_compiler.toolkit.cache_strategy import LRUCache, hash_key


class TestHashKey:
    """Tests for the hash_key utility function."""

    def test_hash_key_consistent(self):
        """Same input always produces same hash."""
        key1 = hash_key("test_string")
        key2 = hash_key("test_string")
        assert key1 == key2

    def test_hash_key_different(self):
        """Different inputs produce different hashes."""
        key1 = hash_key("string1")
        key2 = hash_key("string2")
        assert key1 != key2

    def test_hash_key_multiple_parts(self):
        """Multiple parts are concatenated and hashed."""
        key1 = hash_key("part1", "part2")
        key2 = hash_key("part1part2")
        assert key1 == key2

    def test_hash_key_empty(self):
        """Empty input produces a valid hash."""
        key = hash_key("")
        assert isinstance(key, str)
        assert len(key) == 64  # SHA256 hex digest is 64 chars


class TestLRUCache:
    """Tests for the LRUCache class."""

    def test_get_set_basic(self):
        """Basic get/set operations work."""
        cache = LRUCache(maxsize=2)
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_get_missing_returns_none(self):
        """Getting a missing key returns None."""
        cache = LRUCache(maxsize=2)
        assert cache.get("missing") is None

    def test_eviction_on_overflow(self):
        """Oldest entry is evicted when maxsize is reached."""
        cache = LRUCache(maxsize=2)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")  # Should evict key1
        assert cache.get("key1") is None
        assert cache.get("key2") == "value2"
        assert cache.get("key3") == "value3"

    def test_get_does_not_promote(self):
        """Reading a key does not promote it (no move-to-end on get)."""
        cache = LRUCache(maxsize=2)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        _ = cache.get("key1")  # Read doesn't promote
        cache.set("key3", "value3")  # Should evict key1 (oldest by insertion order)
        assert cache.get("key1") is None  # key1 was evicted
        assert cache.get("key2") == "value2"
        assert cache.get("key3") == "value3"

    def test_lru_promotion_on_set(self):
        """Re-setting an existing key promotes it to most recently used."""
        cache = LRUCache(maxsize=2)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key1", "updated1")  # Promote key1
        cache.set("key3", "value3")  # Should evict key2, not key1
        assert cache.get("key1") == "updated1"
        assert cache.get("key2") is None
        assert cache.get("key3") == "value3"

    def test_thread_safety_concurrent_sets(self):
        """Concurrent sets don't corrupt cache state."""
        cache = LRUCache(maxsize=100)
        errors = []

        def worker(offset: int):
            try:
                for i in range(50):
                    key = f"key_{offset}_{i}"
                    cache.set(key, f"value_{offset}_{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors during concurrent sets: {errors}"
        # All 500 keys should be present (or evicted if maxsize was smaller)
        assert len(cache._cache) <= cache.maxsize

    def test_maxsize_one(self):
        """Cache with maxsize=1 evicts on every new insertion."""
        cache = LRUCache(maxsize=1)
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"
        cache.set("key2", "value2")
        assert cache.get("key1") is None
        assert cache.get("key2") == "value2"
