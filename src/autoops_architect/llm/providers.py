"""LLM provider implementations."""

import json
import os
import re
from typing import Any, Optional

from autoops_architect.llm.base import (
    LLMClient,
    LLMConfig,
    LLMError,
    LLMMessage,
    LLMProvider,
    LLMResponse,
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMTimeoutError,
)


class OpenAIClient(LLMClient):
    """
    OpenAI API client implementation.

    Requires the 'openai' package to be installed:
        pip install autoops-architect[openai]

    Configuration:
        - Set OPENAI_API_KEY environment variable, or
        - Pass api_key in LLMConfig
    """

    def __init__(self, config: LLMConfig) -> None:
        super().__init__(config)
        self._client: Optional[Any] = None

    def _get_client(self) -> Any:
        """Lazy initialization of the OpenAI client."""
        if self._client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError:
                raise ImportError(
                    "OpenAI package not installed. "
                    "Install with: pip install autoops-architect[openai]"
                )

            api_key = self.config.api_key or os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise LLMAuthenticationError(
                    "OpenAI API key not found. Set OPENAI_API_KEY environment variable "
                    "or pass api_key in configuration.",
                    provider="openai",
                )

            self._client = AsyncOpenAI(
                api_key=api_key,
                base_url=self.config.base_url,
                timeout=self.config.timeout_seconds,
            )

        return self._client

    async def complete(
        self,
        messages: list[LLMMessage],
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a completion using OpenAI API."""
        client = self._get_client()

        try:
            response = await client.chat.completions.create(
                model=kwargs.get("model", self.config.model),
                messages=[{"role": m.role, "content": m.content} for m in messages],
                temperature=kwargs.get("temperature", self.config.temperature),
                max_tokens=kwargs.get("max_tokens", self.config.max_tokens),
            )

            choice = response.choices[0]
            return LLMResponse(
                content=choice.message.content or "",
                model=response.model,
                usage={
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                    "total_tokens": response.usage.total_tokens if response.usage else 0,
                },
                finish_reason=choice.finish_reason,
            )

        except Exception as e:
            error_msg = str(e)
            if "rate_limit" in error_msg.lower():
                raise LLMRateLimitError(error_msg, provider="openai")
            if "authentication" in error_msg.lower() or "api key" in error_msg.lower():
                raise LLMAuthenticationError(error_msg, provider="openai")
            if "timeout" in error_msg.lower():
                raise LLMTimeoutError(error_msg, provider="openai")
            raise LLMError(error_msg, provider="openai")

    async def complete_json(
        self,
        messages: list[LLMMessage],
        schema: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate a JSON completion using OpenAI API."""
        client = self._get_client()

        try:
            response = await client.chat.completions.create(
                model=kwargs.get("model", self.config.model),
                messages=[{"role": m.role, "content": m.content} for m in messages],
                temperature=kwargs.get("temperature", self.config.temperature),
                max_tokens=kwargs.get("max_tokens", self.config.max_tokens),
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content or "{}"
            return json.loads(content)

        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in response: {e}")
        except Exception as e:
            error_msg = str(e)
            raise LLMError(error_msg, provider="openai")


class AnthropicClient(LLMClient):
    """
    Anthropic API client implementation.

    Requires the 'anthropic' package to be installed:
        pip install autoops-architect[anthropic]

    Configuration:
        - Set ANTHROPIC_API_KEY environment variable, or
        - Pass api_key in LLMConfig
    """

    def __init__(self, config: LLMConfig) -> None:
        super().__init__(config)
        self._client: Optional[Any] = None

    def _get_client(self) -> Any:
        """Lazy initialization of the Anthropic client."""
        if self._client is None:
            try:
                from anthropic import AsyncAnthropic
            except ImportError:
                raise ImportError(
                    "Anthropic package not installed. "
                    "Install with: pip install autoops-architect[anthropic]"
                )

            api_key = self.config.api_key or os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise LLMAuthenticationError(
                    "Anthropic API key not found. Set ANTHROPIC_API_KEY environment "
                    "variable or pass api_key in configuration.",
                    provider="anthropic",
                )

            self._client = AsyncAnthropic(
                api_key=api_key,
                timeout=self.config.timeout_seconds,
            )

        return self._client

    async def complete(
        self,
        messages: list[LLMMessage],
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a completion using Anthropic API."""
        client = self._get_client()

        # Anthropic uses a different message format
        # Extract system message if present
        system_content = ""
        user_messages = []

        for msg in messages:
            if msg.role == "system":
                system_content = msg.content
            else:
                user_messages.append({"role": msg.role, "content": msg.content})

        # Ensure we have at least one user message
        if not user_messages:
            user_messages = [{"role": "user", "content": ""}]

        try:
            response = await client.messages.create(
                model=kwargs.get("model", self.config.model),
                system=system_content,
                messages=user_messages,
                temperature=kwargs.get("temperature", self.config.temperature),
                max_tokens=kwargs.get("max_tokens", self.config.max_tokens),
            )

            content = ""
            for block in response.content:
                if hasattr(block, "text"):
                    content += block.text

            return LLMResponse(
                content=content,
                model=response.model,
                usage={
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                },
                finish_reason=response.stop_reason,
            )

        except Exception as e:
            error_msg = str(e)
            if "rate_limit" in error_msg.lower():
                raise LLMRateLimitError(error_msg, provider="anthropic")
            if "authentication" in error_msg.lower() or "api key" in error_msg.lower():
                raise LLMAuthenticationError(error_msg, provider="anthropic")
            if "timeout" in error_msg.lower():
                raise LLMTimeoutError(error_msg, provider="anthropic")
            raise LLMError(error_msg, provider="anthropic")

    async def complete_json(
        self,
        messages: list[LLMMessage],
        schema: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate a JSON completion using Anthropic API."""
        # Add JSON instruction to the last user message
        json_messages = list(messages)

        json_instruction = "\n\nRespond with valid JSON only. No markdown, no explanation."
        if schema:
            json_instruction += f"\n\nJSON Schema: {json.dumps(schema)}"

        if json_messages and json_messages[-1].role == "user":
            json_messages[-1] = LLMMessage(
                role="user",
                content=json_messages[-1].content + json_instruction,
            )
        else:
            json_messages.append(LLMMessage(role="user", content=json_instruction))

        response = await self.complete(json_messages, **kwargs)

        # Extract JSON from response (handle markdown code blocks)
        content = response.content.strip()

        # Remove markdown code blocks if present
        if content.startswith("```"):
            # Find the end of the opening fence
            first_newline = content.find("\n")
            if first_newline != -1:
                content = content[first_newline + 1:]
            # Remove closing fence
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in response: {e}\nContent: {content[:500]}")


class MockLLMClient(LLMClient):
    """
    Mock LLM client for testing.

    Returns predefined responses or generates simple mock workflows
    for testing purposes without making actual API calls.
    """

    def __init__(
        self,
        config: LLMConfig,
        responses: Optional[list[str]] = None,
        json_responses: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        super().__init__(config)
        self.responses = responses or []
        self.json_responses = json_responses or []
        self._response_index = 0
        self._json_response_index = 0
        self.call_history: list[list[LLMMessage]] = []

    async def complete(
        self,
        messages: list[LLMMessage],
        **kwargs: Any,
    ) -> LLMResponse:
        """Return a mock response."""
        self.call_history.append(messages)

        if self.responses and self._response_index < len(self.responses):
            content = self.responses[self._response_index]
            self._response_index += 1
        else:
            # Generate a simple mock response
            last_msg = messages[-1].content if messages else ""
            content = f"Mock response for: {last_msg[:100]}"

        return LLMResponse(
            content=content,
            model="mock-model",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            finish_reason="stop",
        )

    async def complete_json(
        self,
        messages: list[LLMMessage],
        schema: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Return a mock JSON response."""
        self.call_history.append(messages)

        if self.json_responses and self._json_response_index < len(self.json_responses):
            result = self.json_responses[self._json_response_index]
            self._json_response_index += 1
            return result

        # Generate a simple mock workflow
        return self._generate_mock_workflow(messages)

    def _generate_mock_workflow(self, messages: list[LLMMessage]) -> dict[str, Any]:
        """Generate a mock workflow based on the goal."""
        # Extract goal from messages
        goal = ""
        for msg in messages:
            if msg.role == "user":
                goal = msg.content
                break

        # Create a simple 3-node workflow
        return {
            "id": "wf-mock-001",
            "name": "Mock Investigation Workflow",
            "goal_description": goal[:200] if goal else "Mock goal",
            "nodes": [
                {
                    "id": "collect-logs",
                    "name": "Collect service logs",
                    "description": "Collect logs from the affected service",
                    "type": "log_collection",
                    "tool": "log_collector",
                    "params": {"duration": "1h"},
                    "requires_human_approval": False,
                },
                {
                    "id": "analyze-logs",
                    "name": "Analyze logs for errors",
                    "description": "Analyze collected logs to identify error patterns",
                    "type": "analysis",
                    "tool": "log_analyzer",
                    "params": {},
                    "requires_human_approval": False,
                },
                {
                    "id": "create-summary",
                    "name": "Create investigation summary",
                    "description": "Generate a summary of findings",
                    "type": "summary",
                    "tool": "summary",
                    "params": {},
                    "requires_human_approval": False,
                },
            ],
            "edges": [
                {"from_node_id": "collect-logs", "to_node_id": "analyze-logs"},
                {"from_node_id": "analyze-logs", "to_node_id": "create-summary"},
            ],
        }

    def reset(self) -> None:
        """Reset the mock client state."""
        self._response_index = 0
        self._json_response_index = 0
        self.call_history.clear()


def get_llm_client(config: Optional[LLMConfig] = None) -> LLMClient:
    """
    Factory function to get an LLM client based on configuration.

    If no config is provided, attempts to auto-detect from environment:
    - If OPENAI_API_KEY is set, uses OpenAI
    - If ANTHROPIC_API_KEY is set, uses Anthropic
    - Otherwise, uses Mock client

    Args:
        config: Optional LLM configuration.

    Returns:
        An LLM client instance.
    """
    if config is None:
        # Auto-detect based on environment
        if os.getenv("OPENAI_API_KEY"):
            config = LLMConfig(provider=LLMProvider.OPENAI, model="gpt-4")
        elif os.getenv("ANTHROPIC_API_KEY"):
            config = LLMConfig(provider=LLMProvider.ANTHROPIC, model="claude-3-sonnet-20240229")
        else:
            config = LLMConfig(provider=LLMProvider.MOCK)

    if config.provider == LLMProvider.OPENAI:
        return OpenAIClient(config)
    elif config.provider == LLMProvider.ANTHROPIC:
        return AnthropicClient(config)
    elif config.provider == LLMProvider.MOCK:
        return MockLLMClient(config)
    else:
        raise ValueError(f"Unsupported LLM provider: {config.provider}")
