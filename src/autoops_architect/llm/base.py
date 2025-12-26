"""Base LLM client interface and types."""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class LLMProvider(str, Enum):
    """Supported LLM providers."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    MOCK = "mock"  # For testing


class LLMConfig(BaseModel):
    """Configuration for an LLM client."""

    provider: LLMProvider = Field(
        default=LLMProvider.MOCK,
        description="LLM provider to use"
    )

    model: str = Field(
        default="gpt-4",
        description="Model identifier"
    )

    api_key: Optional[str] = Field(
        default=None,
        description="API key (can also be set via environment variable)"
    )

    base_url: Optional[str] = Field(
        default=None,
        description="Custom base URL for the API"
    )

    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="Sampling temperature"
    )

    max_tokens: int = Field(
        default=4096,
        ge=1,
        le=128000,
        description="Maximum tokens in response"
    )

    timeout_seconds: int = Field(
        default=60,
        ge=1,
        le=300,
        description="Request timeout in seconds"
    )

    retry_count: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Number of retry attempts on failure"
    )


class LLMMessage(BaseModel):
    """A single message in a conversation."""

    role: str = Field(
        ...,
        description="Message role: system, user, or assistant"
    )

    content: str = Field(
        ...,
        description="Message content"
    )


class LLMResponse(BaseModel):
    """Response from an LLM completion request."""

    content: str = Field(
        ...,
        description="The generated text content"
    )

    model: str = Field(
        default="",
        description="Model that generated the response"
    )

    usage: dict[str, int] = Field(
        default_factory=dict,
        description="Token usage statistics"
    )

    finish_reason: Optional[str] = Field(
        default=None,
        description="Reason the generation stopped"
    )

    raw_response: Optional[dict[str, Any]] = Field(
        default=None,
        description="Raw response from the provider"
    )


class LLMClient(ABC):
    """
    Abstract base class for LLM clients.

    All LLM providers must implement this interface to be usable
    with AutoOps Architect.

    Example:
        >>> client = get_llm_client(LLMConfig(provider=LLMProvider.OPENAI))
        >>> response = await client.complete([
        ...     LLMMessage(role="user", content="Hello!")
        ... ])
        >>> print(response.content)
    """

    def __init__(self, config: LLMConfig) -> None:
        """Initialize the client with configuration."""
        self.config = config

    @abstractmethod
    async def complete(
        self,
        messages: list[LLMMessage],
        **kwargs: Any,
    ) -> LLMResponse:
        """
        Generate a completion for the given messages.

        Args:
            messages: List of conversation messages.
            **kwargs: Provider-specific options.

        Returns:
            The LLM's response.

        Raises:
            LLMError: If the request fails.
        """
        pass

    @abstractmethod
    async def complete_json(
        self,
        messages: list[LLMMessage],
        schema: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Generate a JSON completion.

        Args:
            messages: List of conversation messages.
            schema: Optional JSON schema for validation.
            **kwargs: Provider-specific options.

        Returns:
            Parsed JSON response.

        Raises:
            LLMError: If the request fails.
            ValueError: If the response is not valid JSON.
        """
        pass

    def sync_complete(
        self,
        messages: list[LLMMessage],
        **kwargs: Any,
    ) -> LLMResponse:
        """
        Synchronous wrapper for complete().

        Uses asyncio.run() to execute the async method in a new event loop.
        Compatible with Python 3.11+ and nested async contexts.
        """
        import asyncio

        try:
            # Check if we're already in an async context
            asyncio.get_running_loop()
            # If we reach here, we're in an async context - this is an error
            raise RuntimeError(
                "sync_complete() cannot be called from an async context. "
                "Use await complete() instead."
            )
        except RuntimeError:
            # No running loop - safe to use asyncio.run()
            pass

        return asyncio.run(self.complete(messages, **kwargs))

    def sync_complete_json(
        self,
        messages: list[LLMMessage],
        schema: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Synchronous wrapper for complete_json().

        Uses asyncio.run() to execute the async method in a new event loop.
        Compatible with Python 3.11+ and nested async contexts.
        """
        import asyncio

        try:
            # Check if we're already in an async context
            asyncio.get_running_loop()
            # If we reach here, we're in an async context - this is an error
            raise RuntimeError(
                "sync_complete_json() cannot be called from an async context. "
                "Use await complete_json() instead."
            )
        except RuntimeError:
            # No running loop - safe to use asyncio.run()
            pass

        return asyncio.run(self.complete_json(messages, schema=schema, **kwargs))


class LLMError(Exception):
    """Base exception for LLM-related errors."""

    def __init__(
        self,
        message: str,
        provider: Optional[str] = None,
        status_code: Optional[int] = None,
        response: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.response = response


class LLMRateLimitError(LLMError):
    """Raised when rate limited by the provider."""

    pass


class LLMAuthenticationError(LLMError):
    """Raised when authentication fails."""

    pass


class LLMTimeoutError(LLMError):
    """Raised when request times out."""

    pass
