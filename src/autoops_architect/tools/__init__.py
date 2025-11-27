"""Tool interface and implementations for AutoOps Architect."""

from autoops_architect.tools.base import Tool, ToolResult, ToolConfig, ToolRegistry
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
)

__all__ = [
    # Base
    "Tool",
    "ToolResult",
    "ToolConfig",
    "ToolRegistry",
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
]
