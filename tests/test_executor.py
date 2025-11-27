"""Tests for the workflow executor."""

import pytest

from autoops_architect.executor.engine import (
    ExecutorConfig,
    WorkflowExecutor,
    InteractiveExecutor,
)
from autoops_architect.models.execution import ExecutionStatus
from autoops_architect.models.workflow import Node, NodeType, Edge, WorkflowGraph
from autoops_architect.tools.base import ToolRegistry
from autoops_architect.tools.builtin import EchoTool, LogCollectorTool, SummaryTool, AnalysisTool


@pytest.fixture
def executor_registry():
    """Create a tool registry for executor tests."""
    registry = ToolRegistry()
    registry.register(EchoTool())
    registry.register(LogCollectorTool())
    registry.register(SummaryTool())
    registry.register(AnalysisTool())
    return registry


class TestExecutorConfig:
    """Tests for ExecutorConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = ExecutorConfig()

        assert config.max_concurrency == 1
        assert config.default_timeout_seconds == 120
        assert config.stop_on_failure is True
        assert config.dry_run is False

    def test_custom_config(self):
        """Test custom configuration."""
        config = ExecutorConfig(
            max_concurrency=5,
            dry_run=True,
            stop_on_failure=False,
        )

        assert config.max_concurrency == 5
        assert config.dry_run is True
        assert config.stop_on_failure is False


class TestWorkflowExecutor:
    """Tests for the WorkflowExecutor."""

    def test_executor_creation(self, executor_registry):
        """Test creating an executor."""
        executor = WorkflowExecutor(tool_registry=executor_registry)

        assert executor.config is not None
        assert executor.tool_registry is not None

    @pytest.mark.asyncio
    async def test_execute_simple_workflow(self, sample_workflow, executor_registry):
        """Test executing a simple workflow."""
        executor = WorkflowExecutor(tool_registry=executor_registry)
        result = await executor.execute(sample_workflow)

        assert result.workflow_id == sample_workflow.id
        assert len(result.node_results) == len(sample_workflow.nodes)
        assert result.overall_status in (ExecutionStatus.SUCCESS, ExecutionStatus.FAILED)

    @pytest.mark.asyncio
    async def test_execute_dry_run(self, sample_workflow, executor_registry):
        """Test dry run execution."""
        config = ExecutorConfig(dry_run=True)
        executor = WorkflowExecutor(config=config, tool_registry=executor_registry)

        result = await executor.execute(sample_workflow)

        # All nodes should succeed in dry run
        assert result.overall_status == ExecutionStatus.SUCCESS
        for node_result in result.node_results:
            assert node_result.outputs.get("dry_run") is True

    def test_execute_sync(self, sample_workflow, executor_registry):
        """Test synchronous execution."""
        executor = WorkflowExecutor(tool_registry=executor_registry)
        result = executor.execute_sync(sample_workflow)

        assert result.workflow_id == sample_workflow.id
        assert result.finished_at is not None

    @pytest.mark.asyncio
    async def test_execute_with_callback(self, sample_workflow, executor_registry):
        """Test execution with status callback."""
        status_updates = []

        def callback(node_id, status, result=None):
            status_updates.append((node_id, status))

        executor = WorkflowExecutor(tool_registry=executor_registry)
        executor.add_status_callback(callback)

        await executor.execute(sample_workflow)

        # Should have status updates for each node
        assert len(status_updates) > 0
        # Each node should have at least a running and final status
        node_ids = {update[0] for update in status_updates}
        assert len(node_ids) == len(sample_workflow.nodes)

    @pytest.mark.asyncio
    async def test_execute_parallel_workflow(self, parallel_workflow, executor_registry):
        """Test executing a workflow with parallel branches."""
        executor = WorkflowExecutor(tool_registry=executor_registry)
        result = await executor.execute(parallel_workflow)

        assert len(result.node_results) == len(parallel_workflow.nodes)
        # With current sequential execution, all should complete
        assert result.success_count >= 3  # At least start, one branch, and merge

    @pytest.mark.asyncio
    async def test_execute_with_missing_tool(self):
        """Test execution when a tool is not found."""
        workflow = WorkflowGraph(
            id="wf-test",
            name="Test",
            goal_description="Test",
            nodes=[
                Node(
                    id="node-1",
                    name="Node 1",
                    type=NodeType.ANALYSIS,
                    tool="nonexistent_tool",
                ),
            ],
            edges=[],
        )

        # Empty registry
        executor = WorkflowExecutor(tool_registry=ToolRegistry())
        result = await executor.execute(workflow)

        assert result.overall_status == ExecutionStatus.FAILED
        assert result.node_results[0].error_message is not None
        assert "not found" in result.node_results[0].error_message

    @pytest.mark.asyncio
    async def test_execute_stop_on_failure(self, executor_registry):
        """Test that execution stops on failure when configured."""
        workflow = WorkflowGraph(
            id="wf-test",
            name="Test",
            goal_description="Test",
            nodes=[
                Node(id="n1", name="N1", type=NodeType.ANALYSIS, tool="nonexistent"),
                Node(id="n2", name="N2", type=NodeType.ANALYSIS, tool="echo"),
            ],
            edges=[
                Edge(from_node_id="n1", to_node_id="n2"),
            ],
        )

        config = ExecutorConfig(stop_on_failure=True)
        executor = WorkflowExecutor(config=config, tool_registry=executor_registry)

        result = await executor.execute(workflow)

        # n2 should be skipped due to n1 failure
        n2_result = result.get_node_result("n2")
        assert n2_result.status == ExecutionStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_execute_continue_on_failure(self, executor_registry):
        """Test continue_on_failure flag on nodes."""
        workflow = WorkflowGraph(
            id="wf-test",
            name="Test",
            goal_description="Test",
            nodes=[
                Node(
                    id="n1",
                    name="N1",
                    type=NodeType.ANALYSIS,
                    tool="nonexistent",
                    continue_on_failure=True,
                ),
                Node(id="n2", name="N2", type=NodeType.ANALYSIS, tool="echo"),
            ],
            edges=[
                Edge(from_node_id="n1", to_node_id="n2"),
            ],
        )

        executor = WorkflowExecutor(tool_registry=executor_registry)
        result = await executor.execute(workflow)

        # n2 should still execute because n1 has continue_on_failure
        n2_result = result.get_node_result("n2")
        assert n2_result.status in (ExecutionStatus.SUCCESS, ExecutionStatus.RUNNING)

    @pytest.mark.asyncio
    async def test_execute_single_node(self, executor_registry):
        """Test executing a single node."""
        node = Node(
            id="test",
            name="Test",
            type=NodeType.ANALYSIS,
            tool="echo",
            params={"message": "Hello"},
        )

        executor = WorkflowExecutor(tool_registry=executor_registry)
        result = await executor.execute_single_node(node)

        assert result.node_id == "test"
        assert result.status == ExecutionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_execute_with_context(self, executor_registry):
        """Test that context is passed between nodes."""
        workflow = WorkflowGraph(
            id="wf-test",
            name="Test",
            goal_description="Test",
            nodes=[
                Node(
                    id="collect",
                    name="Collect",
                    type=NodeType.LOG_COLLECTION,
                    tool="log_collector",
                    params={"service": "test"},
                ),
                Node(
                    id="analyze",
                    name="Analyze",
                    type=NodeType.ANALYSIS,
                    tool="log_analyzer",
                    params={},
                ),
            ],
            edges=[
                Edge(from_node_id="collect", to_node_id="analyze"),
            ],
        )

        executor = WorkflowExecutor(tool_registry=executor_registry)
        result = await executor.execute(workflow)

        # Both nodes should succeed
        assert result.success_count == 2


class TestInteractiveExecutor:
    """Tests for the InteractiveExecutor."""

    @pytest.mark.asyncio
    async def test_interactive_execution(self, sample_workflow, executor_registry):
        """Test interactive execution yields after each node."""
        executor = InteractiveExecutor(tool_registry=executor_registry)

        executed_nodes = []
        async for node, result in executor.execute_interactive(sample_workflow):
            executed_nodes.append(node.id)

        assert len(executed_nodes) == len(sample_workflow.nodes)

    @pytest.mark.asyncio
    async def test_interactive_early_stop(self, sample_workflow, executor_registry):
        """Test that interactive execution can be stopped early."""
        config = ExecutorConfig(stop_on_failure=True)
        executor = InteractiveExecutor(config=config, tool_registry=executor_registry)

        executed_nodes = []
        async for node, result in executor.execute_interactive(sample_workflow):
            executed_nodes.append(node.id)
            if len(executed_nodes) >= 2:
                break

        assert len(executed_nodes) == 2
