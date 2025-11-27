"""Safety validation for workflows and nodes."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from autoops_architect.models.workflow import Node, WorkflowGraph
from autoops_architect.safety.config import SafetyConfig, get_safety_config


class ValidationSeverity(str, Enum):
    """Severity level for validation issues."""
    ERROR = "error"      # Must be fixed, blocks execution
    WARNING = "warning"  # Should be reviewed, may proceed
    INFO = "info"        # Informational only


@dataclass
class ValidationIssue:
    """A single validation issue."""
    severity: ValidationSeverity
    message: str
    node_id: Optional[str] = None
    field: Optional[str] = None


@dataclass
class ValidationResult:
    """Result of safety validation."""
    valid: bool
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        """Get only error-level issues."""
        return [i for i in self.issues if i.severity == ValidationSeverity.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        """Get only warning-level issues."""
        return [i for i in self.issues if i.severity == ValidationSeverity.WARNING]

    def add_error(
        self,
        message: str,
        node_id: Optional[str] = None,
        field: Optional[str] = None,
    ) -> None:
        """Add an error issue."""
        self.issues.append(ValidationIssue(
            severity=ValidationSeverity.ERROR,
            message=message,
            node_id=node_id,
            field=field,
        ))
        self.valid = False

    def add_warning(
        self,
        message: str,
        node_id: Optional[str] = None,
        field: Optional[str] = None,
    ) -> None:
        """Add a warning issue."""
        self.issues.append(ValidationIssue(
            severity=ValidationSeverity.WARNING,
            message=message,
            node_id=node_id,
            field=field,
        ))

    def add_info(
        self,
        message: str,
        node_id: Optional[str] = None,
        field: Optional[str] = None,
    ) -> None:
        """Add an informational issue."""
        self.issues.append(ValidationIssue(
            severity=ValidationSeverity.INFO,
            message=message,
            node_id=node_id,
            field=field,
        ))


class SafetyValidator:
    """
    Validates workflows and nodes against safety configuration.

    The validator checks:
    - Workflow structure (max nodes, valid edges)
    - Node types against allowed/blocked lists
    - Tool references against allowed/blocked lists
    - Approval requirements
    - Parameter validation
    """

    def __init__(self, config: Optional[SafetyConfig] = None) -> None:
        """
        Initialize the validator.

        Args:
            config: Safety configuration to validate against.
                   Uses global config if not provided.
        """
        self.config = config or get_safety_config()

    def validate_workflow(self, workflow: WorkflowGraph) -> ValidationResult:
        """
        Validate a complete workflow.

        Args:
            workflow: The workflow to validate.

        Returns:
            ValidationResult with any issues found.
        """
        result = ValidationResult(valid=True)

        # Check node count
        if len(workflow.nodes) > self.config.execution.max_nodes_per_workflow:
            result.add_error(
                f"Workflow has {len(workflow.nodes)} nodes, "
                f"exceeds maximum of {self.config.execution.max_nodes_per_workflow}"
            )

        # Check each node
        for node in workflow.nodes:
            node_result = self.validate_node(node)
            result.issues.extend(node_result.issues)
            if not node_result.valid:
                result.valid = False

        # Check edge validity
        node_ids = {n.id for n in workflow.nodes}
        for edge in workflow.edges:
            if edge.from_node_id not in node_ids:
                result.add_error(
                    f"Edge references non-existent node: {edge.from_node_id}",
                    field="edges"
                )
            if edge.to_node_id not in node_ids:
                result.add_error(
                    f"Edge references non-existent node: {edge.to_node_id}",
                    field="edges"
                )

        # Check for cycles (simple check - orphaned nodes after topo sort)
        try:
            workflow.topological_sort()
        except ValueError as e:
            result.add_error(f"Workflow has invalid structure: {e}")

        # Check remediation actions if disabled
        if not self.config.execution.enable_remediation:
            remediation_types = {
                "service_restart",
                "config_update",
                "rollback",
                "scale_action",
            }
            for node in workflow.nodes:
                if node.type.value in remediation_types:
                    result.add_error(
                        f"Remediation action '{node.type.value}' is not allowed",
                        node_id=node.id
                    )

        return result

    def validate_node(self, node: Node) -> ValidationResult:
        """
        Validate a single node.

        Args:
            node: The node to validate.

        Returns:
            ValidationResult with any issues found.
        """
        result = ValidationResult(valid=True)

        # Check node type
        node_type = node.type.value
        if not self.config.node_types.is_allowed(node_type):
            result.add_error(
                f"Node type '{node_type}' is not allowed",
                node_id=node.id
            )

        # Check if node type requires approval
        if self.config.node_types.requires_approval(node_type):
            if not node.requires_human_approval:
                result.add_warning(
                    f"Node type '{node_type}' should require approval",
                    node_id=node.id
                )

        # Check tool
        if node.tool:
            if not self.config.tools.is_allowed(node.tool):
                result.add_error(
                    f"Tool '{node.tool}' is not allowed",
                    node_id=node.id
                )

            if self.config.tools.requires_approval(node.tool):
                if not node.requires_human_approval:
                    result.add_warning(
                        f"Tool '{node.tool}' should require approval",
                        node_id=node.id
                    )

        # Validate parameters
        param_result = self.validate_params(node.params, node.id)
        result.issues.extend(param_result.issues)
        if not param_result.valid:
            result.valid = False

        return result

    def validate_params(
        self,
        params: dict[str, Any],
        node_id: Optional[str] = None,
    ) -> ValidationResult:
        """
        Validate node parameters for safety issues.

        Args:
            params: Parameters to validate.
            node_id: Optional node ID for context.

        Returns:
            ValidationResult with any issues found.
        """
        result = ValidationResult(valid=True)

        # Check for potentially dangerous patterns
        dangerous_patterns = [
            (r';\s*rm\s', "potential command injection (rm)"),
            (r';\s*dd\s', "potential command injection (dd)"),
            (r';\s*wget\s', "potential command injection (wget)"),
            (r';\s*curl\s', "potential command injection (curl)"),
            (r'\$\(', "command substitution"),
            (r'`.*`', "command substitution (backticks)"),
            (r'\.\./\.\./\.\./', "path traversal"),
            (r'/etc/passwd', "sensitive file reference"),
            (r'/etc/shadow', "sensitive file reference"),
            (r'PRIVATE_KEY', "potential credential exposure"),
            (r'SECRET', "potential credential exposure"),
            (r'PASSWORD', "potential credential exposure"),
        ]

        import re

        def check_value(key: str, value: Any) -> None:
            if isinstance(value, str):
                for pattern, description in dangerous_patterns:
                    if re.search(pattern, value, re.IGNORECASE):
                        result.add_warning(
                            f"Parameter '{key}' contains {description}",
                            node_id=node_id,
                            field=key,
                        )
            elif isinstance(value, dict):
                for k, v in value.items():
                    check_value(f"{key}.{k}", v)
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    check_value(f"{key}[{i}]", item)

        for key, value in params.items():
            check_value(key, value)

        return result

    def check_approval_required(
        self,
        node: Node,
        environment: Optional[str] = None,
    ) -> bool:
        """
        Check if a node requires approval.

        Args:
            node: The node to check.
            environment: Optional environment context.

        Returns:
            True if approval is required.
        """
        if not self.config.approval.enabled:
            return False

        # Always require for production if configured
        if (
            self.config.approval.require_for_production
            and environment
            and environment.lower() in ("production", "prod")
        ):
            if node.type.value in (
                "service_restart",
                "config_update",
                "rollback",
                "scale_action",
                "custom_script",
            ):
                return True

        # Check node's own flag
        if node.requires_human_approval:
            return True

        # Check node type
        if self.config.node_types.requires_approval(node.type.value):
            return True

        # Check tool
        if node.tool and self.config.tools.requires_approval(node.tool):
            return True

        return False


def validate_workflow(
    workflow: WorkflowGraph,
    config: Optional[SafetyConfig] = None,
) -> ValidationResult:
    """
    Convenience function to validate a workflow.

    Args:
        workflow: The workflow to validate.
        config: Optional safety configuration.

    Returns:
        ValidationResult with any issues found.
    """
    validator = SafetyValidator(config)
    return validator.validate_workflow(workflow)


def validate_node(
    node: Node,
    config: Optional[SafetyConfig] = None,
) -> ValidationResult:
    """
    Convenience function to validate a node.

    Args:
        node: The node to validate.
        config: Optional safety configuration.

    Returns:
        ValidationResult with any issues found.
    """
    validator = SafetyValidator(config)
    return validator.validate_node(node)


def validate_tool_params(
    params: dict[str, Any],
    config: Optional[SafetyConfig] = None,
) -> ValidationResult:
    """
    Convenience function to validate tool parameters.

    Args:
        params: Parameters to validate.
        config: Optional safety configuration.

    Returns:
        ValidationResult with any issues found.
    """
    validator = SafetyValidator(config)
    return validator.validate_params(params)
