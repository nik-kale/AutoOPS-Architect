"""Tool interface and implementations for AutoOps Architect."""

from autoops_architect.tools.base import Tool, ToolResult, ToolConfig, ToolRegistry, create_default_registry
from autoops_architect.tools.builtin import (
    EchoTool,
    LogCollectorTool,
    SummaryTool,
    MetricQueryTool,
    AnalysisTool,
)
from autoops_architect.tools.integrations import (
    AutoRCATool,
    MCPTool,
    BrowserMissionTool,
    DatadogTool,
)


def get_default_tools() -> dict[str, Tool]:
    """
    Get a dictionary of all default tools.

    Returns:
        Dictionary mapping tool IDs to Tool instances.
    """
    registry = create_default_registry()
    return registry._tools


__all__ = [
    # Base
    "Tool",
    "ToolResult",
    "ToolConfig",
    "ToolRegistry",
    "create_default_registry",
    "get_default_tools",
    # Built-in tools
    "EchoTool",
    "LogCollectorTool",
    "SummaryTool",
    "MetricQueryTool",
    "AnalysisTool",
    # Integration tools
    "AutoRCATool",
    "MCPTool",
    "BrowserMissionTool",
    "DatadogTool",
]
