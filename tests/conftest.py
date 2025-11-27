"""Shared test fixtures for AutoOps Architect."""

import pytest

from autoops_architect.llm.base import LLMConfig, LLMProvider
from autoops_architect.llm.providers import MockLLMClient
from autoops_architect.models.goal import Environment, Goal, Priority
from autoops_architect.models.workflow import Edge, Node, NodeType, WorkflowGraph
from autoops_architect.tools.base import ToolRegistry
from autoops_architect.tools.builtin import EchoTool, LogCollectorTool, SummaryTool


@pytest.fixture
def sample_goal() -> Goal:
    """Create a sample Goal for testing."""
    return Goal(
        description="Investigate elevated 5xx errors for the checkout service in prod",
        services=["checkout-api", "payments"],
        environment=Environment.PRODUCTION,
        priority=Priority.HIGH,
        tags=["error-rate", "checkout"],
        context="Started seeing increased errors around 2pm UTC",
    )


@pytest.fixture
def simple_goal() -> Goal:
    """Create a simple Goal for testing."""
    return Goal(
        description="Check the status of the auth service",
        services=["auth-service"],
    )


@pytest.fixture
def sample_workflow() -> WorkflowGraph:
    """Create a sample WorkflowGraph for testing."""
    return WorkflowGraph(
        id="wf-test-001",
        name="Test Investigation Workflow",
        goal_description="Investigate elevated 5xx errors",
        nodes=[
            Node(
                id="collect-logs",
                name="Collect checkout service logs",
                description="Retrieve logs from the checkout service",
                type=NodeType.LOG_COLLECTION,
                tool="log_collector",
                params={"service": "checkout-api", "duration": "1h"},
            ),
            Node(
                id="analyze-logs",
                name="Analyze logs for errors",
                description="Analyze collected logs",
                type=NodeType.ANALYSIS,
                tool="log_analyzer",
                params={"analysis_type": "error_patterns"},
            ),
            Node(
                id="create-summary",
                name="Create investigation summary",
                description="Generate a summary report",
                type=NodeType.SUMMARY,
                tool="summary",
                params={"format": "brief"},
            ),
        ],
        edges=[
            Edge(from_node_id="collect-logs", to_node_id="analyze-logs"),
            Edge(from_node_id="analyze-logs", to_node_id="create-summary"),
        ],
    )


@pytest.fixture
def parallel_workflow() -> WorkflowGraph:
    """Create a workflow with parallel branches for testing."""
    return WorkflowGraph(
        id="wf-parallel-001",
        name="Parallel Investigation",
        goal_description="Investigate with parallel data collection",
        nodes=[
            Node(
                id="start",
                name="Start",
                type=NodeType.ANALYSIS,
                tool="echo",
                params={},
            ),
            Node(
                id="collect-logs",
                name="Collect logs",
                type=NodeType.LOG_COLLECTION,
                tool="log_collector",
                params={},
            ),
            Node(
                id="collect-metrics",
                name="Collect metrics",
                type=NodeType.METRIC_QUERY,
                tool="metric_query",
                params={},
            ),
            Node(
                id="merge",
                name="Merge results",
                type=NodeType.SUMMARY,
                tool="summary",
                params={},
            ),
        ],
        edges=[
            Edge(from_node_id="start", to_node_id="collect-logs"),
            Edge(from_node_id="start", to_node_id="collect-metrics"),
            Edge(from_node_id="collect-logs", to_node_id="merge"),
            Edge(from_node_id="collect-metrics", to_node_id="merge"),
        ],
    )


@pytest.fixture
def mock_llm_client() -> MockLLMClient:
    """Create a mock LLM client for testing."""
    config = LLMConfig(provider=LLMProvider.MOCK)
    return MockLLMClient(config)


@pytest.fixture
def tool_registry() -> ToolRegistry:
    """Create a tool registry with basic tools for testing."""
    registry = ToolRegistry()
    registry.register(EchoTool())
    registry.register(LogCollectorTool())
    registry.register(SummaryTool())
    return registry


@pytest.fixture
def mock_workflow_json() -> dict:
    """Return a mock workflow JSON response from LLM."""
    return {
        "id": "wf-mock-001",
        "name": "Mock Investigation Workflow",
        "goal_description": "Investigate the issue",
        "nodes": [
            {
                "id": "collect-logs",
                "name": "Collect service logs",
                "description": "Collect logs from the affected service",
                "type": "log_collection",
                "tool": "log_collector",
                "params": {"duration": "1h"},
                "requires_human_approval": False,
            },
            {
                "id": "analyze-logs",
                "name": "Analyze logs for errors",
                "description": "Analyze collected logs",
                "type": "analysis",
                "tool": "log_analyzer",
                "params": {},
                "requires_human_approval": False,
            },
            {
                "id": "create-summary",
                "name": "Create summary",
                "description": "Generate summary",
                "type": "summary",
                "tool": "summary",
                "params": {},
                "requires_human_approval": False,
            },
        ],
        "edges": [
            {"from_node_id": "collect-logs", "to_node_id": "analyze-logs"},
            {"from_node_id": "analyze-logs", "to_node_id": "create-summary"},
        ],
    }
