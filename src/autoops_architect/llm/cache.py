"""LLM response caching to reduce costs and improve latency."""

import hashlib
import json
import os
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field


class CacheConfig(BaseModel):
    """Configuration for LLM response caching."""

    enabled: bool = Field(
        default=False,
        description="Whether caching is enabled"
    )

    backend: str = Field(
        default="memory",
        description="Cache backend: memory, filesystem, or redis"
    )

    ttl_seconds: int = Field(
        default=3600,
        ge=60,
        le=86400 * 7,
        description="Time-to-live for cache entries in seconds (1 min to 7 days)"
    )

    max_size: int = Field(
        default=1000,
        ge=10,
        le=100000,
        description="Maximum number of cached entries"
    )

    cache_dir: Optional[str] = Field(
        default=None,
        description="Directory for filesystem cache (defaults to ~/.cache/autoops-architect)"
    )

    redis_url: Optional[str] = Field(
        default=None,
        description="Redis URL for redis backend (e.g., redis://localhost:6379/0)"
    )


class CacheEntry(BaseModel):
    """A cached response entry."""

    key: str = Field(..., description="Cache key")
    value: dict[str, Any] = Field(..., description="Cached response")
    timestamp: float = Field(..., description="Unix timestamp when cached")
    ttl: int = Field(..., description="Time-to-live in seconds")

    def is_expired(self) -> bool:
        """Check if this cache entry has expired."""
        return (time.time() - self.timestamp) > self.ttl


class CacheBackend(ABC):
    """Abstract base class for cache backends."""

    def __init__(self, config: CacheConfig) -> None:
        """Initialize cache backend with configuration."""
        self.config = config

    @abstractmethod
    async def get(self, key: str) -> Optional[dict[str, Any]]:
        """
        Retrieve a value from cache.

        Args:
            key: Cache key.

        Returns:
            Cached value if found and not expired, None otherwise.
        """
        pass

    @abstractmethod
    async def set(self, key: str, value: dict[str, Any], ttl: Optional[int] = None) -> None:
        """
        Store a value in cache.

        Args:
            key: Cache key.
            value: Value to cache.
            ttl: Optional time-to-live override in seconds.
        """
        pass

    @abstractmethod
    async def delete(self, key: str) -> None:
        """
        Delete a value from cache.

        Args:
            key: Cache key.
        """
        pass

    @abstractmethod
    async def clear(self) -> None:
        """Clear all cache entries."""
        pass

    @abstractmethod
    async def size(self) -> int:
        """Get the number of entries in cache."""
        pass


class MemoryCacheBackend(CacheBackend):
    """In-memory cache backend using a simple dictionary."""

    def __init__(self, config: CacheConfig) -> None:
        super().__init__(config)
        self._cache: dict[str, CacheEntry] = {}

    async def get(self, key: str) -> Optional[dict[str, Any]]:
        """Retrieve from in-memory cache."""
        entry = self._cache.get(key)
        if entry is None:
            return None

        if entry.is_expired():
            await self.delete(key)
            return None

        return entry.value

    async def set(self, key: str, value: dict[str, Any], ttl: Optional[int] = None) -> None:
        """Store in in-memory cache with LRU eviction."""
        # Evict oldest entries if at max size
        if len(self._cache) >= self.config.max_size:
            # Remove oldest entry (by timestamp)
            oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k].timestamp)
            del self._cache[oldest_key]

        entry = CacheEntry(
            key=key,
            value=value,
            timestamp=time.time(),
            ttl=ttl or self.config.ttl_seconds,
        )
        self._cache[key] = entry

    async def delete(self, key: str) -> None:
        """Delete from in-memory cache."""
        self._cache.pop(key, None)

    async def clear(self) -> None:
        """Clear all entries."""
        self._cache.clear()

    async def size(self) -> int:
        """Get cache size."""
        return len(self._cache)


class FilesystemCacheBackend(CacheBackend):
    """Filesystem-based cache backend."""

    def __init__(self, config: CacheConfig) -> None:
        super().__init__(config)
        cache_dir = config.cache_dir or os.path.expanduser("~/.cache/autoops-architect/llm")
        self.cache_path = Path(cache_dir)
        self.cache_path.mkdir(parents=True, exist_ok=True)

    def _get_file_path(self, key: str) -> Path:
        """Get the file path for a cache key."""
        return self.cache_path / f"{key}.json"

    async def get(self, key: str) -> Optional[dict[str, Any]]:
        """Retrieve from filesystem cache."""
        file_path = self._get_file_path(key)
        if not file_path.exists():
            return None

        try:
            with open(file_path, "r") as f:
                entry_data = json.load(f)
                entry = CacheEntry(**entry_data)

            if entry.is_expired():
                await self.delete(key)
                return None

            return entry.value
        except (json.JSONDecodeError, OSError, KeyError):
            # Corrupted cache file, delete it
            await self.delete(key)
            return None

    async def set(self, key: str, value: dict[str, Any], ttl: Optional[int] = None) -> None:
        """Store in filesystem cache."""
        # Check cache size and evict if needed
        current_size = await self.size()
        if current_size >= self.config.max_size:
            await self._evict_oldest()

        entry = CacheEntry(
            key=key,
            value=value,
            timestamp=time.time(),
            ttl=ttl or self.config.ttl_seconds,
        )

        file_path = self._get_file_path(key)
        try:
            with open(file_path, "w") as f:
                json.dump(entry.model_dump(), f)
        except OSError:
            # Ignore write errors
            pass

    async def delete(self, key: str) -> None:
        """Delete from filesystem cache."""
        file_path = self._get_file_path(key)
        try:
            file_path.unlink(missing_ok=True)
        except OSError:
            pass

    async def clear(self) -> None:
        """Clear all cache files."""
        for file_path in self.cache_path.glob("*.json"):
            try:
                file_path.unlink()
            except OSError:
                pass

    async def size(self) -> int:
        """Get number of cache files."""
        return len(list(self.cache_path.glob("*.json")))

    async def _evict_oldest(self) -> None:
        """Evict the oldest cache entry."""
        oldest_file: Optional[Path] = None
        oldest_time = float("inf")

        for file_path in self.cache_path.glob("*.json"):
            try:
                mtime = file_path.stat().st_mtime
                if mtime < oldest_time:
                    oldest_time = mtime
                    oldest_file = file_path
            except OSError:
                continue

        if oldest_file:
            await self.delete(oldest_file.stem)


class RedisCacheBackend(CacheBackend):
    """Redis-based cache backend for distributed caching."""

    def __init__(self, config: CacheConfig) -> None:
        super().__init__(config)
        self._redis: Optional[Any] = None

    def _get_redis(self) -> Any:
        """Lazy initialization of Redis client."""
        if self._redis is None:
            try:
                import redis.asyncio as redis
            except ImportError:
                raise ImportError(
                    "Redis package not installed. "
                    "Install with: pip install redis"
                )

            redis_url = self.config.redis_url or os.getenv(
                "REDIS_URL", "redis://localhost:6379/0"
            )
            self._redis = redis.from_url(redis_url, decode_responses=True)

        return self._redis

    async def get(self, key: str) -> Optional[dict[str, Any]]:
        """Retrieve from Redis cache."""
        redis_client = self._get_redis()
        try:
            data = await redis_client.get(f"autoops:llm:{key}")
            if data is None:
                return None
            return json.loads(data)
        except Exception:
            return None

    async def set(self, key: str, value: dict[str, Any], ttl: Optional[int] = None) -> None:
        """Store in Redis cache with TTL."""
        redis_client = self._get_redis()
        try:
            ttl_seconds = ttl or self.config.ttl_seconds
            await redis_client.setex(
                f"autoops:llm:{key}",
                ttl_seconds,
                json.dumps(value),
            )
        except Exception:
            # Ignore cache write errors
            pass

    async def delete(self, key: str) -> None:
        """Delete from Redis cache."""
        redis_client = self._get_redis()
        try:
            await redis_client.delete(f"autoops:llm:{key}")
        except Exception:
            pass

    async def clear(self) -> None:
        """Clear all LLM cache entries in Redis."""
        redis_client = self._get_redis()
        try:
            keys = await redis_client.keys("autoops:llm:*")
            if keys:
                await redis_client.delete(*keys)
        except Exception:
            pass

    async def size(self) -> int:
        """Get number of cached entries."""
        redis_client = self._get_redis()
        try:
            keys = await redis_client.keys("autoops:llm:*")
            return len(keys)
        except Exception:
            return 0


def get_cache_backend(config: CacheConfig) -> CacheBackend:
    """
    Factory function to create a cache backend.

    Args:
        config: Cache configuration.

    Returns:
        Cache backend instance.

    Raises:
        ValueError: If backend type is not supported.
    """
    if config.backend == "memory":
        return MemoryCacheBackend(config)
    elif config.backend == "filesystem":
        return FilesystemCacheBackend(config)
    elif config.backend == "redis":
        return RedisCacheBackend(config)
    else:
        raise ValueError(f"Unsupported cache backend: {config.backend}")


def compute_cache_key(
    messages: list[Any],
    model: str,
    temperature: float,
    max_tokens: int,
    **kwargs: Any,
) -> str:
    """
    Compute a cache key from request parameters.

    Uses SHA256 hash of normalized parameters to create a deterministic key.

    Args:
        messages: List of conversation messages.
        model: Model identifier.
        temperature: Sampling temperature.
        max_tokens: Maximum tokens.
        **kwargs: Additional parameters to include in key.

    Returns:
        Cache key as hex string.
    """
    # Normalize messages to dictionaries for hashing
    messages_data = []
    for msg in messages:
        if hasattr(msg, "model_dump"):
            messages_data.append(msg.model_dump())
        elif isinstance(msg, dict):
            messages_data.append(msg)
        else:
            messages_data.append({"role": "user", "content": str(msg)})

    # Create deterministic representation
    key_data = {
        "messages": messages_data,
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "kwargs": {k: v for k, v in sorted(kwargs.items()) if k != "force_refresh"},
    }

    # Hash the JSON representation
    key_json = json.dumps(key_data, sort_keys=True)
    key_hash = hashlib.sha256(key_json.encode()).hexdigest()

    return key_hash

