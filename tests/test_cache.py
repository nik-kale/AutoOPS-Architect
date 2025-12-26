"""Tests for LLM response caching."""

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from autoops_architect.llm.base import LLMConfig, LLMMessage, LLMProvider, LLMResponse
from autoops_architect.llm.cache import (
    CacheConfig,
    CacheEntry,
    FilesystemCacheBackend,
    MemoryCacheBackend,
    compute_cache_key,
    get_cache_backend,
)
from autoops_architect.llm.cached_client import CachedLLMClient
from autoops_architect.llm.providers import MockLLMClient


class TestCacheEntry:
    """Test CacheEntry model."""

    def test_cache_entry_not_expired(self) -> None:
        """Test that a recent cache entry is not expired."""
        import time

        entry = CacheEntry(
            key="test-key",
            value={"result": "test"},
            timestamp=time.time(),
            ttl=3600,
        )
        assert not entry.is_expired()

    def test_cache_entry_expired(self) -> None:
        """Test that an old cache entry is expired."""
        import time

        entry = CacheEntry(
            key="test-key",
            value={"result": "test"},
            timestamp=time.time() - 7200,  # 2 hours ago
            ttl=3600,  # 1 hour TTL
        )
        assert entry.is_expired()


class TestMemoryCacheBackend:
    """Test MemoryCacheBackend."""

    @pytest.fixture
    def cache(self) -> MemoryCacheBackend:
        """Create a memory cache backend."""
        config = CacheConfig(enabled=True, backend="memory", max_size=10)
        return MemoryCacheBackend(config)

    async def test_get_miss(self, cache: MemoryCacheBackend) -> None:
        """Test cache miss returns None."""
        result = await cache.get("nonexistent-key")
        assert result is None

    async def test_set_and_get(self, cache: MemoryCacheBackend) -> None:
        """Test storing and retrieving a value."""
        test_value = {"result": "test", "count": 42}
        await cache.set("test-key", test_value)

        result = await cache.get("test-key")
        assert result == test_value

    async def test_delete(self, cache: MemoryCacheBackend) -> None:
        """Test deleting a value."""
        await cache.set("test-key", {"result": "test"})
        await cache.delete("test-key")

        result = await cache.get("test-key")
        assert result is None

    async def test_clear(self, cache: MemoryCacheBackend) -> None:
        """Test clearing all values."""
        await cache.set("key1", {"value": 1})
        await cache.set("key2", {"value": 2})

        await cache.clear()

        assert await cache.size() == 0
        assert await cache.get("key1") is None
        assert await cache.get("key2") is None

    async def test_size_limit(self, cache: MemoryCacheBackend) -> None:
        """Test that cache evicts old entries when full."""
        # Fill cache to max_size
        for i in range(10):
            await cache.set(f"key-{i}", {"value": i})

        assert await cache.size() == 10

        # Add one more - should evict oldest
        await cache.set("key-10", {"value": 10})

        assert await cache.size() == 10
        # First key should be evicted
        assert await cache.get("key-0") is None
        # New key should exist
        assert await cache.get("key-10") == {"value": 10}

    async def test_expired_entry(self, cache: MemoryCacheBackend) -> None:
        """Test that expired entries are not returned."""
        import time

        # Manually create an expired entry
        cache._cache["expired-key"] = CacheEntry(
            key="expired-key",
            value={"result": "old"},
            timestamp=time.time() - 7200,
            ttl=3600,
        )

        result = await cache.get("expired-key")
        assert result is None
        # Should also be deleted
        assert "expired-key" not in cache._cache


class TestFilesystemCacheBackend:
    """Test FilesystemCacheBackend."""

    @pytest.fixture
    def cache(self) -> FilesystemCacheBackend:
        """Create a filesystem cache backend with temp directory."""
        temp_dir = tempfile.mkdtemp()
        config = CacheConfig(
            enabled=True,
            backend="filesystem",
            cache_dir=temp_dir,
            max_size=5,
        )
        return FilesystemCacheBackend(config)

    async def test_set_and_get(self, cache: FilesystemCacheBackend) -> None:
        """Test storing and retrieving from filesystem."""
        test_value = {"result": "filesystem-test", "count": 99}
        await cache.set("fs-key", test_value)

        result = await cache.get("fs-key")
        assert result == test_value

        # Verify file exists
        file_path = cache._get_file_path("fs-key")
        assert file_path.exists()

    async def test_expired_file(self, cache: FilesystemCacheBackend) -> None:
        """Test that expired files are not returned."""
        import time

        # Create an expired entry file manually
        file_path = cache._get_file_path("expired-fs-key")
        expired_entry = CacheEntry(
            key="expired-fs-key",
            value={"result": "old"},
            timestamp=time.time() - 7200,
            ttl=3600,
        )
        with open(file_path, "w") as f:
            json.dump(expired_entry.model_dump(), f)

        result = await cache.get("expired-fs-key")
        assert result is None
        # File should be deleted
        assert not file_path.exists()

    async def test_clear(self, cache: FilesystemCacheBackend) -> None:
        """Test clearing all cache files."""
        await cache.set("key1", {"value": 1})
        await cache.set("key2", {"value": 2})

        await cache.clear()

        assert await cache.size() == 0
        assert not list(cache.cache_path.glob("*.json"))


class TestComputeCacheKey:
    """Test cache key computation."""

    def test_same_inputs_same_key(self) -> None:
        """Test that identical inputs produce the same key."""
        messages1 = [LLMMessage(role="user", content="Hello")]
        messages2 = [LLMMessage(role="user", content="Hello")]

        key1 = compute_cache_key(messages1, "gpt-4", 0.7, 1000)
        key2 = compute_cache_key(messages2, "gpt-4", 0.7, 1000)

        assert key1 == key2

    def test_different_messages_different_key(self) -> None:
        """Test that different messages produce different keys."""
        messages1 = [LLMMessage(role="user", content="Hello")]
        messages2 = [LLMMessage(role="user", content="Goodbye")]

        key1 = compute_cache_key(messages1, "gpt-4", 0.7, 1000)
        key2 = compute_cache_key(messages2, "gpt-4", 0.7, 1000)

        assert key1 != key2

    def test_different_params_different_key(self) -> None:
        """Test that different parameters produce different keys."""
        messages = [LLMMessage(role="user", content="Hello")]

        key1 = compute_cache_key(messages, "gpt-4", 0.7, 1000)
        key2 = compute_cache_key(messages, "gpt-4", 0.9, 1000)  # Different temp
        key3 = compute_cache_key(messages, "gpt-3.5-turbo", 0.7, 1000)  # Different model

        assert key1 != key2
        assert key1 != key3
        assert key2 != key3

    def test_force_refresh_not_in_key(self) -> None:
        """Test that force_refresh doesn't affect cache key."""
        messages = [LLMMessage(role="user", content="Hello")]

        key1 = compute_cache_key(messages, "gpt-4", 0.7, 1000, force_refresh=False)
        key2 = compute_cache_key(messages, "gpt-4", 0.7, 1000, force_refresh=True)

        assert key1 == key2


class TestCachedLLMClient:
    """Test CachedLLMClient wrapper."""

    @pytest.fixture
    def mock_client(self) -> MockLLMClient:
        """Create a mock LLM client."""
        config = LLMConfig(provider=LLMProvider.MOCK)
        return MockLLMClient(
            config,
            responses=["First response", "Second response", "Third response"],
            json_responses=[{"result": "first"}, {"result": "second"}],
        )

    @pytest.fixture
    def cached_client(self, mock_client: MockLLMClient) -> CachedLLMClient:
        """Create a cached LLM client with memory backend."""
        cache_config = CacheConfig(enabled=True, backend="memory", ttl_seconds=3600)
        return CachedLLMClient(mock_client, cache_config)

    async def test_cache_miss_calls_underlying(
        self, cached_client: CachedLLMClient, mock_client: MockLLMClient
    ) -> None:
        """Test that cache miss calls the underlying client."""
        messages = [LLMMessage(role="user", content="Test message")]

        response = await cached_client.complete(messages)

        assert response.content == "First response"
        assert len(mock_client.call_history) == 1

    async def test_cache_hit_skips_underlying(
        self, cached_client: CachedLLMClient, mock_client: MockLLMClient
    ) -> None:
        """Test that cache hit doesn't call the underlying client."""
        messages = [LLMMessage(role="user", content="Test message")]

        # First call - cache miss
        response1 = await cached_client.complete(messages)
        assert response1.content == "First response"
        assert len(mock_client.call_history) == 1

        # Second call - cache hit
        response2 = await cached_client.complete(messages)
        assert response2.content == "First response"  # Same response
        assert len(mock_client.call_history) == 1  # No additional call

    async def test_force_refresh_bypasses_cache(
        self, cached_client: CachedLLMClient, mock_client: MockLLMClient
    ) -> None:
        """Test that force_refresh bypasses cache."""
        messages = [LLMMessage(role="user", content="Test message")]

        # First call
        response1 = await cached_client.complete(messages)
        assert response1.content == "First response"

        # Second call with force_refresh
        response2 = await cached_client.complete(messages, force_refresh=True)
        assert response2.content == "Second response"  # New response
        assert len(mock_client.call_history) == 2

    async def test_complete_json_caching(
        self, cached_client: CachedLLMClient, mock_client: MockLLMClient
    ) -> None:
        """Test that complete_json is also cached."""
        messages = [LLMMessage(role="user", content="Generate JSON")]

        # First call - cache miss
        result1 = await cached_client.complete_json(messages)
        assert result1 == {"result": "first"}
        assert len(mock_client.call_history) == 1

        # Second call - cache hit
        result2 = await cached_client.complete_json(messages)
        assert result2 == {"result": "first"}  # Same result
        assert len(mock_client.call_history) == 1  # No additional call

    async def test_cache_stats(self, cached_client: CachedLLMClient) -> None:
        """Test cache statistics tracking."""
        messages = [LLMMessage(role="user", content="Test")]

        # No requests yet
        stats = cached_client.get_cache_stats()
        assert stats["cache_hits"] == 0
        assert stats["cache_misses"] == 0
        assert stats["hit_rate"] == 0.0

        # First call - miss
        await cached_client.complete(messages)
        stats = cached_client.get_cache_stats()
        assert stats["cache_misses"] == 1
        assert stats["hit_rate"] == 0.0

        # Second call - hit
        await cached_client.complete(messages)
        stats = cached_client.get_cache_stats()
        assert stats["cache_hits"] == 1
        assert stats["cache_misses"] == 1
        assert stats["hit_rate"] == 0.5

        # Third call - hit
        await cached_client.complete(messages)
        stats = cached_client.get_cache_stats()
        assert stats["cache_hits"] == 2
        assert stats["cache_misses"] == 1
        assert stats["hit_rate"] == pytest.approx(0.666, rel=0.01)

    async def test_clear_cache(
        self, cached_client: CachedLLMClient, mock_client: MockLLMClient
    ) -> None:
        """Test clearing the cache."""
        messages = [LLMMessage(role="user", content="Test")]

        # Cache a response
        await cached_client.complete(messages)
        await cached_client.complete(messages)  # Hit
        assert cached_client.cache_hits == 1

        # Clear cache
        await cached_client.clear_cache()

        # Next call should miss
        await cached_client.complete(messages)
        assert cached_client.cache_hits == 1  # Still 1
        assert cached_client.cache_misses == 2  # Increased

    async def test_disabled_cache(self, mock_client: MockLLMClient) -> None:
        """Test that disabled cache always calls underlying client."""
        cache_config = CacheConfig(enabled=False)
        cached_client = CachedLLMClient(mock_client, cache_config)

        messages = [LLMMessage(role="user", content="Test")]

        # Multiple calls should all hit the underlying client
        await cached_client.complete(messages)
        await cached_client.complete(messages)
        await cached_client.complete(messages)

        assert len(mock_client.call_history) == 3


class TestGetCacheBackend:
    """Test get_cache_backend factory."""

    def test_get_memory_backend(self) -> None:
        """Test creating memory backend."""
        config = CacheConfig(enabled=True, backend="memory")
        backend = get_cache_backend(config)
        assert isinstance(backend, MemoryCacheBackend)

    def test_get_filesystem_backend(self) -> None:
        """Test creating filesystem backend."""
        config = CacheConfig(enabled=True, backend="filesystem")
        backend = get_cache_backend(config)
        assert isinstance(backend, FilesystemCacheBackend)

    def test_invalid_backend(self) -> None:
        """Test that invalid backend raises ValueError."""
        config = CacheConfig(enabled=True, backend="invalid")
        with pytest.raises(ValueError, match="Unsupported cache backend"):
            get_cache_backend(config)


class TestArchitectCacheIntegration:
    """Test cache integration with Architect planner."""

    async def test_planner_with_cache_enabled(self) -> None:
        """Test that planner uses cached client when configured."""
        from autoops_architect.models.goal import Environment, Goal
        from autoops_architect.planner.architect import Architect, PlannerConfig

        cache_config = CacheConfig(enabled=True, backend="memory")
        planner_config = PlannerConfig(cache_config=cache_config)
        architect = Architect(config=planner_config)

        # Check that the LLM client is wrapped with caching
        assert isinstance(architect.llm_client, CachedLLMClient)

    async def test_planner_without_cache(self) -> None:
        """Test that planner doesn't use cache when not configured."""
        from autoops_architect.planner.architect import Architect, PlannerConfig

        planner_config = PlannerConfig()
        architect = Architect(config=planner_config)

        # Check that the LLM client is not wrapped (it's the base client)
        assert not isinstance(architect.llm_client, CachedLLMClient)

