"""Tests for tools."""

import pytest

from autoops_architect.tools.base import (
    Tool,
    ToolConfig,
    ToolRegistry,
    ToolResult,
    ToolStatus,
    create_default_registry,
)
from autoops_architect.tools.builtin import (
    EchoTool,
    LogCollectorTool,
    MetricQueryTool,
    AnalysisTool,
    SummaryTool,
)
from autoops_architect.tools.integrations import (
    AutoRCATool,
    MCPTool,
    BrowserMissionTool,
)


class TestToolResult:
    """Tests for ToolResult."""

    def test_success_result(self):
        """Test creating a success result."""
        result = ToolResult.success(
            outputs={"key": "value"},
            raw_output="Some output",
        )

        assert result.status == ToolStatus.SUCCESS
        assert result.outputs["key"] == "value"
        assert result.raw_output == "Some output"

    def test_failed_result(self):
        """Test creating a failed result."""
        result = ToolResult.failed("Something went wrong")

        assert result.status == ToolStatus.FAILED
        assert result.error_message == "Something went wrong"

    def test_timeout_result(self):
        """Test creating a timeout result."""
        result = ToolResult.timeout()

        assert result.status == ToolStatus.TIMEOUT
        assert "timed out" in result.error_message


class TestToolConfig:
    """Tests for ToolConfig."""

    def test_default_config(self):
        """Test default configuration."""
        config = ToolConfig()

        assert config.enabled is True
        assert config.timeout_seconds == 60
        assert config.retry_count == 0

    def test_custom_config(self):
        """Test custom configuration."""
        config = ToolConfig(
            enabled=False,
            timeout_seconds=120,
            retry_count=3,
        )

        assert config.enabled is False
        assert config.timeout_seconds == 120


class TestToolRegistry:
    """Tests for ToolRegistry."""

    def test_register_tool(self):
        """Test registering a tool."""
        registry = ToolRegistry()
        registry.register(EchoTool())

        assert registry.has("echo")
        assert registry.get("echo") is not None

    def test_register_duplicate(self):
        """Test that duplicate registration fails."""
        registry = ToolRegistry()
        registry.register(EchoTool())

        with pytest.raises(ValueError):
            registry.register(EchoTool())

    def test_list_tools(self):
        """Test listing tools."""
        registry = ToolRegistry()
        registry.register(EchoTool())
        registry.register(LogCollectorTool())

        tools = registry.list_tools()
        assert "echo" in tools
        assert "log_collector" in tools

    def test_get_nonexistent(self):
        """Test getting a non-existent tool."""
        registry = ToolRegistry()
        assert registry.get("nonexistent") is None

    def test_create_default_registry(self):
        """Test creating default registry."""
        registry = create_default_registry()

        assert registry.has("echo")
        assert registry.has("log_collector")
        assert registry.has("summary")


class TestEchoTool:
    """Tests for EchoTool."""

    @pytest.mark.asyncio
    async def test_echo_basic(self):
        """Test basic echo functionality."""
        tool = EchoTool()
        result = await tool.execute({"message": "Hello, World!"})

        assert result.status == ToolStatus.SUCCESS
        assert "Hello, World!" in result.raw_output
        assert result.outputs["echoed_params"]["message"] == "Hello, World!"

    def test_echo_tool_id(self):
        """Test echo tool ID."""
        tool = EchoTool()
        assert tool.tool_id == "echo"

    def test_echo_sync(self):
        """Test synchronous execution."""
        tool = EchoTool()
        result = tool.execute_sync({"message": "Test"})

        assert result.status == ToolStatus.SUCCESS


class TestLogCollectorTool:
    """Tests for LogCollectorTool."""

    @pytest.mark.asyncio
    async def test_collect_logs(self):
        """Test log collection."""
        tool = LogCollectorTool()
        result = await tool.execute({
            "service": "test-service",
            "duration": "1h",
            "level": "error",
        })

        assert result.status == ToolStatus.SUCCESS
        assert "log_count" in result.outputs
        assert "error_count" in result.outputs
        assert result.outputs["service"] == "test-service"

    @pytest.mark.asyncio
    async def test_collect_logs_default_params(self):
        """Test log collection with defaults."""
        tool = LogCollectorTool()
        result = await tool.execute({"service": "my-service"})

        assert result.status == ToolStatus.SUCCESS
        assert result.outputs["duration"] == "1h"


class TestMetricQueryTool:
    """Tests for MetricQueryTool."""

    @pytest.mark.asyncio
    async def test_query_metrics(self):
        """Test metric querying."""
        tool = MetricQueryTool()
        result = await tool.execute({
            "service": "test-service",
            "metric_name": "http_requests_total",
        })

        assert result.status == ToolStatus.SUCCESS
        assert "current_value" in result.outputs
        assert "avg_value" in result.outputs


class TestAnalysisTool:
    """Tests for AnalysisTool."""

    @pytest.mark.asyncio
    async def test_analyze_with_context(self):
        """Test analysis with context from previous nodes."""
        tool = AnalysisTool()

        # Simulate context from a log collector
        context = {
            "collect-logs": {
                "logs": [
                    {"level": "error", "message": "Connection failed"},
                    {"level": "error", "message": "Timeout"},
                    {"level": "info", "message": "Started"},
                ]
            }
        }

        result = await tool.execute(
            {"analysis_type": "error_patterns"},
            context=context,
        )

        assert result.status == ToolStatus.SUCCESS
        assert "findings" in result.outputs
        assert "severity" in result.outputs

    @pytest.mark.asyncio
    async def test_analyze_no_context(self):
        """Test analysis without context."""
        tool = AnalysisTool()
        result = await tool.execute({})

        assert result.status == ToolStatus.SUCCESS
        # Should find no issues
        assert result.outputs["findings"][0]["type"] == "no_issues"


class TestSummaryTool:
    """Tests for SummaryTool."""

    @pytest.mark.asyncio
    async def test_generate_summary(self):
        """Test summary generation."""
        tool = SummaryTool()

        context = {
            "analysis": {
                "findings": [
                    {"type": "error", "description": "Found errors", "severity": "high"}
                ],
                "recommendation": "Investigate immediately",
            }
        }

        result = await tool.execute(
            {"format": "brief"},
            context=context,
        )

        assert result.status == ToolStatus.SUCCESS
        assert "summary" in result.outputs
        assert len(result.outputs["summary"]) > 0

    @pytest.mark.asyncio
    async def test_summary_markdown_format(self):
        """Test markdown format summary."""
        tool = SummaryTool()
        result = await tool.execute({"format": "markdown"})

        assert result.status == ToolStatus.SUCCESS
        assert "#" in result.outputs["summary"]  # Markdown header


class TestIntegrationTools:
    """Tests for integration tools."""

    @pytest.mark.asyncio
    async def test_autorca_disabled(self):
        """Test AutoRCA when disabled."""
        tool = AutoRCATool(config=ToolConfig(enabled=False))
        result = await tool.execute({})

        assert result.status == ToolStatus.SUCCESS
        assert result.outputs["status"] == "disabled"

    @pytest.mark.asyncio
    async def test_mcp_disabled(self):
        """Test MCP tool when disabled."""
        tool = MCPTool(config=ToolConfig(enabled=False))
        result = await tool.execute({
            "server": "jira",
            "action": "create_issue",
        })

        assert result.status == ToolStatus.SUCCESS
        assert result.outputs["status"] == "disabled"

    @pytest.mark.asyncio
    async def test_browser_disabled(self):
        """Test browser tool when disabled."""
        tool = BrowserMissionTool(config=ToolConfig(enabled=False))
        result = await tool.execute({
            "mission_type": "health_check",
        })

        assert result.status == ToolStatus.SUCCESS
        assert result.outputs["status"] == "disabled"

    @pytest.mark.asyncio
    async def test_autorca_enabled_mock(self):
        """Test AutoRCA mock response when enabled."""
        tool = AutoRCATool(config=ToolConfig(enabled=True))
        result = await tool.execute({
            "symptoms": ["High error rate", "Slow responses"],
        })

        assert result.status == ToolStatus.SUCCESS
        assert "root_cause" in result.outputs
        assert "recommendations" in result.outputs

    @pytest.mark.asyncio
    async def test_mcp_jira_mock(self):
        """Test MCP Jira mock response."""
        tool = MCPTool(config=ToolConfig(enabled=True))
        result = await tool.execute({
            "server": "jira",
            "action": "create_issue",
            "arguments": {"summary": "Test issue"},
        })

        assert result.status == ToolStatus.SUCCESS
        assert "issue_key" in result.outputs

    @pytest.mark.asyncio
    async def test_mcp_slack_mock(self):
        """Test MCP Slack mock response."""
        tool = MCPTool(config=ToolConfig(enabled=True))
        result = await tool.execute({
            "server": "slack",
            "action": "send_message",
            "arguments": {"channel": "#alerts"},
        })

        assert result.status == ToolStatus.SUCCESS
        assert result.outputs["channel"] == "#alerts"
