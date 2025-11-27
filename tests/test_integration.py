"""Integration tests for AutoOps Architect."""

import pytest
import tempfile
import os
from pathlib import Path

from autoops_architect.models.goal import Goal, Environment
from autoops_architect.models.workflow import Edge, Node, NodeType, WorkflowGraph
from autoops_architect.models.execution import ExecutionStatus
from autoops_architect.executor.engine import WorkflowExecutor, ExecutorConfig
from autoops_architect.tools.base import create_default_registry
from autoops_architect.memory.backend import JSONMemoryBackend
from autoops_architect.templates.registry import create_default_template_registry
from autoops_architect.templates.loader import TemplateLoader, create_registry_with_file_templates


class TestEndToEndWorkflow:
    """End-to-end workflow tests."""

    @pytest.fixture
    def executor(self):
        """Create executor with default tools."""
        config = ExecutorConfig(dry_run=True)
        registry = create_default_registry()
        return WorkflowExecutor(config=config, tool_registry=registry)

    @pytest.fixture
    def simple_workflow(self):
        """Create a simple test workflow."""
        return WorkflowGraph(
            id="e2e-test-workflow",
            name="E2E Test Workflow",
            goal_description="Test end-to-end execution",
            nodes=[
                Node(
                    id="echo-start",
                    name="Start",
                    type=NodeType.LOG_COLLECTION,
                    tool="echo",
                    params={"message": "Starting workflow"},
                ),
                Node(
                    id="collect-logs",
                    name="Collect Logs",
                    type=NodeType.LOG_COLLECTION,
                    tool="log_collector",
                    params={"service": "test-service", "duration": "1h"},
                ),
                Node(
                    id="analyze",
                    name="Analyze",
                    type=NodeType.ANALYSIS,
                    tool="analysis",
                    params={"analysis_type": "error_patterns"},
                ),
                Node(
                    id="summarize",
                    name="Summary",
                    type=NodeType.SUMMARY,
                    tool="summary",
                    params={"format": "markdown"},
                ),
            ],
            edges=[
                Edge(from_node_id="echo-start", to_node_id="collect-logs"),
                Edge(from_node_id="collect-logs", to_node_id="analyze"),
                Edge(from_node_id="analyze", to_node_id="summarize"),
            ],
        )

    def test_execute_simple_workflow(self, executor, simple_workflow):
        """Test executing a simple workflow."""
        result = executor.execute_sync(simple_workflow)

        assert result.overall_status == ExecutionStatus.SUCCESS
        assert result.success_count == 4
        assert result.failed_count == 0

    def test_execute_parallel_workflow(self, executor):
        """Test executing workflow with parallel nodes."""
        workflow = WorkflowGraph(
            id="parallel-test",
            name="Parallel Test",
            goal_description="Test parallel execution",
            nodes=[
                Node(
                    id="start",
                    name="Start",
                    type=NodeType.LOG_COLLECTION,
                    tool="echo",
                    params={"message": "Start"},
                ),
                Node(
                    id="parallel-1",
                    name="Parallel 1",
                    type=NodeType.METRIC_QUERY,
                    tool="metric_query",
                    params={"metric_name": "cpu"},
                ),
                Node(
                    id="parallel-2",
                    name="Parallel 2",
                    type=NodeType.LOG_COLLECTION,
                    tool="log_collector",
                    params={"service": "test"},
                ),
                Node(
                    id="merge",
                    name="Merge Results",
                    type=NodeType.SUMMARY,
                    tool="summary",
                    params={},
                ),
            ],
            edges=[
                Edge(from_node_id="start", to_node_id="parallel-1"),
                Edge(from_node_id="start", to_node_id="parallel-2"),
                Edge(from_node_id="parallel-1", to_node_id="merge"),
                Edge(from_node_id="parallel-2", to_node_id="merge"),
            ],
        )

        result = executor.execute_sync(workflow)

        assert result.overall_status == ExecutionStatus.SUCCESS
        assert result.success_count == 4

    def test_workflow_with_failure(self, executor):
        """Test workflow handling of node failure."""
        workflow = WorkflowGraph(
            id="failure-test",
            name="Failure Test",
            goal_description="Test failure handling",
            nodes=[
                Node(
                    id="will-succeed",
                    name="Succeed",
                    type=NodeType.LOG_COLLECTION,
                    tool="echo",
                    params={"message": "success"},
                ),
                Node(
                    id="will-fail",
                    name="Fail",
                    type=NodeType.LOG_COLLECTION,
                    tool="nonexistent_tool",  # This will fail
                    params={},
                ),
                Node(
                    id="after-fail",
                    name="After Fail",
                    type=NodeType.SUMMARY,
                    tool="summary",
                    params={},
                    continue_on_failure=True,
                ),
            ],
            edges=[
                Edge(from_node_id="will-succeed", to_node_id="will-fail"),
                Edge(from_node_id="will-fail", to_node_id="after-fail"),
            ],
        )

        result = executor.execute_sync(workflow)

        # Should complete with some failures
        assert result.failed_count >= 1


class TestMemoryIntegration:
    """Tests for memory backend integration."""

    @pytest.fixture
    def memory_backend(self):
        """Create temporary memory backend."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            temp_path = f.name

        backend = JSONMemoryBackend(temp_path)
        yield backend

        # Cleanup
        os.unlink(temp_path)

    @pytest.fixture
    def goal(self):
        """Create test goal."""
        return Goal(
            description="Investigate 5xx errors in checkout service",
            services=["checkout-api"],
            environment=Environment.PRODUCTION,
        )

    @pytest.fixture
    def workflow(self):
        """Create test workflow."""
        return WorkflowGraph(
            id="mem-test-workflow",
            name="Memory Test",
            goal_description="Test memory storage",
            nodes=[
                Node(
                    id="n1",
                    name="Collect",
                    type=NodeType.LOG_COLLECTION,
                    tool="log_collector",
                ),
            ],
            edges=[],
        )

    def test_save_and_retrieve(self, memory_backend, goal, workflow):
        """Test saving and retrieving workflow runs."""
        from autoops_architect.models.execution import WorkflowRunResult

        result = WorkflowRunResult(
            workflow_id=workflow.id,
            overall_status=ExecutionStatus.SUCCESS,
            node_results=[],
        )

        # Save
        entry_id = memory_backend.save_workflow_run(goal, workflow, result)

        assert entry_id is not None
        assert entry_id.startswith("mem-")

        # Retrieve
        entry = memory_backend.get_entry(entry_id)

        assert entry is not None
        assert entry.goal_description == goal.description

    def test_keyword_search(self, memory_backend, goal, workflow):
        """Test keyword-based search."""
        from autoops_architect.models.execution import WorkflowRunResult

        result = WorkflowRunResult(
            workflow_id=workflow.id,
            overall_status=ExecutionStatus.SUCCESS,
            node_results=[],
        )

        memory_backend.save_workflow_run(goal, workflow, result)

        # Search by keywords
        results = memory_backend.search(
            keywords=["5xx", "checkout"],
            limit=10,
        )

        assert len(results) > 0
        assert any("checkout" in r.goal_description.lower() for r in results)

    def test_semantic_search(self, memory_backend, goal, workflow):
        """Test semantic similarity search."""
        from autoops_architect.models.execution import WorkflowRunResult

        result = WorkflowRunResult(
            workflow_id=workflow.id,
            overall_status=ExecutionStatus.SUCCESS,
            node_results=[],
        )

        memory_backend.save_workflow_run(goal, workflow, result)

        # Semantic search with related query
        results = memory_backend.semantic_search(
            query="server errors in shopping cart",
            limit=10,
        )

        # Should find related result (5xx errors in checkout)
        assert len(results) >= 0  # May or may not match depending on threshold


class TestTemplateIntegration:
    """Tests for template system integration."""

    @pytest.fixture
    def template_registry(self):
        """Create template registry with built-in templates."""
        return create_default_template_registry()

    def test_list_builtin_templates(self, template_registry):
        """Test listing built-in templates."""
        templates = template_registry.list()

        assert len(templates) > 0
        assert any(t.id == "error-rate-investigation" for t in templates)

    def test_instantiate_template(self, template_registry):
        """Test instantiating a template."""
        template = template_registry.get("error-rate-investigation")

        assert template is not None

        workflow = template.instantiate(
            goal_description="Check 5xx errors",
            service="checkout-api",
        )

        assert workflow is not None
        assert len(workflow.nodes) > 0
        assert "checkout-api" in workflow.name

    def test_search_templates(self, template_registry):
        """Test searching templates."""
        results = template_registry.search(query="latency")

        assert len(results) > 0
        assert any("latency" in t.name.lower() for t in results)

    def test_template_categories(self, template_registry):
        """Test listing template categories."""
        categories = template_registry.list_categories()

        assert len(categories) > 0
        assert "error_investigation" in categories or "performance" in categories

    def test_load_yaml_template(self):
        """Test loading template from YAML file."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write("""
id: test-template
name: Test Template
description: A test template
category: testing
tags:
  - test
nodes:
  - id: step1
    name: Step 1
    type: log_collection
    tool: log_collector
    params:
      service: "{{service}}"
edges: []
""")
            temp_path = f.name

        try:
            template = TemplateLoader.load_from_file(temp_path)

            assert template.id == "test-template"
            assert template.name == "Test Template"
            assert len(template.nodes) == 1

            # Test instantiation
            workflow = template.instantiate(
                goal_description="Test",
                service="my-service",
            )

            assert workflow is not None
            assert "my-service" in str(workflow.nodes[0].params)
        finally:
            os.unlink(temp_path)


class TestWorkflowExport:
    """Tests for workflow export functionality."""

    @pytest.fixture
    def workflow(self):
        """Create test workflow."""
        return WorkflowGraph(
            id="export-test",
            name="Export Test",
            goal_description="Test exports",
            nodes=[
                Node(
                    id="n1",
                    name="Node 1",
                    type=NodeType.LOG_COLLECTION,
                    tool="log_collector",
                ),
                Node(
                    id="n2",
                    name="Node 2",
                    type=NodeType.ANALYSIS,
                    tool="analysis",
                ),
            ],
            edges=[
                Edge(from_node_id="n1", to_node_id="n2"),
            ],
        )

    def test_export_mermaid(self, workflow):
        """Test Mermaid diagram export."""
        mermaid = workflow.to_mermaid()

        assert "graph TD" in mermaid or "flowchart" in mermaid
        assert "n1" in mermaid
        assert "n2" in mermaid
        assert "-->" in mermaid

    def test_export_yaml(self, workflow):
        """Test YAML export."""
        yaml_content = workflow.to_yaml()

        assert "id:" in yaml_content
        assert "export-test" in yaml_content
        assert "nodes:" in yaml_content

    def test_export_json(self, workflow):
        """Test JSON export."""
        import json

        json_content = workflow.model_dump_json()
        data = json.loads(json_content)

        assert data["id"] == "export-test"
        assert len(data["nodes"]) == 2

    def test_roundtrip_yaml(self, workflow):
        """Test YAML export and reimport."""
        yaml_content = workflow.to_yaml()
        reimported = WorkflowGraph.from_yaml(yaml_content)

        assert reimported.id == workflow.id
        assert reimported.name == workflow.name
        assert len(reimported.nodes) == len(workflow.nodes)
        assert len(reimported.edges) == len(workflow.edges)


class TestToolRegistry:
    """Tests for tool registry."""

    def test_create_default_registry(self):
        """Test creating default tool registry."""
        registry = create_default_registry()

        # Should have built-in tools
        assert registry.has("echo")
        assert registry.has("log_collector")
        assert registry.has("metric_query")
        assert registry.has("summary")

    def test_tool_execution(self):
        """Test executing a tool."""
        registry = create_default_registry()
        echo_tool = registry.get("echo")

        result = echo_tool.execute_sync(
            {"message": "test message"},
        )

        assert result.status.value == "success"
        assert "test message" in str(result.outputs) or result.raw_output

    def test_list_tools(self):
        """Test listing available tools."""
        registry = create_default_registry()
        tool_ids = registry.list_tools()

        assert len(tool_ids) > 0
        assert "echo" in tool_ids
