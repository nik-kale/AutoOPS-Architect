"""Tool interface and implementations for AutoOps Architect."""

from autoops_architect.tools.base import (
    Tool,
    ToolConfig,
    ToolRegistry,
    ToolResult,
    create_default_registry,
)
from autoops_architect.tools.builtin import (
    AnalysisTool,
    EchoTool,
    LogCollectorTool,
    MetricQueryTool,
    SummaryTool,
    TraceCollectorTool,
)
from autoops_architect.tools.integrations import (
    AutoRCATool,
    BrowserMissionTool,
    DatadogTool,
    MCPTool,
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
    "TraceCollectorTool",
    # Integration tools
    "AutoRCATool",
    "MCPTool",
    "BrowserMissionTool",
    "DatadogTool",
]
