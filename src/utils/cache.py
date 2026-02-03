"""
Caching utilities for multi-cloud cost monitoring.

Provides Redis-based caching for dashboard and API responses.
Provider-level disk caching is handled directly in provider implementations.
"""

import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class CacheBackend(ABC):
    """Abstract base class for cache backends."""

    @abstractmethod
    def get(self, key: str) -> Any | None:
        """Get a value from the cache."""
        pass

    @abstractmethod
    def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """Set a value in the cache with optional TTL."""
        pass

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Delete a key from the cache."""
        pass

    @abstractmethod
    def clear(self) -> bool:
        """Clear all entries from the cache."""
        pass

    @abstractmethod
    def size(self) -> int:
        """Get the current size of the cache."""
        pass

    @abstractmethod
    def keys(self) -> list:
        """Get all keys in the cache."""
        pass


class RedisCache(CacheBackend):
    """Redis-based cache backend."""

    _redis: Any | None

    def __init__(
        self, redis_url: str | None = None, default_ttl: int = 1800, prefix: str = "cost-monitor:"
    ):
        """
        Initialize Redis cache.

        Args:
            redis_url: Redis connection URL (defaults to REDIS_URL env var)
            default_ttl: Default TTL in seconds
            prefix: Key prefix for namespacing
        """
        try:
            import redis.asyncio as redis
        except ImportError:
            raise ImportError("redis package required for Redis caching")

        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.default_ttl = default_ttl
        self.prefix = prefix

        try:
            # Initialize Redis connection
            if self.redis_url:
                self._redis = redis.from_url(self.redis_url, decode_responses=True)
                logger.info(f"Redis cache initialized with TTL: {default_ttl}s")
            else:
                self._redis = None
                logger.warning("No Redis URL provided, Redis cache disabled")
        except Exception as e:
            logger.error(f"Failed to initialize Redis cache: {e}")
            self._redis = None

    def _get_key(self, key: str) -> str:
        """Get prefixed key for namespacing."""
        return f"{self.prefix}{key}"

    def get(self, key: str) -> Any | None:
        """Get a value from the cache."""
        if not self._redis:
            return None

        try:
            import asyncio

            # Handle both sync and async contexts
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # We're in an async context, but this is a sync method
                    # This shouldn't happen in normal usage - use async methods instead
                    logger.warning("get() called in async context - use async variant instead")
                    return None
                else:
                    # Sync context
                    result = loop.run_until_complete(self._redis.get(self._get_key(key)))
            except RuntimeError:
                # No event loop running, create one
                result = asyncio.run(self._redis.get(self._get_key(key)))

            if result:
                return json.loads(result)
            return None
        except Exception as e:
            logger.warning(f"Error getting from Redis cache: {e}")
            return None

    def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """Set a value in the cache with optional TTL."""
        if not self._redis:
            return False

        try:
            import asyncio

            ttl = ttl or self.default_ttl
            serialized = json.dumps(value, default=str)

            # Handle both sync and async contexts
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    logger.warning("set() called in async context - use async variant instead")
                    return False
                else:
                    result = loop.run_until_complete(
                        self._redis.setex(self._get_key(key), ttl, serialized)
                    )
            except RuntimeError:
                result = asyncio.run(self._redis.setex(self._get_key(key), ttl, serialized))

            return bool(result)
        except Exception as e:
            logger.error(f"Error setting Redis cache: {e}")
            return False

    def delete(self, key: str) -> bool:
        """Delete a key from the cache."""
        if not self._redis:
            return False

        try:
            import asyncio

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    logger.warning("delete() called in async context - use async variant instead")
                    return False
                else:
                    result = loop.run_until_complete(self._redis.delete(self._get_key(key)))
            except RuntimeError:
                result = asyncio.run(self._redis.delete(self._get_key(key)))

            return bool(result)
        except Exception as e:
            logger.error(f"Error deleting from Redis cache: {e}")
            return False

    def clear(self) -> bool:
        """Clear all entries from the cache with our prefix."""
        if not self._redis:
            return False

        try:
            import asyncio

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    logger.warning("clear() called in async context - use async variant instead")
                    return False
                else:
                    keys = loop.run_until_complete(self._redis.keys(f"{self.prefix}*"))
                    if keys:
                        loop.run_until_complete(self._redis.delete(*keys))
            except RuntimeError:
                keys = asyncio.run(self._redis.keys(f"{self.prefix}*"))
                if keys:
                    asyncio.run(self._redis.delete(*keys))

            logger.info(f"Cleared {len(keys) if 'keys' in locals() else 0} keys from Redis cache")
            return True
        except Exception as e:
            logger.error(f"Error clearing Redis cache: {e}")
            return False

    def size(self) -> int:
        """Get the current size of the cache."""
        if not self._redis:
            return 0

        try:
            import asyncio

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    return 0
                else:
                    keys = loop.run_until_complete(self._redis.keys(f"{self.prefix}*"))
            except RuntimeError:
                keys = asyncio.run(self._redis.keys(f"{self.prefix}*"))

            return len(keys)
        except Exception as e:
            logger.warning(f"Error getting Redis cache size: {e}")
            return 0

    def keys(self) -> list:
        """Get all keys in the cache."""
        if not self._redis:
            return []

        try:
            import asyncio

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    return []
                else:
                    keys = loop.run_until_complete(self._redis.keys(f"{self.prefix}*"))
            except RuntimeError:
                keys = asyncio.run(self._redis.keys(f"{self.prefix}*"))

            # Remove prefix from keys
            return [key.replace(self.prefix, "", 1) for key in keys]
        except Exception as e:
            logger.warning(f"Error getting Redis cache keys: {e}")
            return []

    def stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        try:
            return {
                "type": "redis",
                "redis_url": self.redis_url,
                "prefix": self.prefix,
                "size": self.size(),
                "default_ttl": self.default_ttl,
                "connected": bool(self._redis),
            }
        except Exception as e:
            return {"type": "redis", "error": str(e)}
