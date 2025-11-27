"""Tests for data models."""

import json

import pytest
from pydantic import ValidationError

from autoops_architect.models.goal import Environment, Goal, Priority
from autoops_architect.models.workflow import Edge, Node, NodeType, WorkflowGraph
from autoops_architect.models.execution import (
    ExecutionStatus,
    NodeResult,
    WorkflowRunResult,
)
from autoops_architect.models.memory import MemoryEntry, WorkflowMemory


class TestGoal:
    """Tests for the Goal model."""

    def test_goal_creation(self):
        """Test creating a basic goal."""
        goal = Goal(description="Test goal for investigation")
        assert goal.description == "Test goal for investigation"
        assert goal.services == []
        assert goal.environment == Environment.UNKNOWN
        assert goal.priority == Priority.UNKNOWN

    def test_goal_with_all_fields(self, sample_goal):
        """Test goal with all fields populated."""
        assert sample_goal.description.startswith("Investigate")
        assert "checkout-api" in sample_goal.services
        assert sample_goal.environment == Environment.PRODUCTION
        assert sample_goal.priority == Priority.HIGH
        assert "error-rate" in sample_goal.tags

    def test_goal_validation_min_length(self):
        """Test that goal description has minimum length."""
        with pytest.raises(ValidationError):
            Goal(description="short")

    def test_goal_to_prompt_context(self, sample_goal):
        """Test converting goal to prompt context."""
        context = sample_goal.to_prompt_context()
        assert "Goal:" in context
        assert "checkout-api" in context
        assert "production" in context

    def test_goal_get_keywords(self, sample_goal):
        """Test extracting keywords from goal."""
        keywords = sample_goal.get_keywords()
        assert "checkout-api" in keywords
        assert "error-rate" in keywords
        assert "production" in keywords


class TestNode:
    """Tests for the Node model."""

    def test_node_creation(self):
        """Test creating a basic node."""
        node = Node(
            id="test-node",
            name="Test Node",
            type=NodeType.LOG_COLLECTION,
            tool="log_collector",
        )
        assert node.id == "test-node"
        assert node.type == NodeType.LOG_COLLECTION
        assert node.requires_human_approval is False

    def test_node_id_validation(self):
        """Test node ID pattern validation."""
        # Valid IDs
        Node(id="valid-id", name="Test", type=NodeType.ANALYSIS, tool="echo")
        Node(id="valid_id_123", name="Test", type=NodeType.ANALYSIS, tool="echo")

        # Invalid IDs
        with pytest.raises(ValidationError):
            Node(id="invalid id", name="Test", type=NodeType.ANALYSIS, tool="echo")

    def test_dangerous_node_requires_approval(self):
        """Test that dangerous node types require approval."""
        node = Node(
            id="restart",
            name="Restart Service",
            type=NodeType.SERVICE_RESTART,
            tool="shell",
        )
        assert node.requires_human_approval is True

    def test_node_params(self):
        """Test node parameters."""
        node = Node(
            id="test",
            name="Test",
            type=NodeType.LOG_COLLECTION,
            tool="log_collector",
            params={"service": "my-service", "duration": "1h"},
        )
        assert node.params["service"] == "my-service"


class TestEdge:
    """Tests for the Edge model."""

    def test_edge_creation(self):
        """Test creating an edge."""
        edge = Edge(from_node_id="node-1", to_node_id="node-2")
        assert edge.from_node_id == "node-1"
        assert edge.to_node_id == "node-2"
        assert edge.condition is None

    def test_edge_with_condition(self):
        """Test edge with a condition."""
        edge = Edge(
            from_node_id="node-1",
            to_node_id="node-2",
            condition="status == 'error'",
        )
        assert edge.condition == "status == 'error'"


class TestWorkflowGraph:
    """Tests for the WorkflowGraph model."""

    def test_workflow_creation(self, sample_workflow):
        """Test creating a workflow."""
        assert sample_workflow.id == "wf-test-001"
        assert len(sample_workflow.nodes) == 3
        assert len(sample_workflow.edges) == 2

    def test_workflow_duplicate_node_ids(self):
        """Test that duplicate node IDs are rejected."""
        with pytest.raises(ValidationError):
            WorkflowGraph(
                id="wf-test",
                name="Test",
                goal_description="Test goal",
                nodes=[
                    Node(id="same-id", name="Node 1", type=NodeType.ANALYSIS, tool="echo"),
                    Node(id="same-id", name="Node 2", type=NodeType.ANALYSIS, tool="echo"),
                ],
                edges=[],
            )

    def test_workflow_invalid_edge_reference(self):
        """Test that edges must reference valid nodes."""
        with pytest.raises(ValidationError):
            WorkflowGraph(
                id="wf-test",
                name="Test",
                goal_description="Test goal",
                nodes=[
                    Node(id="node-1", name="Node 1", type=NodeType.ANALYSIS, tool="echo"),
                ],
                edges=[
                    Edge(from_node_id="node-1", to_node_id="nonexistent"),
                ],
            )

    def test_workflow_cycle_detection(self):
        """Test that cycles are detected and rejected."""
        with pytest.raises(ValidationError):
            WorkflowGraph(
                id="wf-test",
                name="Test",
                goal_description="Test goal",
                nodes=[
                    Node(id="a", name="A", type=NodeType.ANALYSIS, tool="echo"),
                    Node(id="b", name="B", type=NodeType.ANALYSIS, tool="echo"),
                    Node(id="c", name="C", type=NodeType.ANALYSIS, tool="echo"),
                ],
                edges=[
                    Edge(from_node_id="a", to_node_id="b"),
                    Edge(from_node_id="b", to_node_id="c"),
                    Edge(from_node_id="c", to_node_id="a"),  # Creates cycle
                ],
            )

    def test_workflow_topological_sort(self, sample_workflow):
        """Test topological sorting of nodes."""
        sorted_nodes = sample_workflow.topological_sort()
        node_ids = [n.id for n in sorted_nodes]

        # collect-logs must come before analyze-logs
        assert node_ids.index("collect-logs") < node_ids.index("analyze-logs")
        # analyze-logs must come before create-summary
        assert node_ids.index("analyze-logs") < node_ids.index("create-summary")

    def test_workflow_get_dependencies(self, sample_workflow):
        """Test getting node dependencies."""
        deps = sample_workflow.get_dependencies("analyze-logs")
        assert "collect-logs" in deps

    def test_workflow_get_root_nodes(self, sample_workflow):
        """Test getting root nodes."""
        roots = sample_workflow.get_root_nodes()
        assert len(roots) == 1
        assert roots[0].id == "collect-logs"

    def test_workflow_to_yaml(self, sample_workflow):
        """Test YAML serialization."""
        yaml_str = sample_workflow.to_yaml()
        assert "wf-test-001" in yaml_str
        assert "collect-logs" in yaml_str

    def test_workflow_from_yaml(self, sample_workflow):
        """Test YAML deserialization."""
        yaml_str = sample_workflow.to_yaml()
        restored = WorkflowGraph.from_yaml(yaml_str)
        assert restored.id == sample_workflow.id
        assert len(restored.nodes) == len(sample_workflow.nodes)

    def test_workflow_to_mermaid(self, sample_workflow):
        """Test Mermaid diagram generation."""
        mermaid = sample_workflow.to_mermaid()
        assert "graph TD" in mermaid
        assert "collect-logs" in mermaid
        assert "-->" in mermaid


class TestNodeResult:
    """Tests for the NodeResult model."""

    def test_node_result_creation(self):
        """Test creating a node result."""
        result = NodeResult(node_id="test-node")
        assert result.node_id == "test-node"
        assert result.status == ExecutionStatus.PENDING
        assert result.is_terminal is False

    def test_node_result_mark_success(self):
        """Test marking a result as successful."""
        result = NodeResult(node_id="test")
        result.mark_started()
        result.mark_success({"key": "value"})

        assert result.status == ExecutionStatus.SUCCESS
        assert result.outputs["key"] == "value"
        assert result.is_terminal is True

    def test_node_result_mark_failed(self):
        """Test marking a result as failed."""
        result = NodeResult(node_id="test")
        result.mark_started()
        result.mark_failed("Something went wrong")

        assert result.status == ExecutionStatus.FAILED
        assert result.error_message == "Something went wrong"
        assert result.is_terminal is True

    def test_node_result_duration(self):
        """Test duration calculation."""
        result = NodeResult(node_id="test")
        result.mark_started()
        result.mark_success()

        assert result.duration_seconds is not None
        assert result.duration_seconds >= 0


class TestWorkflowRunResult:
    """Tests for the WorkflowRunResult model."""

    def test_run_result_creation(self):
        """Test creating a run result."""
        result = WorkflowRunResult(
            workflow_id="wf-test",
            goal_description="Test goal",
        )
        assert result.workflow_id == "wf-test"
        assert result.overall_status == ExecutionStatus.PENDING

    def test_run_result_compute_status(self):
        """Test computing overall status."""
        result = WorkflowRunResult(
            workflow_id="wf-test",
            goal_description="Test",
            node_results=[
                NodeResult(node_id="a", status=ExecutionStatus.SUCCESS),
                NodeResult(node_id="b", status=ExecutionStatus.SUCCESS),
            ],
        )
        assert result.compute_overall_status() == ExecutionStatus.SUCCESS

    def test_run_result_with_failure(self):
        """Test status with a failed node."""
        result = WorkflowRunResult(
            workflow_id="wf-test",
            goal_description="Test",
            node_results=[
                NodeResult(node_id="a", status=ExecutionStatus.SUCCESS),
                NodeResult(node_id="b", status=ExecutionStatus.FAILED),
            ],
        )
        assert result.compute_overall_status() == ExecutionStatus.FAILED
        assert result.failed_count == 1

    def test_run_result_generate_summary(self):
        """Test summary generation."""
        result = WorkflowRunResult(
            workflow_id="wf-test",
            goal_description="Test goal",
            node_results=[
                NodeResult(node_id="a", status=ExecutionStatus.SUCCESS),
            ],
        )
        summary = result.generate_summary()
        assert "wf-test" in summary
        assert "Test goal" in summary


class TestMemoryEntry:
    """Tests for the MemoryEntry model."""

    def test_memory_entry_creation(self):
        """Test creating a memory entry."""
        entry = MemoryEntry(
            id="mem-001",
            goal_description="Test goal",
            workflow_id="wf-001",
            outcome_status="success",
        )
        assert entry.id == "mem-001"
        assert entry.outcome_status == "success"

    def test_memory_entry_to_prompt_context(self):
        """Test converting to prompt context."""
        entry = MemoryEntry(
            id="mem-001",
            goal_description="Previous investigation",
            workflow_id="wf-001",
            outcome_status="success",
            outcome_summary="Found the root cause",
        )
        context = entry.to_prompt_context()
        assert "Previous similar goal" in context
        assert "Outcome: success" in context


class TestWorkflowMemory:
    """Tests for the WorkflowMemory model."""

    def test_workflow_memory_search(self):
        """Test searching workflow memory."""
        memory = WorkflowMemory()
        memory.add_entry(MemoryEntry(
            id="mem-001",
            goal_description="5xx errors in checkout",
            workflow_id="wf-001",
            outcome_status="success",
            keywords=["5xx", "checkout", "errors"],
        ))
        memory.add_entry(MemoryEntry(
            id="mem-002",
            goal_description="Slow login API",
            workflow_id="wf-002",
            outcome_status="success",
            keywords=["slow", "login", "latency"],
        ))

        results = memory.search(keywords=["checkout", "5xx"], limit=5)
        assert len(results) >= 1
        assert results[0].id == "mem-001"
