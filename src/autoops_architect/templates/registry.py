"""Template registry and template model definitions."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from autoops_architect.models.workflow import Edge, Node, NodeType, WorkflowGraph


class WorkflowTemplate(BaseModel):
    """
    A workflow template for common operations scenarios.

    Templates provide pre-defined workflow structures that can be
    adapted to specific goals. They include placeholders for
    service names, parameters, and other dynamic values.
    """

    id: str = Field(
        ...,
        description="Unique identifier for the template"
    )

    name: str = Field(
        ...,
        description="Human-readable template name"
    )

    description: str = Field(
        ...,
        description="Description of what this template is for"
    )

    category: str = Field(
        default="general",
        description="Template category (error_investigation, latency, security, etc.)"
    )

    tags: list[str] = Field(
        default_factory=list,
        description="Tags for searching and filtering"
    )

    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Template parameters with default values"
    )

    nodes: list[Node] = Field(
        ...,
        description="Template nodes (may contain placeholders)"
    )

    edges: list[Edge] = Field(
        ...,
        description="Template edges"
    )

    author: Optional[str] = Field(
        default=None,
        description="Template author"
    )

    version: str = Field(
        default="1.0",
        description="Template version"
    )

    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When the template was created"
    )

    def instantiate(
        self,
        goal_description: str,
        service: Optional[str] = None,
        **kwargs: Any,
    ) -> WorkflowGraph:
        """
        Create a WorkflowGraph instance from this template.

        Args:
            goal_description: The goal this workflow addresses.
            service: Optional service name to substitute.
            **kwargs: Additional parameter overrides.

        Returns:
            A WorkflowGraph ready for execution or further customization.
        """
        import uuid

        # Merge parameters with defaults
        params = dict(self.parameters)
        if service:
            params["service"] = service
        params.update(kwargs)

        # Create nodes with substitutions
        instantiated_nodes = []
        for node in self.nodes:
            node_dict = node.model_dump()

            # Substitute service in params
            if "params" in node_dict:
                for key, value in node_dict["params"].items():
                    if isinstance(value, str) and "{{service}}" in value:
                        node_dict["params"][key] = value.replace(
                            "{{service}}", params.get("service", "unknown-service")
                        )
                    elif value == "{{service}}":
                        node_dict["params"][key] = params.get("service", "unknown-service")

            # Substitute in name and description
            if "{{service}}" in node_dict.get("name", ""):
                node_dict["name"] = node_dict["name"].replace(
                    "{{service}}", params.get("service", "service")
                )
            if "{{service}}" in node_dict.get("description", ""):
                node_dict["description"] = node_dict["description"].replace(
                    "{{service}}", params.get("service", "service")
                )

            instantiated_nodes.append(Node.model_validate(node_dict))

        # Create the workflow
        workflow = WorkflowGraph(
            id=f"wf-{uuid.uuid4().hex[:8]}",
            name=f"{self.name} - {params.get('service', 'Service')}",
            goal_description=goal_description,
            nodes=instantiated_nodes,
            edges=list(self.edges),
            metadata={
                "template_id": self.id,
                "template_version": self.version,
                "instantiated_at": datetime.utcnow().isoformat(),
                "parameters": params,
            },
        )

        return workflow


class TemplateRegistry:
    """
    Registry for managing workflow templates.

    The registry provides methods to register, retrieve, and search
    templates by various criteria.
    """

    def __init__(self) -> None:
        """Initialize an empty registry."""
        self._templates: dict[str, WorkflowTemplate] = {}

    def register(self, template: WorkflowTemplate) -> None:
        """Register a template."""
        if template.id in self._templates:
            raise ValueError(f"Template '{template.id}' already registered")
        self._templates[template.id] = template

    def get(self, template_id: str) -> Optional[WorkflowTemplate]:
        """Get a template by ID."""
        return self._templates.get(template_id)

    def list(self, category: Optional[str] = None) -> list[WorkflowTemplate]:
        """
        List all templates, optionally filtered by category.

        Args:
            category: Optional category to filter by.

        Returns:
            List of templates.
        """
        templates = list(self._templates.values())
        if category:
            templates = [t for t in templates if t.category == category]
        return templates

    def search(
        self,
        query: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> list[WorkflowTemplate]:
        """
        Search templates by query, category, or tags.

        Args:
            query: Search in name and description.
            category: Filter by category.
            tags: Filter by tags (any match).

        Returns:
            List of matching templates.
        """
        results = list(self._templates.values())

        if category:
            results = [t for t in results if t.category == category]

        if tags:
            tag_set = set(t.lower() for t in tags)
            results = [
                t for t in results
                if any(tag.lower() in tag_set for tag in t.tags)
            ]

        if query:
            query_lower = query.lower()
            results = [
                t for t in results
                if query_lower in t.name.lower() or query_lower in t.description.lower()
            ]

        return results

    def list_categories(self) -> list[str]:
        """Get all unique categories."""
        categories = set(t.category for t in self._templates.values())
        return sorted(categories)


def get_builtin_templates() -> list[WorkflowTemplate]:
    """
    Get all built-in workflow templates.

    Returns:
        List of pre-defined templates.
    """
    return [
        # Template 1: Error Rate Investigation
        WorkflowTemplate(
            id="error-rate-investigation",
            name="Error Rate Investigation",
            description="Investigate elevated error rates for a service",
            category="error_investigation",
            tags=["5xx", "errors", "investigation", "production"],
            parameters={
                "service": "{{service}}",
                "duration": "2h",
                "error_threshold": 5.0,
            },
            nodes=[
                Node(
                    id="collect-error-logs",
                    name="Collect {{service}} error logs",
                    description="Retrieve error logs from the affected service",
                    type=NodeType.LOG_COLLECTION,
                    tool="log_collector",
                    params={"service": "{{service}}", "duration": "2h", "level": "error"},
                ),
                Node(
                    id="query-error-metrics",
                    name="Query error rate metrics",
                    description="Get error rate metrics from monitoring",
                    type=NodeType.METRIC_QUERY,
                    tool="metric_query",
                    params={"service": "{{service}}", "metric_name": "http_errors_total"},
                ),
                Node(
                    id="analyze-errors",
                    name="Analyze error patterns",
                    description="Identify patterns in the error logs",
                    type=NodeType.ANALYSIS,
                    tool="log_analyzer",
                    params={"analysis_type": "error_patterns"},
                ),
                Node(
                    id="run-rca",
                    name="Root cause analysis",
                    description="Run automated root cause analysis",
                    type=NodeType.RCA_CALL,
                    tool="autoRCA",
                    params={},
                ),
                Node(
                    id="generate-summary",
                    name="Generate investigation summary",
                    description="Create a summary of findings and recommendations",
                    type=NodeType.SUMMARY,
                    tool="summary",
                    params={"format": "markdown", "include_recommendations": True},
                ),
            ],
            edges=[
                Edge(from_node_id="collect-error-logs", to_node_id="analyze-errors"),
                Edge(from_node_id="query-error-metrics", to_node_id="analyze-errors"),
                Edge(from_node_id="analyze-errors", to_node_id="run-rca"),
                Edge(from_node_id="run-rca", to_node_id="generate-summary"),
            ],
            author="autoops-architect",
        ),

        # Template 2: Latency Investigation
        WorkflowTemplate(
            id="latency-investigation",
            name="Latency Investigation",
            description="Investigate high latency or slow response times",
            category="performance",
            tags=["latency", "slow", "performance", "p99"],
            parameters={
                "service": "{{service}}",
                "duration": "6h",
                "latency_threshold_ms": 1000,
            },
            nodes=[
                Node(
                    id="query-latency-metrics",
                    name="Query latency metrics for {{service}}",
                    description="Get P50, P95, P99 latency metrics",
                    type=NodeType.METRIC_QUERY,
                    tool="metric_query",
                    params={
                        "service": "{{service}}",
                        "metric_name": "http_request_duration_seconds",
                    },
                ),
                Node(
                    id="collect-slow-logs",
                    name="Collect slow request logs",
                    description="Gather logs for requests exceeding latency threshold",
                    type=NodeType.LOG_COLLECTION,
                    tool="log_collector",
                    params={"service": "{{service}}", "duration": "6h"},
                ),
                Node(
                    id="check-dependencies",
                    name="Check dependency latencies",
                    description="Query metrics for downstream dependencies",
                    type=NodeType.METRIC_QUERY,
                    tool="metric_query",
                    params={"service": "{{service}}", "metric_name": "dependency_latency"},
                ),
                Node(
                    id="analyze-latency",
                    name="Analyze latency patterns",
                    description="Identify bottlenecks and patterns",
                    type=NodeType.ANALYSIS,
                    tool="log_analyzer",
                    params={"analysis_type": "latency"},
                ),
                Node(
                    id="generate-summary",
                    name="Generate performance summary",
                    description="Summary of latency findings",
                    type=NodeType.SUMMARY,
                    tool="summary",
                    params={"format": "detailed"},
                ),
            ],
            edges=[
                Edge(from_node_id="query-latency-metrics", to_node_id="analyze-latency"),
                Edge(from_node_id="collect-slow-logs", to_node_id="analyze-latency"),
                Edge(from_node_id="check-dependencies", to_node_id="analyze-latency"),
                Edge(from_node_id="analyze-latency", to_node_id="generate-summary"),
            ],
            author="autoops-architect",
        ),

        # Template 3: Login/Auth Failures
        WorkflowTemplate(
            id="auth-failure-investigation",
            name="Authentication Failure Investigation",
            description="Investigate recurring authentication or login failures",
            category="security",
            tags=["auth", "login", "failures", "security"],
            parameters={
                "service": "auth-service",
                "duration": "24h",
            },
            nodes=[
                Node(
                    id="collect-auth-logs",
                    name="Collect authentication logs",
                    description="Gather auth-related logs",
                    type=NodeType.LOG_COLLECTION,
                    tool="log_collector",
                    params={"service": "{{service}}", "duration": "24h"},
                ),
                Node(
                    id="query-auth-metrics",
                    name="Query auth failure metrics",
                    description="Get authentication failure rates",
                    type=NodeType.METRIC_QUERY,
                    tool="metric_query",
                    params={"service": "{{service}}", "metric_name": "auth_failures_total"},
                ),
                Node(
                    id="analyze-failures",
                    name="Analyze failure patterns",
                    description="Identify patterns in authentication failures",
                    type=NodeType.ANALYSIS,
                    tool="log_analyzer",
                    params={"analysis_type": "error_patterns"},
                ),
                Node(
                    id="check-identity-provider",
                    name="Check identity provider status",
                    description="Verify external identity providers are healthy",
                    type=NodeType.METRIC_QUERY,
                    tool="metric_query",
                    params={"service": "identity-provider", "metric_name": "health_status"},
                ),
                Node(
                    id="generate-summary",
                    name="Generate security summary",
                    description="Summary of authentication findings",
                    type=NodeType.SUMMARY,
                    tool="summary",
                    params={"format": "markdown"},
                ),
            ],
            edges=[
                Edge(from_node_id="collect-auth-logs", to_node_id="analyze-failures"),
                Edge(from_node_id="query-auth-metrics", to_node_id="analyze-failures"),
                Edge(from_node_id="check-identity-provider", to_node_id="analyze-failures"),
                Edge(from_node_id="analyze-failures", to_node_id="generate-summary"),
            ],
            author="autoops-architect",
        ),

        # Template 4: Database Connection Issues
        WorkflowTemplate(
            id="db-connection-investigation",
            name="Database Connection Investigation",
            description="Investigate database connection pool exhaustion or connection issues",
            category="database",
            tags=["database", "connection", "pool", "exhaustion"],
            parameters={
                "service": "{{service}}",
                "database": "primary-db",
                "duration": "2h",
            },
            nodes=[
                Node(
                    id="query-pool-metrics",
                    name="Query connection pool metrics",
                    description="Get database connection pool statistics",
                    type=NodeType.METRIC_QUERY,
                    tool="metric_query",
                    params={"service": "{{service}}", "metric_name": "db_pool_connections"},
                ),
                Node(
                    id="collect-db-logs",
                    name="Collect database-related logs",
                    description="Gather connection error logs",
                    type=NodeType.LOG_COLLECTION,
                    tool="log_collector",
                    params={"service": "{{service}}", "duration": "2h"},
                ),
                Node(
                    id="query-query-latency",
                    name="Query database query latency",
                    description="Check for slow queries",
                    type=NodeType.METRIC_QUERY,
                    tool="metric_query",
                    params={"service": "{{service}}", "metric_name": "db_query_duration"},
                ),
                Node(
                    id="analyze-connections",
                    name="Analyze connection patterns",
                    description="Identify connection leaks or bottlenecks",
                    type=NodeType.ANALYSIS,
                    tool="log_analyzer",
                    params={"analysis_type": "error_patterns"},
                ),
                Node(
                    id="generate-summary",
                    name="Generate database summary",
                    description="Summary of database connection findings",
                    type=NodeType.SUMMARY,
                    tool="summary",
                    params={"format": "detailed"},
                ),
            ],
            edges=[
                Edge(from_node_id="query-pool-metrics", to_node_id="analyze-connections"),
                Edge(from_node_id="collect-db-logs", to_node_id="analyze-connections"),
                Edge(from_node_id="query-query-latency", to_node_id="analyze-connections"),
                Edge(from_node_id="analyze-connections", to_node_id="generate-summary"),
            ],
            author="autoops-architect",
        ),

        # Template 5: Memory/Resource Issues
        WorkflowTemplate(
            id="resource-investigation",
            name="Resource Exhaustion Investigation",
            description="Investigate memory leaks or resource exhaustion",
            category="resources",
            tags=["memory", "cpu", "resources", "oom", "leak"],
            parameters={
                "service": "{{service}}",
                "duration": "24h",
            },
            nodes=[
                Node(
                    id="query-memory-metrics",
                    name="Query memory metrics for {{service}}",
                    description="Get memory usage over time",
                    type=NodeType.METRIC_QUERY,
                    tool="metric_query",
                    params={"service": "{{service}}", "metric_name": "memory_usage_bytes"},
                ),
                Node(
                    id="query-cpu-metrics",
                    name="Query CPU metrics",
                    description="Get CPU utilization",
                    type=NodeType.METRIC_QUERY,
                    tool="metric_query",
                    params={"service": "{{service}}", "metric_name": "cpu_usage_percent"},
                ),
                Node(
                    id="collect-oom-logs",
                    name="Collect OOM/resource logs",
                    description="Gather out-of-memory and resource-related logs",
                    type=NodeType.LOG_COLLECTION,
                    tool="log_collector",
                    params={"service": "{{service}}", "duration": "24h"},
                ),
                Node(
                    id="analyze-resources",
                    name="Analyze resource trends",
                    description="Identify memory leaks or resource spikes",
                    type=NodeType.ANALYSIS,
                    tool="log_analyzer",
                    params={"analysis_type": "anomaly_detection"},
                ),
                Node(
                    id="generate-summary",
                    name="Generate resource summary",
                    description="Summary of resource utilization findings",
                    type=NodeType.SUMMARY,
                    tool="summary",
                    params={"format": "markdown"},
                ),
            ],
            edges=[
                Edge(from_node_id="query-memory-metrics", to_node_id="analyze-resources"),
                Edge(from_node_id="query-cpu-metrics", to_node_id="analyze-resources"),
                Edge(from_node_id="collect-oom-logs", to_node_id="analyze-resources"),
                Edge(from_node_id="analyze-resources", to_node_id="generate-summary"),
            ],
            author="autoops-architect",
        ),
    ]


def create_default_template_registry() -> TemplateRegistry:
    """
    Create a registry with all built-in templates.

    Returns:
        A TemplateRegistry pre-populated with built-in templates.
    """
    registry = TemplateRegistry()
    for template in get_builtin_templates():
        registry.register(template)
    return registry
