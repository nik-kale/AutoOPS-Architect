"""Semantic search capabilities for memory backend."""

import hashlib
import json
import math
import os
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field


class EmbeddingConfig(BaseModel):
    """Configuration for embedding providers."""

    provider: str = Field(
        default="local",
        description="Embedding provider: local, openai, anthropic"
    )

    model: Optional[str] = Field(
        default=None,
        description="Model name for the embedding provider"
    )

    api_key: Optional[str] = Field(
        default=None,
        description="API key (if not in environment)"
    )

    dimension: int = Field(
        default=384,
        description="Embedding dimension"
    )

    cache_path: Optional[str] = Field(
        default=None,
        description="Path to embedding cache file"
    )


class EmbeddingProvider(ABC):
    """Abstract base class for embedding providers."""

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Generate an embedding for the given text."""
        pass

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        pass

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Return the embedding dimension."""
        pass


class LocalEmbeddingProvider(EmbeddingProvider):
    """
    Simple local embedding provider using TF-IDF-like features.

    This is a lightweight fallback that doesn't require external APIs.
    It uses a combination of:
    - Character n-gram hashing
    - Word frequency features
    - Domain-specific keywords

    Not as good as neural embeddings but works offline and is fast.
    """

    # Domain-specific keywords for SRE/ops contexts
    DOMAIN_KEYWORDS = {
        # Error types
        "error": 0, "5xx": 1, "4xx": 2, "timeout": 3, "exception": 4,
        "failure": 5, "crash": 6, "oom": 7, "panic": 8, "fatal": 9,
        # Performance
        "latency": 10, "slow": 11, "performance": 12, "p99": 13, "p95": 14,
        "throughput": 15, "bottleneck": 16, "degradation": 17,
        # Infrastructure
        "kubernetes": 18, "k8s": 18, "pod": 19, "container": 20,
        "node": 21, "cluster": 22, "deployment": 23, "service": 24,
        "database": 25, "db": 25, "redis": 26, "postgres": 27, "mysql": 28,
        # Operations
        "investigation": 29, "debug": 30, "troubleshoot": 31, "diagnose": 32,
        "monitor": 33, "alert": 34, "incident": 35, "outage": 36,
        # Security
        "auth": 37, "authentication": 37, "login": 38, "security": 39,
        "permission": 40, "access": 41, "token": 42,
        # Resources
        "memory": 43, "cpu": 44, "disk": 45, "network": 46,
        "connection": 47, "pool": 48, "resource": 49,
    }

    def __init__(self, dimension: int = 384) -> None:
        """Initialize local embedding provider."""
        self._dimension = dimension
        self._keyword_dim = 50  # Reserved for domain keywords

    @property
    def dimension(self) -> int:
        """Return embedding dimension."""
        return self._dimension

    def embed(self, text: str) -> list[float]:
        """Generate embedding using local features."""
        # Initialize embedding vector
        embedding = [0.0] * self._dimension

        text_lower = text.lower()
        words = re.findall(r'\w+', text_lower)

        # 1. Domain keyword features (first 50 dimensions)
        for word in words:
            if word in self.DOMAIN_KEYWORDS:
                idx = self.DOMAIN_KEYWORDS[word]
                embedding[idx] = 1.0

        # 2. Character trigram features (next dimensions)
        trigram_start = self._keyword_dim
        trigram_end = self._dimension // 2

        for i in range(len(text_lower) - 2):
            trigram = text_lower[i:i+3]
            # Hash the trigram to a position
            h = int(hashlib.md5(trigram.encode()).hexdigest(), 16)
            idx = trigram_start + (h % (trigram_end - trigram_start))
            embedding[idx] += 1.0

        # 3. Word hash features (remaining dimensions)
        word_start = self._dimension // 2
        word_end = self._dimension

        for word in words:
            if len(word) > 2:
                h = int(hashlib.md5(word.encode()).hexdigest(), 16)
                idx = word_start + (h % (word_end - word_start))
                embedding[idx] += 1.0

        # Normalize the vector
        magnitude = math.sqrt(sum(x * x for x in embedding))
        if magnitude > 0:
            embedding = [x / magnitude for x in embedding]

        return embedding

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        return [self.embed(text) for text in texts]


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """
    OpenAI embedding provider using text-embedding-3-small.

    Requires OPENAI_API_KEY environment variable or api_key in config.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "text-embedding-3-small",
    ) -> None:
        """Initialize OpenAI embedding provider."""
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.model = model
        self._dimension = 1536 if "large" in model else 512

        if not self.api_key:
            raise ValueError("OpenAI API key required")

    @property
    def dimension(self) -> int:
        """Return embedding dimension."""
        return self._dimension

    def embed(self, text: str) -> list[float]:
        """Generate embedding using OpenAI API."""
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings using OpenAI API."""
        try:
            import httpx
        except ImportError:
            raise ImportError("httpx required for OpenAI embeddings: pip install httpx")

        response = httpx.post(
            "https://api.openai.com/v1/embeddings",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "input": texts,
            },
            timeout=30.0,
        )
        response.raise_for_status()

        data = response.json()
        # Sort by index to ensure correct order
        embeddings = sorted(data["data"], key=lambda x: x["index"])
        return [e["embedding"] for e in embeddings]


class EmbeddingCache:
    """
    Simple file-based cache for embeddings.

    Stores embeddings by content hash to avoid recomputation.
    """

    def __init__(self, cache_path: str = "~/.autoops/embeddings.json") -> None:
        """Initialize embedding cache."""
        self.cache_path = Path(cache_path).expanduser()
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, list[float]] = {}
        self._load()

    def _load(self) -> None:
        """Load cache from disk."""
        if self.cache_path.exists():
            try:
                with open(self.cache_path, "r") as f:
                    self._cache = json.load(f)
            except (json.JSONDecodeError, Exception):
                self._cache = {}

    def _save(self) -> None:
        """Save cache to disk."""
        with open(self.cache_path, "w") as f:
            json.dump(self._cache, f)

    def _hash_text(self, text: str) -> str:
        """Generate hash for text."""
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    def get(self, text: str) -> Optional[list[float]]:
        """Get cached embedding."""
        key = self._hash_text(text)
        return self._cache.get(key)

    def set(self, text: str, embedding: list[float]) -> None:
        """Cache an embedding."""
        key = self._hash_text(text)
        self._cache[key] = embedding
        self._save()

    def get_or_compute(
        self,
        text: str,
        provider: EmbeddingProvider,
    ) -> list[float]:
        """Get from cache or compute embedding."""
        cached = self.get(text)
        if cached is not None:
            return cached

        embedding = provider.embed(text)
        self.set(text, embedding)
        return embedding


def cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
    """
    Calculate cosine similarity between two vectors.

    Args:
        vec1: First vector.
        vec2: Second vector.

    Returns:
        Cosine similarity (0 to 1 for normalized vectors).
    """
    if len(vec1) != len(vec2):
        raise ValueError("Vectors must have same dimension")

    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    magnitude1 = math.sqrt(sum(a * a for a in vec1))
    magnitude2 = math.sqrt(sum(b * b for b in vec2))

    if magnitude1 == 0 or magnitude2 == 0:
        return 0.0

    return dot_product / (magnitude1 * magnitude2)


def get_embedding_provider(config: Optional[EmbeddingConfig] = None) -> EmbeddingProvider:
    """
    Factory function to get an embedding provider.

    Args:
        config: Embedding configuration.

    Returns:
        An EmbeddingProvider instance.
    """
    if config is None:
        config = EmbeddingConfig()

    if config.provider == "openai":
        return OpenAIEmbeddingProvider(
            api_key=config.api_key,
            model=config.model or "text-embedding-3-small",
        )
    else:
        # Default to local provider
        return LocalEmbeddingProvider(dimension=config.dimension)


class SemanticSearcher:
    """
    Semantic search helper for memory entries.

    Combines keyword-based and embedding-based search for best results.
    """

    def __init__(
        self,
        provider: Optional[EmbeddingProvider] = None,
        cache: Optional[EmbeddingCache] = None,
    ) -> None:
        """Initialize semantic searcher."""
        self.provider = provider or LocalEmbeddingProvider()
        self.cache = cache or EmbeddingCache()

    def embed_text(self, text: str) -> list[float]:
        """Get embedding for text, using cache."""
        return self.cache.get_or_compute(text, self.provider)

    def semantic_similarity(self, text1: str, text2: str) -> float:
        """Calculate semantic similarity between two texts."""
        emb1 = self.embed_text(text1)
        emb2 = self.embed_text(text2)
        return cosine_similarity(emb1, emb2)

    def rank_by_similarity(
        self,
        query: str,
        texts: list[str],
        top_k: int = 10,
    ) -> list[tuple[int, float]]:
        """
        Rank texts by similarity to query.

        Args:
            query: Query text.
            texts: List of texts to rank.
            top_k: Number of top results to return.

        Returns:
            List of (index, score) tuples, sorted by score descending.
        """
        query_emb = self.embed_text(query)

        results = []
        for i, text in enumerate(texts):
            text_emb = self.embed_text(text)
            score = cosine_similarity(query_emb, text_emb)
            results.append((i, score))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def hybrid_score(
        self,
        query: str,
        text: str,
        keywords: list[str],
        text_keywords: list[str],
        semantic_weight: float = 0.6,
    ) -> float:
        """
        Calculate hybrid score combining semantic and keyword similarity.

        Args:
            query: Query text.
            text: Text to compare.
            keywords: Query keywords.
            text_keywords: Text keywords.
            semantic_weight: Weight for semantic similarity (0-1).

        Returns:
            Combined score (0-1).
        """
        # Semantic similarity
        semantic_score = self.semantic_similarity(query, text)

        # Keyword overlap
        query_kw = set(k.lower() for k in keywords)
        text_kw = set(k.lower() for k in text_keywords)

        if query_kw:
            keyword_score = len(query_kw & text_kw) / len(query_kw)
        else:
            keyword_score = 0.0

        # Combine scores
        keyword_weight = 1.0 - semantic_weight
        combined = (semantic_weight * semantic_score) + (keyword_weight * keyword_score)

        return min(combined, 1.0)
