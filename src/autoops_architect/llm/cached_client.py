"""Cached LLM client wrapper for transparent response caching."""

from typing import Any, Optional

from autoops_architect.llm.base import LLMClient, LLMConfig, LLMMessage, LLMResponse
from autoops_architect.llm.cache import (
    CacheBackend,
    CacheConfig,
    compute_cache_key,
    get_cache_backend,
)


class CachedLLMClient(LLMClient):
    """
    LLM client wrapper that adds transparent response caching.

    This wrapper can be used with any LLM client to add caching without
    modifying the underlying client implementation.

    Cache hits avoid expensive LLM API calls, reducing costs and latency.

    Example:
        >>> from autoops_architect.llm import get_llm_client
        >>> from autoops_architect.llm.cache import CacheConfig
        >>>
        >>> # Create base client
        >>> base_client = get_llm_client()
        >>>
        >>> # Wrap with caching
        >>> cache_config = CacheConfig(enabled=True, backend="memory", ttl_seconds=3600)
        >>> cached_client = CachedLLMClient(base_client, cache_config)
        >>>
        >>> # First call hits LLM
        >>> response1 = await cached_client.complete([
        ...     LLMMessage(role="user", content="What is 2+2?")
        ... ])
        >>>
        >>> # Second identical call returns cached response instantly
        >>> response2 = await cached_client.complete([
        ...     LLMMessage(role="user", content="What is 2+2?")
        ... ])
        >>>
        >>> # Force refresh to bypass cache
        >>> response3 = await cached_client.complete(
        ...     [LLMMessage(role="user", content="What is 2+2?")],
        ...     force_refresh=True
        ... )
    """

    def __init__(
        self,
        client: LLMClient,
        cache_config: Optional[CacheConfig] = None,
        cache_backend: Optional[CacheBackend] = None,
    ) -> None:
        """
        Initialize cached client wrapper.

        Args:
            client: The underlying LLM client to wrap.
            cache_config: Cache configuration. If None, caching is disabled.
            cache_backend: Optional pre-configured cache backend. If provided,
                cache_config is ignored.
        """
        # Initialize with the wrapped client's config
        super().__init__(client.config)
        self.client = client

        # Set up caching
        self.cache_config = cache_config or CacheConfig(enabled=False)
        self.cache_enabled = self.cache_config.enabled

        if cache_backend:
            self.cache = cache_backend
        elif self.cache_enabled:
            self.cache = get_cache_backend(self.cache_config)
        else:
            self.cache = None

        # Metrics
        self.cache_hits = 0
        self.cache_misses = 0

    async def complete(
        self,
        messages: list[LLMMessage],
        force_refresh: bool = False,
        **kwargs: Any,
    ) -> LLMResponse:
        """
        Generate a completion with caching.

        Args:
            messages: List of conversation messages.
            force_refresh: If True, bypass cache and force fresh LLM call.
            **kwargs: Provider-specific options.

        Returns:
            The LLM's response (from cache or fresh API call).
        """
        # If caching is disabled or force refresh, call directly
        if not self.cache_enabled or force_refresh or self.cache is None:
            return await self.client.complete(messages, **kwargs)

        # Compute cache key
        cache_key = compute_cache_key(
            messages=messages,
            model=kwargs.get("model", self.config.model),
            temperature=kwargs.get("temperature", self.config.temperature),
            max_tokens=kwargs.get("max_tokens", self.config.max_tokens),
            **{k: v for k, v in kwargs.items() if k not in ["model", "temperature", "max_tokens"]},
        )

        # Try cache first
        cached_data = await self.cache.get(cache_key)
        if cached_data is not None:
            self.cache_hits += 1
            # Reconstruct LLMResponse from cached data
            return LLMResponse(**cached_data)

        # Cache miss - call underlying client
        self.cache_misses += 1
        response = await self.client.complete(messages, **kwargs)

        # Store in cache
        await self.cache.set(cache_key, response.model_dump())

        return response

    async def complete_json(
        self,
        messages: list[LLMMessage],
        schema: Optional[dict[str, Any]] = None,
        force_refresh: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Generate a JSON completion with caching.

        Args:
            messages: List of conversation messages.
            schema: Optional JSON schema for validation.
            force_refresh: If True, bypass cache and force fresh LLM call.
            **kwargs: Provider-specific options.

        Returns:
            Parsed JSON response (from cache or fresh API call).
        """
        # If caching is disabled or force refresh, call directly
        if not self.cache_enabled or force_refresh or self.cache is None:
            return await self.client.complete_json(messages, schema=schema, **kwargs)

        # Compute cache key (include schema in key)
        cache_key = compute_cache_key(
            messages=messages,
            model=kwargs.get("model", self.config.model),
            temperature=kwargs.get("temperature", self.config.temperature),
            max_tokens=kwargs.get("max_tokens", self.config.max_tokens),
            schema=schema,
            **{k: v for k, v in kwargs.items() if k not in ["model", "temperature", "max_tokens"]},
        )

        # Try cache first
        cached_data = await self.cache.get(cache_key)
        if cached_data is not None:
            self.cache_hits += 1
            return cached_data

        # Cache miss - call underlying client
        self.cache_misses += 1
        result = await self.client.complete_json(messages, schema=schema, **kwargs)

        # Store in cache
        await self.cache.set(cache_key, result)

        return result

    def get_cache_stats(self) -> dict[str, Any]:
        """
        Get cache performance statistics.

        Returns:
            Dictionary with cache hits, misses, and hit rate.
        """
        total_requests = self.cache_hits + self.cache_misses
        hit_rate = self.cache_hits / total_requests if total_requests > 0 else 0.0

        return {
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "total_requests": total_requests,
            "hit_rate": hit_rate,
            "cache_enabled": self.cache_enabled,
            "cache_backend": self.cache_config.backend if self.cache_enabled else None,
        }

    async def clear_cache(self) -> None:
        """Clear all cached entries."""
        if self.cache:
            await self.cache.clear()

    def reset_stats(self) -> None:
        """Reset cache statistics counters."""
        self.cache_hits = 0
        self.cache_misses = 0

