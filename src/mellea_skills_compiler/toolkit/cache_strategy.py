"""LRU caching strategy for reusable hooks and services."""

import hashlib
import threading
from collections import OrderedDict
from typing import Any, Optional


def hash_key(*parts: str) -> str:
    """Compute SHA256 hash of concatenated string parts for use in cache keys."""
    content = "".join(parts).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


class LRUCache:
    """Thread-safe LRU cache with configurable maximum size.

    When the cache reaches `maxsize`, the least-recently-used (oldest) entry
    is evicted on the next insertion. Accessing an existing key promotes it
    to the end (most recently used).
    """

    def __init__(self, maxsize: int = 512):
        """Initialize LRU cache.

        Args:
            maxsize: Maximum number of entries before eviction begins.
        """
        self.maxsize = maxsize
        self._cache: OrderedDict[Any, Any] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: Any) -> Optional[Any]:
        """Get a value from the cache by key.

        Returns None if not found.
        """
        with self._lock:
            return self._cache.get(key)

    def set(self, key: Any, value: Any) -> None:
        """Set a key-value pair in the cache.

        If the key already exists, it is moved to the end (marked most recently used).
        If the cache is at capacity, the least recently used (oldest) entry is removed.
        """
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            else:
                if len(self._cache) >= self.maxsize:
                    self._cache.popitem(last=False)
            self._cache[key] = value
