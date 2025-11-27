"""Memory backends for storing institutional knowledge."""

from autoops_architect.memory.backend import (
    MemoryBackend,
    JSONMemoryBackend,
    SQLiteMemoryBackend,
    get_memory_backend,
)
from autoops_architect.memory.semantic import (
    EmbeddingConfig,
    EmbeddingProvider,
    LocalEmbeddingProvider,
    EmbeddingCache,
    SemanticSearcher,
    cosine_similarity,
    get_embedding_provider,
)

__all__ = [
    # Backend
    "MemoryBackend",
    "JSONMemoryBackend",
    "SQLiteMemoryBackend",
    "get_memory_backend",
    # Semantic search
    "EmbeddingConfig",
    "EmbeddingProvider",
    "LocalEmbeddingProvider",
    "EmbeddingCache",
    "SemanticSearcher",
    "cosine_similarity",
    "get_embedding_provider",
]
