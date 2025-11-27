"""Base tool interface and registry for AutoOps Architect."""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Optional, Type

from pydantic import BaseModel, Field


class ToolStatus(str, Enum):
    """Status of a tool execution."""

    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


class ToolResult(BaseModel):
    """
    Result of executing a tool.

    Captures the outcome, outputs, and any errors from tool execution.
    """

    status: ToolStatus = Field(
        default=ToolStatus.SUCCESS,
        description="Execution status"
    )

    outputs: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured outputs from the tool"
    )

    raw_output: Optional[str] = Field(
        default=None,
        description="Raw text/log output"
    )

    error_message: Optional[str] = Field(
        default=None,
        description="Error message if execution failed"
    )

    artifacts: list[str] = Field(
        default_factory=list,
        description="Paths or URLs to generated artifacts"
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata about the execution"
    )

    @classmethod
    def success(
        cls,
        outputs: Optional[dict[str, Any]] = None,
        raw_output: Optional[str] = None,
        artifacts: Optional[list[str]] = None,
    ) -> "ToolResult":
        """Create a successful result."""
        return cls(
            status=ToolStatus.SUCCESS,
            outputs=outputs or {},
            raw_output=raw_output,
            artifacts=artifacts or [],
        )

    @classmethod
    def failed(
        cls,
        error_message: str,
        outputs: Optional[dict[str, Any]] = None,
    ) -> "ToolResult":
        """Create a failed result."""
        return cls(
            status=ToolStatus.FAILED,
            error_message=error_message,
            outputs=outputs or {},
        )

    @classmethod
    def timeout(cls, message: str = "Tool execution timed out") -> "ToolResult":
        """Create a timeout result."""
        return cls(
            status=ToolStatus.TIMEOUT,
            error_message=message,
        )


class ToolConfig(BaseModel):
    """Base configuration for tools."""

    enabled: bool = Field(
        default=True,
        description="Whether this tool is enabled"
    )

    timeout_seconds: int = Field(
        default=60,
        ge=1,
        le=3600,
        description="Default timeout for tool execution"
    )

    retry_count: int = Field(
        default=0,
        ge=0,
        le=5,
        description="Number of retry attempts on failure"
    )


class Tool(ABC):
    """
    Abstract base class for all tools in AutoOps Architect.

    Tools are the execution units that perform actual work in workflows.
    Each tool has a unique identifier and can execute with parameters.

    Example:
        >>> class MyTool(Tool):
        ...     @property
        ...     def tool_id(self) -> str:
        ...         return "my_tool"
        ...
        ...     @property
        ...     def description(self) -> str:
        ...         return "My custom tool"
        ...
        ...     async def execute(self, params: dict) -> ToolResult:
        ...         # Do work
        ...         return ToolResult.success({"result": "done"})
    """

    def __init__(self, config: Optional[ToolConfig] = None) -> None:
        """Initialize the tool with optional configuration."""
        self.config = config or ToolConfig()

    @property
    @abstractmethod
    def tool_id(self) -> str:
        """
        Unique identifier for this tool.

        This is used to match nodes in workflows to tools.
        """
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of what this tool does."""
        pass

    @property
    def param_schema(self) -> dict[str, Any]:
        """
        JSON schema for the tool's parameters.

        Override this to document expected parameters.
        """
        return {"type": "object", "properties": {}}

    @abstractmethod
    async def execute(
        self,
        params: dict[str, Any],
        context: Optional[dict[str, Any]] = None,
    ) -> ToolResult:
        """
        Execute the tool with the given parameters.

        Args:
            params: Tool-specific parameters from the workflow node.
            context: Optional execution context (e.g., previous node outputs).

        Returns:
            ToolResult containing the execution outcome.
        """
        pass

    def execute_sync(
        self,
        params: dict[str, Any],
        context: Optional[dict[str, Any]] = None,
    ) -> ToolResult:
        """
        Synchronous wrapper for execute().

        Args:
            params: Tool-specific parameters.
            context: Optional execution context.

        Returns:
            ToolResult containing the execution outcome.
        """
        import asyncio

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        return loop.run_until_complete(self.execute(params, context))

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        """
        Validate parameters against the schema.

        Args:
            params: Parameters to validate.

        Returns:
            List of validation errors (empty if valid).
        """
        # Basic validation - subclasses can override for detailed checks
        errors = []

        schema = self.param_schema
        required = schema.get("required", [])

        for field in required:
            if field not in params:
                errors.append(f"Missing required parameter: {field}")

        return errors


class ToolRegistry:
    """
    Registry for managing available tools.

    The registry allows tools to be registered and retrieved by their ID.
    It also supports checking tool availability and listing all tools.

    Example:
        >>> registry = ToolRegistry()
        >>> registry.register(EchoTool())
        >>> registry.register(LogCollectorTool())
        >>> tool = registry.get("echo")
        >>> result = await tool.execute({"message": "Hello"})
    """

    def __init__(self) -> None:
        """Initialize an empty registry."""
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """
        Register a tool.

        Args:
            tool: The tool instance to register.

        Raises:
            ValueError: If a tool with the same ID is already registered.
        """
        if tool.tool_id in self._tools:
            raise ValueError(f"Tool with ID '{tool.tool_id}' is already registered")
        self._tools[tool.tool_id] = tool

    def register_class(
        self,
        tool_class: Type[Tool],
        config: Optional[ToolConfig] = None,
    ) -> None:
        """
        Register a tool class (instantiates it).

        Args:
            tool_class: The tool class to instantiate and register.
            config: Optional configuration for the tool.
        """
        tool = tool_class(config=config)
        self.register(tool)

    def get(self, tool_id: str) -> Optional[Tool]:
        """
        Get a tool by its ID.

        Args:
            tool_id: The tool identifier.

        Returns:
            The tool instance, or None if not found.
        """
        return self._tools.get(tool_id)

    def has(self, tool_id: str) -> bool:
        """Check if a tool is registered."""
        return tool_id in self._tools

    def list_tools(self) -> list[str]:
        """Get a list of all registered tool IDs."""
        return list(self._tools.keys())

    def list_enabled_tools(self) -> list[str]:
        """Get a list of enabled tool IDs."""
        return [
            tool_id
            for tool_id, tool in self._tools.items()
            if tool.config.enabled
        ]

    def get_tool_info(self) -> list[dict[str, Any]]:
        """
        Get information about all registered tools.

        Returns:
            List of tool information dictionaries.
        """
        return [
            {
                "id": tool.tool_id,
                "description": tool.description,
                "enabled": tool.config.enabled,
                "param_schema": tool.param_schema,
            }
            for tool in self._tools.values()
        ]

    def create_default_registry(self) -> "ToolRegistry":
        """
        Create a registry with all default built-in tools.

        Returns:
            A new registry with built-in tools registered.
        """
        from autoops_architect.tools.builtin import (
            EchoTool,
            LogCollectorTool,
            SummaryTool,
            MetricQueryTool,
            AnalysisTool,
            TraceCollectorTool,
        )
        from autoops_architect.tools.integrations import (
            AutoRCATool,
            MCPTool,
            BrowserMissionTool,
            DatadogTool,
        )

        registry = ToolRegistry()

        # Register built-in tools
        registry.register(EchoTool())
        registry.register(LogCollectorTool())
        registry.register(SummaryTool())
        registry.register(MetricQueryTool())
        registry.register(AnalysisTool())
        registry.register(TraceCollectorTool())

        # Register integration tools (disabled by default until configured)
        registry.register(AutoRCATool(config=ToolConfig(enabled=False)))
        registry.register(MCPTool(config=ToolConfig(enabled=False)))
        registry.register(BrowserMissionTool(config=ToolConfig(enabled=False)))
        registry.register(DatadogTool(config=ToolConfig(enabled=False)))

        return registry


def create_default_registry() -> ToolRegistry:
    """
    Create a registry with all default built-in tools.

    This is a convenience function that creates a ToolRegistry
    and populates it with all built-in tools.

    Returns:
        A ToolRegistry with default tools registered.
    """
    return ToolRegistry().create_default_registry()
