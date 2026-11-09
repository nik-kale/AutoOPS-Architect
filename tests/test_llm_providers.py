"""Tests for the OpenAI and Anthropic clients against stand-in SDK objects."""

import sys
from types import SimpleNamespace
from typing import Any

import pytest

from autoops_architect.llm.base import (
    LLMAuthenticationError,
    LLMConfig,
    LLMError,
    LLMMessage,
    LLMProvider,
    LLMRateLimitError,
    LLMTimeoutError,
)
from autoops_architect.llm.providers import (
    AnthropicClient,
    MockLLMClient,
    OpenAIClient,
    get_llm_client,
)

MESSAGES = [
    LLMMessage(role="system", content="Be brief"),
    LLMMessage(role="user", content="Hello"),
]


class FakeCreate:
    """Stand-in for an SDK create() coroutine."""

    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


def openai_client(create: FakeCreate) -> OpenAIClient:
    client = OpenAIClient(LLMConfig(provider=LLMProvider.OPENAI, model="m", api_key="k"))
    client._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    return client


def anthropic_client(create: FakeCreate) -> AnthropicClient:
    client = AnthropicClient(LLMConfig(provider=LLMProvider.ANTHROPIC, model="m", api_key="k"))
    client._client = SimpleNamespace(messages=SimpleNamespace(create=create))
    return client


def openai_response(content: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        model="m",
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason="stop")],
    )


def anthropic_response(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        model="m",
        usage=SimpleNamespace(input_tokens=1, output_tokens=2),
        stop_reason="end_turn",
        content=[SimpleNamespace(text=text), SimpleNamespace(type="thinking")],
    )


ERROR_CASES = [
    ("rate_limit exceeded", LLMRateLimitError),
    ("Invalid API key", LLMAuthenticationError),
    ("request timeout", LLMTimeoutError),
    ("something else", LLMError),
]


class TestOpenAI:
    async def test_complete_maps_the_response(self) -> None:
        create = FakeCreate(openai_response("Hi"))

        response = await openai_client(create).complete(MESSAGES)

        assert response.content == "Hi"
        assert response.usage["total_tokens"] == 3
        assert create.calls[0]["messages"][0] == {"role": "system", "content": "Be brief"}

    async def test_complete_json_parses_the_content(self) -> None:
        result = await openai_client(FakeCreate(openai_response('{"a": 1}'))).complete_json(
            MESSAGES
        )

        assert result == {"a": 1}

    async def test_complete_json_rejects_non_json(self) -> None:
        with pytest.raises(ValueError, match="Invalid JSON"):
            await openai_client(FakeCreate(openai_response("nope"))).complete_json(MESSAGES)

    @pytest.mark.parametrize(("message", "expected"), ERROR_CASES)
    async def test_errors_are_classified(self, message: str, expected: type[Exception]) -> None:
        with pytest.raises(expected):
            await openai_client(FakeCreate(error=RuntimeError(message))).complete(MESSAGES)

    def test_missing_key_is_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(AsyncOpenAI=object))
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        with pytest.raises(LLMAuthenticationError):
            OpenAIClient(LLMConfig(provider=LLMProvider.OPENAI))._get_client()


class TestAnthropic:
    async def test_system_message_is_sent_separately(self) -> None:
        create = FakeCreate(anthropic_response("Hi"))

        response = await anthropic_client(create).complete(MESSAGES)

        assert response.content == "Hi"
        assert create.calls[0]["system"] == "Be brief"
        assert create.calls[0]["messages"] == [{"role": "user", "content": "Hello"}]

    @pytest.mark.parametrize("text", ['{"a": 1}', '```json\n{"a": 1}\n```'])
    async def test_complete_json_handles_code_fences(self, text: str) -> None:
        result = await anthropic_client(FakeCreate(anthropic_response(text))).complete_json(
            MESSAGES
        )

        assert result == {"a": 1}

    async def test_schema_is_added_to_the_prompt(self) -> None:
        create = FakeCreate(anthropic_response("{}"))

        await anthropic_client(create).complete_json(MESSAGES, schema={"type": "object"})

        assert '"type": "object"' in create.calls[0]["messages"][0]["content"]

    async def test_complete_json_rejects_non_json(self) -> None:
        with pytest.raises(ValueError, match="Invalid JSON"):
            await anthropic_client(FakeCreate(anthropic_response("nope"))).complete_json(MESSAGES)

    @pytest.mark.parametrize(("message", "expected"), ERROR_CASES)
    async def test_errors_are_classified(self, message: str, expected: type[Exception]) -> None:
        with pytest.raises(expected):
            await anthropic_client(FakeCreate(error=RuntimeError(message))).complete(MESSAGES)


class TestProviderSelection:
    def test_mock_without_keys(self) -> None:
        assert isinstance(get_llm_client(), MockLLMClient)

    def test_openai_key_selects_openai(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "k")

        assert isinstance(get_llm_client(), OpenAIClient)

    def test_anthropic_key_selects_anthropic(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")

        assert isinstance(get_llm_client(), AnthropicClient)

    def test_explicit_config_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "k")

        assert isinstance(get_llm_client(LLMConfig(provider=LLMProvider.MOCK)), MockLLMClient)
