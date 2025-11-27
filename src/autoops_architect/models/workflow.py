"""Workflow graph models representing the execution plan."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


class NodeType(str, Enum):
    """Types of nodes in a workflow graph."""

    # Data collection
    LOG_COLLECTION = "log_collection"
    METRIC_QUERY = "metric_query"
    TRACE_COLLECTION = "trace_collection"

    # Analysis
    RCA_CALL = "rca_call"
    ANALYSIS = "analysis"
    SUMMARY = "summary"

    # Actions
    TICKET_CREATE = "ticket_create"
    TICKET_UPDATE = "ticket_update"
    NOTIFICATION = "notification"
    BROWSER_REPLAY = "browser_replay"

    # Remediation (requires approval by default)
    SERVICE_RESTART = "service_restart"
    CONFIG_UPDATE = "config_update"
    ROLLBACK = "rollback"
    SCALE_ACTION = "scale_action"

    # Utility
    CUSTOM_SCRIPT = "custom_script"
    WAIT = "wait"
    DECISION = "decision"
    HUMAN_REVIEW = "human_review"


# Node types that require human approval by default
APPROVAL_REQUIRED_TYPES = {
    NodeType.SERVICE_RESTART,
    NodeType.CONFIG_UPDATE,
    NodeType.ROLLBACK,
    NodeType.SCALE_ACTION,
    NodeType.CUSTOM_SCRIPT,
}


class Node(BaseModel):
    """
    A single node in the workflow graph representing a step or action.

    Nodes are executed by tools and can have dependencies on other nodes.
    Some node types require human approval before execution.

    Example:
        >>> node = Node(
        ...     id="collect-logs-1",
        ...     name="Collect checkout service logs",
        ...     description="Retrieve logs from the checkout service for the last hour",
        ...     type=NodeType.LOG_COLLECTION,
        ...     tool="log_collector",
        ...     params={"service": "checkout-api", "duration": "1h"}
        ... )
    """

    id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="Unique identifier for this node"
    )

    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Short human-readable name for this step"
    )

    description: str = Field(
        default="",
        max_length=1000,
        description="Detailed description of what this step does"
    )

    type: NodeType = Field(
        ...,
        description="The type of operation this node performs"
    )

    tool: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Identifier of the tool that will execute this node"
    )

    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Tool-specific parameters for execution"
    )

    requires_human_approval: bool = Field(
        default=False,
        description="Whether this node requires explicit human approval before execution"
    )

    timeout_seconds: Optional[int] = Field(
        default=None,
        ge=1,
        le=3600,
        description="Maximum execution time in seconds (default: tool-specific)"
    )

    retry_count: int = Field(
        default=0,
        ge=0,
        le=5,
        description="Number of retry attempts on failure"
    )

    continue_on_failure: bool = Field(
        default=False,
        description="Whether to continue workflow execution if this node fails"
    )

    @model_validator(mode="after")
    def set_approval_for_dangerous_types(self) -> "Node":
        """Automatically require approval for potentially dangerous operations."""
        if self.type in APPROVAL_REQUIRED_TYPES and not self.requires_human_approval:
            # Note: We set this as a default, but user can explicitly override
            object.__setattr__(self, "requires_human_approval", True)
        return self


class Edge(BaseModel):
    """
    An edge connecting two nodes in the workflow graph.

    Edges define dependencies: the target node (to_node_id) will only
    execute after the source node (from_node_id) completes successfully.

    Example:
        >>> edge = Edge(
        ...     from_node_id="collect-logs-1",
        ...     to_node_id="analyze-logs-1"
        ... )
    """

    from_node_id: str = Field(
        ...,
        description="ID of the source node (dependency)"
    )

    to_node_id: str = Field(
        ...,
        description="ID of the target node (depends on source)"
    )

    condition: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional condition expression for conditional edges"
    )

    @field_validator("from_node_id", "to_node_id")
    @classmethod
    def validate_node_id(cls, v: str) -> str:
        """Validate node ID format."""
        if not v or not v.strip():
            raise ValueError("Node ID cannot be empty")
        return v


class WorkflowGraph(BaseModel):
    """
    A directed acyclic graph (DAG) representing an operations workflow.

    The workflow is generated from a Goal and consists of nodes (steps)
    connected by edges (dependencies). It can be serialized to JSON/YAML
    for storage, review, and execution.

    Example:
        >>> workflow = WorkflowGraph(
        ...     id="wf-20241127-001",
        ...     name="Investigate 5xx errors",
        ...     goal_description="Investigate elevated 5xx errors for checkout",
        ...     nodes=[...],
        ...     edges=[...]
        ... )
    """

    id: str = Field(
        ...,
        description="Unique identifier for this workflow"
    )

    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Human-readable name for this workflow"
    )

    goal_description: str = Field(
        ...,
        description="The original goal that generated this workflow"
    )

    nodes: list[Node] = Field(
        default_factory=list,
        description="List of nodes (steps) in the workflow"
    )

    edges: list[Edge] = Field(
        default_factory=list,
        description="List of edges (dependencies) between nodes"
    )

    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Timestamp when the workflow was created"
    )

    version: str = Field(
        default="1.0",
        description="Schema version of this workflow"
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata (e.g., template source, environment)"
    )

    @model_validator(mode="after")
    def validate_graph_structure(self) -> "WorkflowGraph":
        """Validate that the graph is well-formed."""
        node_ids = {node.id for node in self.nodes}

        # Check for duplicate node IDs
        if len(node_ids) != len(self.nodes):
            seen = set()
            duplicates = []
            for node in self.nodes:
                if node.id in seen:
                    duplicates.append(node.id)
                seen.add(node.id)
            raise ValueError(f"Duplicate node IDs found: {duplicates}")

        # Check that all edge references are valid
        for edge in self.edges:
            if edge.from_node_id not in node_ids:
                raise ValueError(
                    f"Edge references non-existent node: {edge.from_node_id}"
                )
            if edge.to_node_id not in node_ids:
                raise ValueError(
                    f"Edge references non-existent node: {edge.to_node_id}"
                )
            if edge.from_node_id == edge.to_node_id:
                raise ValueError(
                    f"Self-referencing edge not allowed: {edge.from_node_id}"
                )

        # Check for cycles using DFS
        if self._has_cycle():
            raise ValueError("Workflow graph contains a cycle - must be a DAG")

        return self

    def _has_cycle(self) -> bool:
        """Check if the graph contains a cycle using DFS."""
        # Build adjacency list
        adj: dict[str, list[str]] = {node.id: [] for node in self.nodes}
        for edge in self.edges:
            adj[edge.from_node_id].append(edge.to_node_id)

        # Track visit state: 0=unvisited, 1=in current path, 2=completed
        state: dict[str, int] = {node.id: 0 for node in self.nodes}

        def dfs(node_id: str) -> bool:
            if state[node_id] == 1:  # Back edge found
                return True
            if state[node_id] == 2:  # Already fully explored
                return False

            state[node_id] = 1  # Mark as in current path

            for neighbor in adj[node_id]:
                if dfs(neighbor):
                    return True

            state[node_id] = 2  # Mark as completed
            return False

        for node_id in adj:
            if state[node_id] == 0:
                if dfs(node_id):
                    return True

        return False

    def get_node(self, node_id: str) -> Optional[Node]:
        """Get a node by its ID."""
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None

    def get_root_nodes(self) -> list[Node]:
        """Get nodes with no incoming edges (start points)."""
        nodes_with_incoming = {edge.to_node_id for edge in self.edges}
        return [node for node in self.nodes if node.id not in nodes_with_incoming]

    def get_dependencies(self, node_id: str) -> list[str]:
        """Get IDs of nodes that must complete before this node."""
        return [edge.from_node_id for edge in self.edges if edge.to_node_id == node_id]

    def get_dependents(self, node_id: str) -> list[str]:
        """Get IDs of nodes that depend on this node."""
        return [edge.to_node_id for edge in self.edges if edge.from_node_id == node_id]

    def topological_sort(self) -> list[Node]:
        """
        Return nodes in topological order (dependencies before dependents).

        Returns:
            List of nodes in execution order.

        Raises:
            ValueError: If the graph contains a cycle.
        """
        # Build adjacency list and in-degree count
        adj: dict[str, list[str]] = {node.id: [] for node in self.nodes}
        in_degree: dict[str, int] = {node.id: 0 for node in self.nodes}

        for edge in self.edges:
            adj[edge.from_node_id].append(edge.to_node_id)
            in_degree[edge.to_node_id] += 1

        # Start with nodes that have no dependencies
        queue = [node_id for node_id, degree in in_degree.items() if degree == 0]
        result: list[Node] = []

        while queue:
            node_id = queue.pop(0)
            node = self.get_node(node_id)
            if node:
                result.append(node)

            for neighbor in adj[node_id]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(result) != len(self.nodes):
            raise ValueError("Graph contains a cycle")

        return result

    def to_yaml(self) -> str:
        """Serialize the workflow to YAML format."""
        return yaml.dump(
            self.model_dump(mode="json"),
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )

    @classmethod
    def from_yaml(cls, yaml_str: str) -> "WorkflowGraph":
        """Deserialize a workflow from YAML format."""
        data = yaml.safe_load(yaml_str)
        return cls.model_validate(data)

    def to_mermaid(self) -> str:
        """
        Generate a Mermaid diagram representation of the workflow.

        Returns:
            Mermaid diagram code as a string.
        """
        lines = ["graph TD"]

        # Add nodes
        for node in self.nodes:
            # Escape special characters in name
            safe_name = node.name.replace('"', "'")
            shape_start, shape_end = ("[", "]")

            # Use different shapes for different node types
            if node.type == NodeType.DECISION:
                shape_start, shape_end = ("{", "}")
            elif node.type == NodeType.HUMAN_REVIEW:
                shape_start, shape_end = ("([", "])")
            elif node.requires_human_approval:
                shape_start, shape_end = ("[[", "]]")

            lines.append(f'    {node.id}{shape_start}"{safe_name}"{shape_end}')

        # Add edges
        for edge in self.edges:
            arrow = "-->"
            if edge.condition:
                arrow = f"-->|{edge.condition}|"
            lines.append(f"    {edge.from_node_id} {arrow} {edge.to_node_id}")

        return "\n".join(lines)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "id": "wf-example-001",
                    "name": "Investigate 5xx Errors",
                    "goal_description": "Investigate elevated 5xx errors for checkout service",
                    "nodes": [
                        {
                            "id": "collect-logs",
                            "name": "Collect checkout service logs",
                            "type": "log_collection",
                            "tool": "log_collector",
                            "params": {"service": "checkout-api", "duration": "1h"}
                        },
                        {
                            "id": "run-rca",
                            "name": "Run root cause analysis",
                            "type": "rca_call",
                            "tool": "autoRCA",
                            "params": {}
                        },
                        {
                            "id": "create-summary",
                            "name": "Create investigation summary",
                            "type": "summary",
                            "tool": "summary",
                            "params": {}
                        }
                    ],
                    "edges": [
                        {"from_node_id": "collect-logs", "to_node_id": "run-rca"},
                        {"from_node_id": "run-rca", "to_node_id": "create-summary"}
                    ]
                }
            ]
        }
    }
