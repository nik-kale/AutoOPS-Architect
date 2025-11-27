"""Safety configuration for AutoOps Architect."""

import os
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field


class ExecutionSafety(BaseModel):
    """Execution-related safety settings."""

    enable_remediation: bool = Field(
        default=False,
        description="Whether to allow remediation actions (restarts, rollbacks, etc.)"
    )

    max_nodes_per_workflow: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of nodes allowed in a workflow"
    )

    default_timeout_seconds: int = Field(
        default=60,
        ge=1,
        le=3600,
        description="Default timeout for individual node execution"
    )

    workflow_timeout_seconds: int = Field(
        default=600,
        ge=1,
        le=36000,
        description="Maximum time for entire workflow execution"
    )

    max_concurrency: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Maximum number of nodes to execute in parallel"
    )

    dry_run_by_default: bool = Field(
        default=False,
        description="Whether to run in dry-run mode by default"
    )


class ToolSafety(BaseModel):
    """Tool-related safety settings."""

    allowed: list[str] = Field(
        default_factory=lambda: [
            "log_collector",
            "metric_query",
            "trace_collector",
            "analysis",
            "summary",
            "echo",
        ],
        description="Whitelist of allowed tools"
    )

    blocked: list[str] = Field(
        default_factory=lambda: [
            "custom_script",
        ],
        description="Blacklist of blocked tools"
    )

    require_approval: list[str] = Field(
        default_factory=lambda: [
            "autoRCA",
            "browserMission",
        ],
        description="Tools that require approval before execution"
    )

    def is_allowed(self, tool_id: str) -> bool:
        """Check if a tool is allowed."""
        if tool_id in self.blocked:
            return False
        if self.allowed and tool_id not in self.allowed:
            return False
        return True

    def requires_approval(self, tool_id: str) -> bool:
        """Check if a tool requires approval."""
        return tool_id in self.require_approval


class NodeTypeSafety(BaseModel):
    """Node type safety settings."""

    allowed: list[str] = Field(
        default_factory=lambda: [
            "log_collection",
            "metric_query",
            "trace_collection",
            "analysis",
            "summary",
            "rca_call",
            "mcp_action",
            "browser_mission",
        ],
        description="Allowed node types"
    )

    blocked: list[str] = Field(
        default_factory=lambda: [
            "service_restart",
            "config_update",
            "rollback",
            "scale_action",
            "custom_script",
        ],
        description="Blocked node types"
    )

    require_approval: list[str] = Field(
        default_factory=lambda: [
            "service_restart",
            "config_update",
            "rollback",
            "scale_action",
            "custom_script",
        ],
        description="Node types that require approval"
    )

    def is_allowed(self, node_type: str) -> bool:
        """Check if a node type is allowed."""
        if node_type in self.blocked:
            return False
        if self.allowed and node_type not in self.allowed:
            return False
        return True

    def requires_approval(self, node_type: str) -> bool:
        """Check if a node type requires approval."""
        return node_type in self.require_approval


class ApprovalSafety(BaseModel):
    """Approval workflow settings."""

    enabled: bool = Field(
        default=True,
        description="Whether approval workflow is enabled"
    )

    timeout_seconds: int = Field(
        default=300,
        ge=0,
        le=86400,
        description="Timeout for approval requests (0 = no timeout)"
    )

    require_for_production: bool = Field(
        default=True,
        description="Always require approval for production environments"
    )

    auto_approve_dry_run: bool = Field(
        default=True,
        description="Auto-approve in dry-run mode"
    )

    notify_channel: Optional[str] = Field(
        default=None,
        description="Channel to notify for approval requests"
    )


class NetworkSafety(BaseModel):
    """Network-related safety settings."""

    allowed_hosts: list[str] = Field(
        default_factory=list,
        description="Allowed hosts (supports wildcards)"
    )

    blocked_hosts: list[str] = Field(
        default_factory=list,
        description="Blocked hosts (supports wildcards)"
    )

    def is_host_allowed(self, host: str) -> bool:
        """Check if a host is allowed."""
        import fnmatch

        # Check blocked first
        for pattern in self.blocked_hosts:
            if fnmatch.fnmatch(host, pattern):
                return False

        # If whitelist is specified, host must match
        if self.allowed_hosts:
            for pattern in self.allowed_hosts:
                if fnmatch.fnmatch(host, pattern):
                    return True
            return False

        return True


class SafetyConfig(BaseModel):
    """
    Complete safety configuration for AutoOps Architect.

    This configuration controls what operations are allowed,
    what requires approval, and what is blocked entirely.
    """

    version: str = Field(
        default="1.0",
        description="Config version"
    )

    execution: ExecutionSafety = Field(
        default_factory=ExecutionSafety,
        description="Execution safety settings"
    )

    tools: ToolSafety = Field(
        default_factory=ToolSafety,
        description="Tool safety settings"
    )

    node_types: NodeTypeSafety = Field(
        default_factory=NodeTypeSafety,
        description="Node type safety settings"
    )

    approval: ApprovalSafety = Field(
        default_factory=ApprovalSafety,
        description="Approval workflow settings"
    )

    network: NetworkSafety = Field(
        default_factory=NetworkSafety,
        description="Network safety settings"
    )

    def to_yaml(self) -> str:
        """Export configuration to YAML."""
        data = self.model_dump(mode="json")
        return yaml.dump(data, default_flow_style=False, sort_keys=False)

    @classmethod
    def from_yaml(cls, yaml_content: str) -> "SafetyConfig":
        """Load configuration from YAML."""
        data = yaml.safe_load(yaml_content)
        return cls.model_validate(data)


def get_default_safety_config() -> SafetyConfig:
    """
    Get the default safety configuration.

    This is a restrictive configuration suitable for most use cases.

    Returns:
        Default SafetyConfig instance.
    """
    return SafetyConfig()


def load_safety_config(path: Optional[str] = None) -> SafetyConfig:
    """
    Load safety configuration from file or environment.

    Precedence:
    1. Explicit path argument
    2. AUTOOPS_SAFETY_CONFIG environment variable
    3. ~/.autoops/safety.yaml
    4. Default configuration

    Args:
        path: Optional explicit path to config file.

    Returns:
        Loaded SafetyConfig instance.
    """
    config_path = path or os.environ.get("AUTOOPS_SAFETY_CONFIG")

    if config_path is None:
        default_path = Path.home() / ".autoops" / "safety.yaml"
        if default_path.exists():
            config_path = str(default_path)

    if config_path:
        config_file = Path(config_path)
        if config_file.exists():
            try:
                content = config_file.read_text()
                config = SafetyConfig.from_yaml(content)

                # Override with environment variables
                config = _apply_env_overrides(config)
                return config
            except Exception as e:
                # Log warning but fall back to default
                import logging
                logging.getLogger(__name__).warning(
                    f"Failed to load safety config from {config_path}: {e}"
                )

    return _apply_env_overrides(get_default_safety_config())


def _apply_env_overrides(config: SafetyConfig) -> SafetyConfig:
    """Apply environment variable overrides to config."""
    # AUTOOPS_ENABLE_REMEDIATION
    if os.environ.get("AUTOOPS_ENABLE_REMEDIATION", "").lower() == "true":
        config.execution.enable_remediation = True

    # AUTOOPS_DRY_RUN
    if os.environ.get("AUTOOPS_DRY_RUN", "").lower() == "true":
        config.execution.dry_run_by_default = True

    # AUTOOPS_REQUIRE_APPROVAL
    if os.environ.get("AUTOOPS_REQUIRE_APPROVAL", "").lower() == "true":
        config.approval.enabled = True

    return config


# Global safety config instance (lazy loaded)
_global_config: Optional[SafetyConfig] = None


def get_safety_config() -> SafetyConfig:
    """
    Get the global safety configuration.

    Loads from file/environment on first call, then caches.

    Returns:
        Global SafetyConfig instance.
    """
    global _global_config
    if _global_config is None:
        _global_config = load_safety_config()
    return _global_config


def set_safety_config(config: SafetyConfig) -> None:
    """
    Set the global safety configuration.

    Args:
        config: SafetyConfig to use globally.
    """
    global _global_config
    _global_config = config
