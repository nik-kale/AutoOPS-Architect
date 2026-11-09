"""Tests for the time ranges the Datadog integration sends."""

import time

import httpx
import pytest

from autoops_architect.tools.base import ToolConfig, ToolStatus
from autoops_architect.tools.integrations import DatadogTool


class TestDatadogTimeRange:
    @pytest.fixture
    def tool(self, monkeypatch: pytest.MonkeyPatch) -> DatadogTool:
        monkeypatch.setenv("DATADOG_API_KEY", "key")
        monkeypatch.setenv("DATADOG_APP_KEY", "app")
        return DatadogTool(config=ToolConfig(enabled=True))

    @pytest.fixture
    def requests(self, monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"status": "ok"})

        real_client = httpx.AsyncClient
        monkeypatch.setattr(
            "autoops_architect.tools.integrations.httpx.AsyncClient",
            lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
        )
        return seen

    @pytest.mark.parametrize(
        ("timeframe", "seconds"), [("30m", 1800), ("6h", 21600), ("1d", 86400)]
    )
    async def test_metric_query_uses_epoch_seconds(
        self, tool: DatadogTool, requests: list[httpx.Request], timeframe: str, seconds: int
    ) -> None:
        result = await tool.execute(
            {"action": "query_metrics", "query": "avg:cpu{*}", "timeframe": timeframe}
        )

        assert result.status == ToolStatus.SUCCESS, result.error_message
        params = requests[0].url.params
        assert abs(int(params["to"]) - time.time()) < 60
        assert int(params["to"]) - int(params["from"]) == seconds

    async def test_unsupported_timeframe_is_a_failed_result(
        self, tool: DatadogTool, requests: list[httpx.Request]
    ) -> None:
        result = await tool.execute({"action": "query_metrics", "timeframe": "soon"})

        assert result.status == ToolStatus.FAILED
        assert requests == []
