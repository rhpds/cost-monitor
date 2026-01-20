"""
Caching utilities for multi-cloud cost monitoring.

Provides efficient caching mechanisms to reduce API calls to cloud providers,
improve performance, and minimize costs. Supports both memory and disk-based
caching with configurable TTL and size limits.
"""

import hashlib
import json
import logging
import os
import pickle
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Union

try:
    import diskcache as dc
    DISKCACHE_AVAILABLE = True
except ImportError:
    DISKCACHE_AVAILABLE = False

logger = logging.getLogger(__name__)


class CacheBackend(ABC):
    """Abstract base class for cache backends."""

    @abstractmethod
    def get(self, key: str) -> Optional[Any]:
        """Get a value from the cache."""
        pass

    @abstractmethod
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
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


class MemoryCache(CacheBackend):
    """In-memory cache backend with TTL support."""

    def __init__(self, max_size: int = 5000, default_ttl: int = 1800):
        """
        Initialize memory cache.

        Args:
            max_size: Maximum number of cache entries (increased from 1000 to 5000)
            default_ttl: Default TTL in seconds (reduced from 3600 to 1800 for fresher data)
        """
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._access_order = []  # Track access order for better LRU eviction

    def _cleanup_expired(self):
        """Remove expired entries from cache."""
        current_time = time.time()
        expired_keys = []

        for key, entry in self._cache.items():
            if current_time > entry['expires_at']:
                expired_keys.append(key)

        for key in expired_keys:
            del self._cache[key]

    def _evict_if_needed(self):
        """Evict least recently used entries if cache is full."""
        if len(self._cache) >= self.max_size:
            # Use LRU eviction - remove entries based on access order
            num_to_remove = max(1, self.max_size // 5)  # Remove 20% instead of 10%

            # Update access order to remove any keys that no longer exist
            self._access_order = [key for key in self._access_order if key in self._cache]

            # Remove least recently used entries
            keys_to_remove = self._access_order[:num_to_remove]
            for key in keys_to_remove:
                if key in self._cache:
                    del self._cache[key]
                self._access_order.remove(key)

    def get(self, key: str) -> Optional[Any]:
        """Get a value from the cache."""
        self._cleanup_expired()

        if key in self._cache:
            entry = self._cache[key]
            if time.time() <= entry['expires_at']:
                entry['accessed_at'] = time.time()

                # Update access order for LRU
                if key in self._access_order:
                    self._access_order.remove(key)
                self._access_order.append(key)

                return entry['value']
            else:
                del self._cache[key]
                if key in self._access_order:
                    self._access_order.remove(key)

        return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Set a value in the cache with optional TTL."""
        try:
            self._cleanup_expired()
            self._evict_if_needed()

            ttl = ttl or self.default_ttl
            current_time = time.time()

            self._cache[key] = {
                'value': value,
                'created_at': current_time,
                'accessed_at': current_time,
                'expires_at': current_time + ttl,
                'ttl': ttl
            }

            # Update access order for LRU
            if key in self._access_order:
                self._access_order.remove(key)
            self._access_order.append(key)

            return True
        except Exception as e:
            logger.error(f"Failed to set cache entry {key}: {e}")
            return False

    def delete(self, key: str) -> bool:
        """Delete a key from the cache."""
        if key in self._cache:
            del self._cache[key]
            return True
        return False

    def clear(self) -> bool:
        """Clear all entries from the cache."""
        self._cache.clear()
        return True

    def size(self) -> int:
        """Get the current size of the cache."""
        self._cleanup_expired()
        return len(self._cache)

    def keys(self) -> list:
        """Get all keys in the cache."""
        self._cleanup_expired()
        return list(self._cache.keys())

    def stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        self._cleanup_expired()
        return {
            'entries': len(self._cache),
            'max_size': self.max_size,
            'default_ttl': self.default_ttl
        }


class DiskCache(CacheBackend):
    """Disk-based cache backend using diskcache."""

    def __init__(self, directory: str = "/tmp/cost-monitor-cache",
                 max_size: int = 100_000_000,  # 100MB
                 default_ttl: int = 3600):
        """
        Initialize disk cache.

        Args:
            directory: Cache directory path
            max_size: Maximum cache size in bytes
            default_ttl: Default TTL in seconds
        """
        if not DISKCACHE_AVAILABLE:
            raise ImportError("diskcache is required for disk caching. Install with: pip install diskcache")

        self.directory = directory
        self.max_size = max_size
        self.default_ttl = default_ttl

        # Create directory if it doesn't exist
        Path(directory).mkdir(parents=True, exist_ok=True)

        # Initialize diskcache
        self._cache = dc.Cache(
            directory,
            size_limit=max_size
        )

    def get(self, key: str) -> Optional[Any]:
        """Get a value from the cache."""
        try:
            return self._cache.get(key)
        except Exception as e:
            logger.error(f"Failed to get cache entry {key}: {e}")
            return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Set a value in the cache with optional TTL."""
        try:
            ttl = ttl or self.default_ttl
            return self._cache.set(key, value, expire=ttl)
        except Exception as e:
            logger.error(f"Failed to set cache entry {key}: {e}")
            return False

    def delete(self, key: str) -> bool:
        """Delete a key from the cache."""
        try:
            return self._cache.delete(key)
        except Exception as e:
            logger.error(f"Failed to delete cache entry {key}: {e}")
            return False

    def clear(self) -> bool:
        """Clear all entries from the cache."""
        try:
            self._cache.clear()
            return True
        except Exception as e:
            logger.error(f"Failed to clear cache: {e}")
            return False

    def size(self) -> int:
        """Get the current size of the cache."""
        try:
            return len(self._cache)
        except Exception as e:
            logger.error(f"Failed to get cache size: {e}")
            return 0

    def keys(self) -> list:
        """Get all keys in the cache."""
        try:
            return list(self._cache)
        except Exception as e:
            logger.error(f"Failed to get cache keys: {e}")
            return []

    def stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        try:
            return {
                'entries': len(self._cache),
                'volume': self._cache.volume(),
                'max_size': self.max_size,
                'directory': self.directory,
                'default_ttl': self.default_ttl
            }
        except Exception as e:
            logger.error(f"Failed to get cache stats: {e}")
            return {}


class CacheManager:
    """High-level cache manager with multiple backends and strategies."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize cache manager from configuration.

        Args:
            config: Cache configuration dictionary
        """
        self.config = config
        self.enabled = config.get('enabled', True)

        if not self.enabled:
            self._backend = None
            return

        # Determine cache backend
        cache_type = config.get('type', 'memory').lower()
        default_ttl = config.get('ttl', 3600)

        if cache_type == 'disk':
            cache_dir = config.get('directory', '/tmp/cost-monitor-cache')
            max_size_str = config.get('max_size', '100MB')
            max_size = self._parse_size(max_size_str)

            self._backend = DiskCache(
                directory=cache_dir,
                max_size=max_size,
                default_ttl=default_ttl
            )
        else:
            max_entries = config.get('max_entries', 1000)
            self._backend = MemoryCache(
                max_size=max_entries,
                default_ttl=default_ttl
            )

        # Provider-specific TTL settings
        self.provider_ttls = {
            'aws': config.get('aws', {}).get('ttl', default_ttl),
            'azure': config.get('azure', {}).get('ttl', default_ttl),
            'gcp': config.get('gcp', {}).get('ttl', default_ttl)
        }

        logger.info(f"Cache initialized: {cache_type} backend, TTL: {default_ttl}s")

    def _parse_size(self, size_str: str) -> int:
        """Parse size string like '100MB' to bytes."""
        size_str = size_str.upper()
        if size_str.endswith('KB'):
            return int(size_str[:-2]) * 1024
        elif size_str.endswith('MB'):
            return int(size_str[:-2]) * 1024 * 1024
        elif size_str.endswith('GB'):
            return int(size_str[:-2]) * 1024 * 1024 * 1024
        else:
            return int(size_str)

    def _generate_cache_key(
        self,
        provider: str,
        operation: str,
        params: Dict[str, Any]
    ) -> str:
        """Generate a cache key for the given parameters."""
        # Create a deterministic key from parameters
        key_data = {
            'provider': provider,
            'operation': operation,
            'params': params
        }

        # Sort and serialize to ensure consistent keys
        key_str = json.dumps(key_data, sort_keys=True, default=str)

        # Hash to create shorter, fixed-length key
        return hashlib.sha256(key_str.encode()).hexdigest()[:32]

    def get(self, provider: str, operation: str, params: Dict[str, Any]) -> Optional[Any]:
        """Get cached data."""
        if not self.enabled or not self._backend:
            return None

        try:
            key = self._generate_cache_key(provider, operation, params)
            return self._backend.get(key)
        except Exception as e:
            logger.error(f"Cache get failed: {e}")
            return None

    def set(
        self,
        provider: str,
        operation: str,
        params: Dict[str, Any],
        value: Any,
        ttl: Optional[int] = None
    ) -> bool:
        """Set cached data."""
        if not self.enabled or not self._backend:
            return False

        try:
            key = self._generate_cache_key(provider, operation, params)

            # Use provider-specific TTL if not specified
            if ttl is None:
                ttl = self.provider_ttls.get(provider, self._backend.default_ttl)

            return self._backend.set(key, value, ttl)
        except Exception as e:
            logger.error(f"Cache set failed: {e}")
            return False

    def delete(self, provider: str, operation: str, params: Dict[str, Any]) -> bool:
        """Delete cached data."""
        if not self.enabled or not self._backend:
            return False

        try:
            key = self._generate_cache_key(provider, operation, params)
            return self._backend.delete(key)
        except Exception as e:
            logger.error(f"Cache delete failed: {e}")
            return False

    def clear_provider(self, provider: str) -> int:
        """Clear all cached data for a specific provider."""
        if not self.enabled or not self._backend:
            return 0

        try:
            keys_to_delete = []
            for key in self._backend.keys():
                # This is a simplified approach - in practice, you might want to
                # store provider info in the key more explicitly
                if provider in key:
                    keys_to_delete.append(key)

            for key in keys_to_delete:
                self._backend.delete(key)

            return len(keys_to_delete)
        except Exception as e:
            logger.error(f"Clear provider cache failed: {e}")
            return 0

    def clear_all(self) -> bool:
        """Clear all cached data."""
        if not self.enabled or not self._backend:
            return True

        try:
            return self._backend.clear()
        except Exception as e:
            logger.error(f"Clear cache failed: {e}")
            return False

    def stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        if not self.enabled or not self._backend:
            return {'enabled': False}

        try:
            stats = self._backend.stats()
            stats['enabled'] = True
            stats['provider_ttls'] = self.provider_ttls
            return stats
        except Exception as e:
            logger.error(f"Cache stats failed: {e}")
            return {'enabled': True, 'error': str(e)}


class CacheDecorator:
    """Decorator for caching function results."""

    def __init__(self, cache_manager: CacheManager, provider: str, ttl: Optional[int] = None):
        """
        Initialize cache decorator.

        Args:
            cache_manager: Cache manager instance
            provider: Provider name
            ttl: Optional TTL override
        """
        self.cache_manager = cache_manager
        self.provider = provider
        self.ttl = ttl

    def __call__(self, func):
        """Decorator implementation."""
        def wrapper(*args, **kwargs):
            # Generate cache parameters from function arguments
            params = {
                'args': args,
                'kwargs': kwargs,
                'function': func.__name__
            }

            # Try to get from cache first
            cached_result = self.cache_manager.get(
                self.provider,
                func.__name__,
                params
            )

            if cached_result is not None:
                logger.debug(f"Cache hit for {self.provider}:{func.__name__}")
                return cached_result

            # Execute function and cache result
            logger.debug(f"Cache miss for {self.provider}:{func.__name__}")
            result = func(*args, **kwargs)

            # Cache the result
            self.cache_manager.set(
                self.provider,
                func.__name__,
                params,
                result,
                self.ttl
            )

            return result

        return wrapper


def cache_cost_data(cache_manager: CacheManager, provider: str, ttl: Optional[int] = None):
    """Decorator for caching cost data operations."""
    return CacheDecorator(cache_manager, provider, ttl)


class SmartCacheStrategy:
    """Smart caching strategy that adjusts TTL based on data characteristics."""

    def __init__(self, cache_manager: CacheManager):
        self.cache_manager = cache_manager

    def calculate_ttl(
        self,
        provider: str,
        data_type: str,
        time_range_days: int,
        data_age_hours: int = 0
    ) -> int:
        """
        Calculate optimal TTL based on data characteristics.

        Args:
            provider: Cloud provider name
            data_type: Type of data (daily_costs, monthly_costs, service_costs, etc.)
            time_range_days: Number of days in the queried range
            data_age_hours: How many hours old the data endpoint is

        Returns:
            Optimal TTL in seconds
        """

        # PERMANENT CACHING: Historical data (>48 hours old) should never expire
        if data_age_hours >= 48:
            # Set to 10 years (effectively permanent for cost data)
            logger.info(f"💾 {provider.upper()}: Setting permanent cache for {data_age_hours}h old data")
            return 315360000  # 10 years in seconds

        # Recent data (24-48 hours) gets extended cache but still expires
        elif data_age_hours >= 24:
            logger.info(f"💾 {provider.upper()}: Extended cache for {data_age_hours}h old data")
            return 86400 * 7  # 7 days for data that's 1-2 days old

        base_ttl = self.cache_manager.provider_ttls.get(provider, 3600)

        # For very recent data (< 24 hours), use dynamic TTL
        if data_type == 'daily_costs':
            # Recent daily costs update several times per day
            ttl_factor = 0.5 if data_age_hours < 12 else 1.0
        elif data_type == 'monthly_costs':
            # Monthly aggregations are more stable
            ttl_factor = 2.0
        elif data_type == 'service_costs':
            # Service breakdowns are fairly stable
            ttl_factor = 1.5
        else:
            ttl_factor = 1.0

        # Adjust based on time range for recent data
        if time_range_days > 30:
            # Historical data changes less frequently
            ttl_factor *= 2.0
        elif time_range_days <= 1:
            # Recent data changes more frequently
            ttl_factor *= 0.5

        # Provider-specific adjustments
        provider_factors = {
            'aws': 1.0,      # AWS updates 3-4 times daily
            'azure': 1.2,    # Azure updates hourly
            'gcp': 1.1       # GCP updates hourly
        }

        ttl_factor *= provider_factors.get(provider, 1.0)

        calculated_ttl = int(base_ttl * ttl_factor)
        logger.debug(f"💾 {provider.upper()}: Recent data TTL={calculated_ttl}s for {data_age_hours}h old data")
        return calculated_ttl


# Global cache manager instance
_global_cache_manager = None


def get_cache_manager(config: Optional[Dict[str, Any]] = None) -> CacheManager:
    """Get global cache manager instance."""
    global _global_cache_manager

    if _global_cache_manager is None and config:
        _global_cache_manager = CacheManager(config)

    return _global_cache_manager


def initialize_cache(config: Dict[str, Any]) -> CacheManager:
    """Initialize global cache manager."""
    global _global_cache_manager
    _global_cache_manager = CacheManager(config)
    return _global_cache_manager