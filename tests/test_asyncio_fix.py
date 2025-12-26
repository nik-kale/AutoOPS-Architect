"""Tests for asyncio.run() compatibility fix."""

import asyncio

import pytest

from autoops_architect.executor.engine import WorkflowExecutor, WorkflowExecutorConfig
from autoops_architect.llm.base import LLMConfig, LLMMessage, LLMProvider
from autoops_architect.llm.providers import MockLLMClient
from autoops_architect.models.goal import Environment, Goal
from autoops_architect.models.workflow import Node, NodeType, WorkflowGraph
from autoops_architect.planner.architect import Architect, PlannerConfig
from autoops_architect.tools.base import ToolRegistry


class TestAsyncioCompat:
    """Test asyncio.run() compatibility for sync wrappers."""

    def test_llm_sync_complete(self) -> None:
        """Test that sync_complete works correctly."""
        config = LLMConfig(provider=LLMProvider.MOCK)
        client = MockLLMClient(config, responses=["Test response"])

        messages = [LLMMessage(role="user", content="Test")]
        response = client.sync_complete(messages)

        assert response.content == "Test response"

    def test_llm_sync_complete_json(self) -> None:
        """Test that sync_complete_json works correctly."""
        config = LLMConfig(provider=LLMProvider.MOCK)
        client = MockLLMClient(config, json_responses=[{"result": "success"}])

        messages = [LLMMessage(role="user", content="Test")]
        result = client.sync_complete_json(messages)

        assert result == {"result": "success"}

    def test_llm_sync_complete_from_async_raises(self) -> None:
        """Test that sync_complete raises when called from async context."""
        config = LLMConfig(provider=LLMProvider.MOCK)
        client = MockLLMClient(config)

        messages = [LLMMessage(role="user", content="Test")]

        async def call_from_async():
            # This should raise RuntimeError
            client.sync_complete(messages)

        with pytest.raises(RuntimeError, match="cannot be called from an async context"):
            asyncio.run(call_from_async())

    def test_planner_sync(self) -> None:
        """Test that plan_sync works correctly."""
        config = PlannerConfig()
        architect = Architect(config=config)

        goal = Goal(
            description="Test goal",
            services=["test-service"],
            environment=Environment.PRODUCTION,
        )

        # This should not raise DeprecationWarning
        workflow = architect.plan_sync(goal)

        assert workflow is not None
        assert workflow.goal_description == goal.description

    def test_planner_sync_from_async_raises(self) -> None:
        """Test that plan_sync raises when called from async context."""
        config = PlannerConfig()
        architect = Architect(config=config)

        goal = Goal(
            description="Test goal",
            services=["test-service"],
            environment=Environment.PRODUCTION,
        )

        async def call_from_async():
            # This should raise RuntimeError
            architect.plan_sync(goal)

        with pytest.raises(RuntimeError, match="cannot be called from an async context"):
            asyncio.run(call_from_async())

    def test_executor_sync(self) -> None:
        """Test that execute_sync works correctly."""
        config = WorkflowExecutorConfig(dry_run=True)
        registry = ToolRegistry()
        executor = WorkflowExecutor(config=config, tool_registry=registry)

        workflow = WorkflowGraph(
            id="wf-test",
            name="Test Workflow",
            goal_description="Test goal",
            nodes=[
                Node(
                    id="test-node",
                    name="Test Node",
                    description="A test node",
                    type=NodeType.ANALYSIS,
                    tool="echo",
                    params={},
                )
            ],
            edges=[],
        )

        # This should not raise DeprecationWarning
        result = executor.execute_sync(workflow)

        assert result is not None
        assert result.workflow_id == workflow.id

    def test_executor_sync_from_async_raises(self) -> None:
        """Test that execute_sync raises when called from async context."""
        config = WorkflowExecutorConfig(dry_run=True)
        registry = ToolRegistry()
        executor = WorkflowExecutor(config=config, tool_registry=registry)

        workflow = WorkflowGraph(
            id="wf-test",
            name="Test Workflow",
            goal_description="Test goal",
            nodes=[
                Node(
                    id="test-node",
                    name="Test Node",
                    description="A test node",
                    type=NodeType.ANALYSIS,
                    tool="echo",
                    params={},
                )
            ],
            edges=[],
        )

        async def call_from_async():
            # This should raise RuntimeError
            executor.execute_sync(workflow)

        with pytest.raises(RuntimeError, match="cannot be called from an async context"):
            asyncio.run(call_from_async())

    def test_no_deprecation_warnings(self) -> None:
        """Test that no deprecation warnings are raised."""
        import warnings

        # Capture warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            # Test LLM client
            config = LLMConfig(provider=LLMProvider.MOCK)
            client = MockLLMClient(config, responses=["Test"])
            messages = [LLMMessage(role="user", content="Test")]
            client.sync_complete(messages)

            # Test planner
            planner_config = PlannerConfig()
            architect = Architect(config=planner_config)
            goal = Goal(
                description="Test",
                services=["test"],
                environment=Environment.PRODUCTION,
            )
            architect.plan_sync(goal)

            # Test executor
            executor_config = WorkflowExecutorConfig(dry_run=True)
            registry = ToolRegistry()
            executor = WorkflowExecutor(config=executor_config, tool_registry=registry)
            workflow = WorkflowGraph(
                id="wf-test",
                name="Test",
                goal_description="Test",
                nodes=[
                    Node(
                        id="n1",
                        name="N1",
                        description="Test",
                        type=NodeType.ANALYSIS,
                        tool="echo",
                        params={},
                    )
                ],
                edges=[],
            )
            executor.execute_sync(workflow)

            # Check that no DeprecationWarnings were raised
            deprecation_warnings = [
                warning for warning in w
                if issubclass(warning.category, DeprecationWarning)
            ]
            assert len(deprecation_warnings) == 0, (
                f"Unexpected DeprecationWarnings: {deprecation_warnings}"
            )


class TestAsyncioRunBehavior:
    """Test correct behavior of asyncio.run() approach."""

    def test_multiple_sync_calls(self) -> None:
        """Test that multiple sync calls work correctly."""
        config = LLMConfig(provider=LLMProvider.MOCK)
        client = MockLLMClient(config, responses=["Response 1", "Response 2", "Response 3"])

        messages = [LLMMessage(role="user", content="Test")]

        # Multiple calls should work without issues
        r1 = client.sync_complete(messages)
        r2 = client.sync_complete(messages)
        r3 = client.sync_complete(messages)

        assert r1.content == "Response 1"
        assert r2.content == "Response 2"
        assert r3.content == "Response 3"

    async def test_async_calls_still_work(self) -> None:
        """Test that async calls continue to work normally."""
        config = LLMConfig(provider=LLMProvider.MOCK)
        client = MockLLMClient(config, responses=["Async response"])

        messages = [LLMMessage(role="user", content="Test")]

        # Async calls should work fine
        response = await client.complete(messages)
        assert response.content == "Async response"

