"""Tests for the Architect planner."""

import pytest

from autoops_architect.llm.base import LLMConfig, LLMProvider
from autoops_architect.llm.providers import MockLLMClient
from autoops_architect.models.goal import Goal
from autoops_architect.models.workflow import NodeType, WorkflowGraph
from autoops_architect.planner.architect import Architect, PlannerConfig
from autoops_architect.planner.prompts import (
    SYSTEM_PROMPT,
    format_planning_prompt,
    WORKFLOW_JSON_SCHEMA,
)


class TestPrompts:
    """Tests for prompt templates."""

    def test_system_prompt_exists(self):
        """Test that system prompt is defined."""
        assert len(SYSTEM_PROMPT) > 100
        assert "AutoOps Architect" in SYSTEM_PROMPT

    def test_format_planning_prompt(self, sample_goal):
        """Test formatting the planning prompt."""
        prompt = format_planning_prompt(goal=sample_goal)

        assert "Goal:" in prompt
        assert sample_goal.description in prompt
        assert "checkout-api" in prompt
        assert "production" in prompt

    def test_format_planning_prompt_with_constraints(self, sample_goal):
        """Test prompt with constraints."""
        prompt = format_planning_prompt(
            goal=sample_goal,
            constraints=["No shell commands", "Max 5 nodes"],
        )

        assert "No shell commands" in prompt
        assert "Max 5 nodes" in prompt

    def test_format_planning_prompt_with_tools(self, sample_goal):
        """Test prompt with available tools."""
        prompt = format_planning_prompt(
            goal=sample_goal,
            available_tools=["log_collector", "autoRCA"],
        )

        assert "log_collector" in prompt
        assert "autoRCA" in prompt

    def test_workflow_json_schema(self):
        """Test that JSON schema is well-formed."""
        assert WORKFLOW_JSON_SCHEMA["type"] == "object"
        assert "nodes" in WORKFLOW_JSON_SCHEMA["properties"]
        assert "edges" in WORKFLOW_JSON_SCHEMA["properties"]


class TestArchitect:
    """Tests for the Architect class."""

    @pytest.fixture
    def mock_architect(self, mock_llm_client, mock_workflow_json):
        """Create an Architect with mock LLM."""
        mock_llm_client.json_responses = [mock_workflow_json]
        config = PlannerConfig(
            llm_config=LLMConfig(provider=LLMProvider.MOCK),
        )
        return Architect(config=config, llm_client=mock_llm_client)

    def test_architect_creation(self):
        """Test creating an Architect."""
        architect = Architect()
        assert architect.config is not None
        assert architect.config.max_nodes == 20

    def test_architect_with_custom_config(self):
        """Test Architect with custom configuration."""
        config = PlannerConfig(
            max_nodes=10,
            enable_remediation=True,
            available_tools=["echo", "log_collector"],
        )
        architect = Architect(config=config)

        assert architect.config.max_nodes == 10
        assert architect.config.enable_remediation is True

    @pytest.mark.asyncio
    async def test_plan_generates_workflow(self, mock_architect, sample_goal):
        """Test that plan() generates a valid workflow."""
        workflow = await mock_architect.plan(sample_goal)

        assert isinstance(workflow, WorkflowGraph)
        assert len(workflow.nodes) > 0
        assert workflow.goal_description is not None

    @pytest.mark.asyncio
    async def test_plan_respects_constraints(self, mock_architect, sample_goal):
        """Test that constraints are passed to planning."""
        # The mock will return predefined response, but we verify
        # the architect accepts constraints
        workflow = await mock_architect.plan(
            sample_goal,
            constraints=["No remediation"],
        )

        assert workflow is not None

    def test_plan_sync(self, mock_architect, sample_goal):
        """Test synchronous planning."""
        workflow = mock_architect.plan_sync(sample_goal)

        assert isinstance(workflow, WorkflowGraph)
        assert len(workflow.nodes) > 0

    def test_validate_workflow(self, sample_workflow):
        """Test workflow validation."""
        architect = Architect()
        issues = architect.validate_workflow(sample_workflow)

        # Sample workflow should have no critical issues
        # (may have warnings about unknown tools)
        assert isinstance(issues, list)

    def test_validate_workflow_too_many_nodes(self):
        """Test validation catches too many nodes."""
        config = PlannerConfig(max_nodes=2)
        architect = Architect(config=config)

        from autoops_architect.models.workflow import Node, NodeType

        workflow = WorkflowGraph(
            id="wf-test",
            name="Test",
            goal_description="Test",
            nodes=[
                Node(id="n1", name="N1", type=NodeType.ANALYSIS, tool="echo"),
                Node(id="n2", name="N2", type=NodeType.ANALYSIS, tool="echo"),
                Node(id="n3", name="N3", type=NodeType.ANALYSIS, tool="echo"),
            ],
            edges=[],
        )

        issues = architect.validate_workflow(workflow)
        assert any("exceeds maximum" in issue for issue in issues)

    def test_validate_workflow_unapproved_dangerous(self):
        """Test validation catches unapproved dangerous operations."""
        architect = Architect()

        from autoops_architect.models.workflow import Node, NodeType

        # Note: Node auto-sets approval for dangerous types,
        # so we need to override it
        node = Node(
            id="restart",
            name="Restart",
            type=NodeType.SERVICE_RESTART,
            tool="shell",
        )
        # Force override (in real code this shouldn't happen)
        object.__setattr__(node, "requires_human_approval", False)

        workflow = WorkflowGraph(
            id="wf-test",
            name="Test",
            goal_description="Test",
            nodes=[node],
            edges=[],
        )

        issues = architect.validate_workflow(workflow)
        assert any("should require human approval" in issue for issue in issues)

    def test_parse_workflow_adds_missing_fields(self, sample_goal):
        """Test that parse_workflow handles missing fields."""
        architect = Architect()

        # Minimal valid data
        data = {
            "nodes": [
                {
                    "id": "test",
                    "name": "Test",
                    "type": "analysis",
                    "tool": "echo",
                }
            ],
            "edges": [],
        }

        workflow = architect._parse_workflow(data, sample_goal)

        assert workflow.id is not None
        assert workflow.name is not None
        assert workflow.goal_description == sample_goal.description


class TestMockLLMClient:
    """Tests for the MockLLMClient."""

    @pytest.mark.asyncio
    async def test_mock_complete(self, mock_llm_client):
        """Test mock completion."""
        from autoops_architect.llm.base import LLMMessage

        response = await mock_llm_client.complete([
            LLMMessage(role="user", content="Hello")
        ])

        assert response.content is not None
        assert response.model == "mock-model"

    @pytest.mark.asyncio
    async def test_mock_complete_json(self, mock_llm_client):
        """Test mock JSON completion."""
        from autoops_architect.llm.base import LLMMessage

        response = await mock_llm_client.complete_json([
            LLMMessage(role="user", content="Generate a workflow")
        ])

        assert isinstance(response, dict)
        assert "nodes" in response
        assert "edges" in response

    def test_mock_call_history(self, mock_llm_client):
        """Test that mock tracks call history."""
        from autoops_architect.llm.base import LLMMessage

        mock_llm_client.sync_complete([
            LLMMessage(role="user", content="Test 1")
        ])
        mock_llm_client.sync_complete([
            LLMMessage(role="user", content="Test 2")
        ])

        assert len(mock_llm_client.call_history) == 2
