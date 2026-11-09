"""Tests for what the executor refuses to run after failures and approval gates."""

from typing import Any

import pytest

from autoops_architect.executor.engine import (
    ConditionEvaluator,
    ExecutorConfig,
    InteractiveExecutor,
    WorkflowExecutor,
)
from autoops_architect.models.execution import ExecutionStatus, WorkflowRunResult
from autoops_architect.models.workflow import Edge, Node, NodeType, WorkflowGraph
from autoops_architect.tools.base import Tool, ToolRegistry, ToolResult


class RecordingTool(Tool):
    """Tool that records each call and succeeds or fails as configured."""

    def __init__(self, tool_id: str, *, fail: bool = False) -> None:
        super().__init__()
        self._tool_id = tool_id
        self._fail = fail
        self.calls: list[dict[str, Any]] = []

    @property
    def tool_id(self) -> str:
        return self._tool_id

    @property
    def description(self) -> str:
        return "Records calls"

    async def execute(
        self,
        params: dict[str, Any],
        context: dict[str, Any] | None = None,  # noqa: ARG002 - Tool interface
    ) -> ToolResult:
        self.calls.append(params)
        if self._fail:
            return ToolResult.failed("boom")
        return ToolResult.success({"ok": True})


def node(node_id: str, tool: str = "ok", **kwargs: Any) -> Node:
    return Node(id=node_id, name=node_id, type=NodeType.ANALYSIS, tool=tool, **kwargs)


def chain(*nodes: Node) -> WorkflowGraph:
    """Build a linear workflow from the given nodes."""
    edges = [
        Edge(from_node_id=a.id, to_node_id=b.id) for a, b in zip(nodes, nodes[1:], strict=False)
    ]
    return WorkflowGraph(
        id="wf-gating", name="Gating", goal_description="Test", nodes=list(nodes), edges=edges
    )


@pytest.fixture
def ok_tool() -> RecordingTool:
    return RecordingTool("ok")


@pytest.fixture
def registry(ok_tool: RecordingTool) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ok_tool)
    registry.register(RecordingTool("bad", fail=True))
    return registry


async def run_with(
    runner: str, executor: WorkflowExecutor, workflow: WorkflowGraph
) -> WorkflowRunResult:
    return await getattr(executor, runner)(workflow)


def statuses(result: WorkflowRunResult) -> dict[str, ExecutionStatus]:
    return {r.node_id: r.status for r in result.node_results}


@pytest.fixture(params=["execute", "execute_parallel"])
def runner(request: pytest.FixtureRequest) -> str:
    return str(request.param)


class TestFailurePropagation:
    async def test_tool_failure_stops_the_workflow(
        self, runner: str, registry: ToolRegistry, ok_tool: RecordingTool
    ) -> None:
        executor = WorkflowExecutor(tool_registry=registry)

        result = await run_with(runner, executor, chain(node("a", "bad"), node("b")))

        assert statuses(result) == {
            "a": ExecutionStatus.FAILED,
            "b": ExecutionStatus.SKIPPED,
        }
        assert ok_tool.calls == []
        assert result.overall_status == ExecutionStatus.FAILED

    async def test_skip_propagates_past_the_direct_dependent(
        self, runner: str, registry: ToolRegistry, ok_tool: RecordingTool
    ) -> None:
        executor = WorkflowExecutor(
            config=ExecutorConfig(stop_on_failure=False), tool_registry=registry
        )

        result = await run_with(runner, executor, chain(node("a", "bad"), node("b"), node("c")))

        assert statuses(result)["c"] == ExecutionStatus.SKIPPED
        assert ok_tool.calls == []

    async def test_stop_on_failure_skips_unrelated_later_nodes(
        self, registry: ToolRegistry, ok_tool: RecordingTool
    ) -> None:
        workflow = WorkflowGraph(
            id="wf",
            name="Parallel roots",
            goal_description="Test",
            nodes=[node("a", "bad"), node("b")],
            edges=[],
        )
        executor = WorkflowExecutor(tool_registry=registry)

        result = await executor.execute(workflow)

        assert statuses(result)["b"] == ExecutionStatus.SKIPPED
        assert ok_tool.calls == []

    async def test_failure_flagged_continue_does_not_block_dependents(
        self, runner: str, registry: ToolRegistry, ok_tool: RecordingTool
    ) -> None:
        executor = WorkflowExecutor(tool_registry=registry)
        workflow = chain(node("a", "bad", continue_on_failure=True), node("b"))

        result = await run_with(runner, executor, workflow)

        assert statuses(result)["b"] == ExecutionStatus.SUCCESS
        assert len(ok_tool.calls) == 1

    async def test_dependent_flagged_continue_runs_after_failure(
        self, runner: str, registry: ToolRegistry, ok_tool: RecordingTool
    ) -> None:
        executor = WorkflowExecutor(
            config=ExecutorConfig(stop_on_failure=False), tool_registry=registry
        )
        workflow = chain(node("a", "bad"), node("cleanup", continue_on_failure=True))

        result = await run_with(runner, executor, workflow)

        assert statuses(result)["cleanup"] == ExecutionStatus.SUCCESS
        assert len(ok_tool.calls) == 1


class TestApprovalGates:
    async def test_no_approval_mechanism_blocks_dependents(
        self, runner: str, registry: ToolRegistry, ok_tool: RecordingTool
    ) -> None:
        executor = WorkflowExecutor(tool_registry=registry)
        workflow = chain(node("gate", requires_human_approval=True), node("after"))

        result = await run_with(runner, executor, workflow)

        assert statuses(result) == {
            "gate": ExecutionStatus.SKIPPED,
            "after": ExecutionStatus.SKIPPED,
        }
        assert ok_tool.calls == []

    async def test_denied_approval_blocks_dependents(
        self, runner: str, registry: ToolRegistry, ok_tool: RecordingTool
    ) -> None:
        executor = WorkflowExecutor(tool_registry=registry, approval_callback=lambda _: False)
        workflow = chain(node("gate", requires_human_approval=True), node("after"))

        await run_with(runner, executor, workflow)

        assert ok_tool.calls == []

    async def test_continue_on_failure_cannot_bypass_a_gate(
        self, runner: str, registry: ToolRegistry, ok_tool: RecordingTool
    ) -> None:
        executor = WorkflowExecutor(tool_registry=registry, approval_callback=lambda _: False)
        workflow = chain(
            node("gate", requires_human_approval=True),
            node("after", continue_on_failure=True),
        )

        result = await run_with(runner, executor, workflow)

        assert statuses(result)["after"] == ExecutionStatus.SKIPPED
        assert ok_tool.calls == []

    async def test_approved_gate_runs_dependents(
        self, runner: str, registry: ToolRegistry, ok_tool: RecordingTool
    ) -> None:
        executor = WorkflowExecutor(tool_registry=registry, approval_callback=lambda _: True)
        workflow = chain(node("gate", requires_human_approval=True), node("after"))

        await run_with(runner, executor, workflow)

        assert len(ok_tool.calls) == 2

    async def test_interactive_executor_honours_approval_gates(
        self, registry: ToolRegistry, ok_tool: RecordingTool
    ) -> None:
        executor = InteractiveExecutor(tool_registry=registry)
        workflow = chain(node("gate", requires_human_approval=True), node("after"))

        seen = {n.id: r.status async for n, r in executor.execute_interactive(workflow)}

        assert seen == {
            "gate": ExecutionStatus.SKIPPED,
            "after": ExecutionStatus.SKIPPED,
        }
        assert ok_tool.calls == []


class TestConditions:
    def test_unevaluable_condition_does_not_open_the_edge(self) -> None:
        evaluator = ConditionEvaluator({"logs": {}})

        # The missing value compares as None > 5, which raises TypeError.
        assert evaluator.evaluate("{{ logs.error_count > 5 }}") is False

    def test_condition_still_evaluates_normally(self) -> None:
        evaluator = ConditionEvaluator({"logs": {"error_count": 7}})

        assert evaluator.evaluate("{{ logs.error_count > 5 }}") is True


class TestToolResolution:
    async def test_qualified_mcp_reference_selects_the_server(self) -> None:
        mcp = RecordingTool("secureMCP")
        registry = ToolRegistry()
        registry.register(mcp)
        executor = WorkflowExecutor(tool_registry=registry)
        workflow = chain(node("ticket", "secureMCP:jira", params={"action": "create_issue"}))

        result = await executor.execute(workflow)

        assert result.overall_status == ExecutionStatus.SUCCESS
        assert mcp.calls == [{"server": "jira", "action": "create_issue"}]

    async def test_analysis_alias_resolves_to_log_analyzer(self) -> None:
        analyzer = RecordingTool("log_analyzer")
        registry = ToolRegistry()
        registry.register(analyzer)
        executor = WorkflowExecutor(tool_registry=registry)

        result = await executor.execute(chain(node("analyze", "analysis")))

        assert result.overall_status == ExecutionStatus.SUCCESS
        assert len(analyzer.calls) == 1

    async def test_dry_run_reports_a_tool_that_cannot_be_resolved(
        self, registry: ToolRegistry
    ) -> None:
        executor = WorkflowExecutor(config=ExecutorConfig(dry_run=True), tool_registry=registry)

        result = await executor.execute(chain(node("a", "no_such_tool")))

        assert statuses(result)["a"] == ExecutionStatus.FAILED


class TestIntegrationToolErrors:
    async def test_unexpected_error_is_a_failed_result(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from autoops_architect.tools.base import ToolConfig, ToolStatus
        from autoops_architect.tools.integrations import AutoRCATool

        tool = AutoRCATool(config=ToolConfig(enabled=True))

        async def explode(_payload: dict[str, Any]) -> dict[str, Any]:
            raise ValueError("bad response")

        monkeypatch.setattr(tool, "_call_autorca_api", explode)

        result = await tool.execute({"symptoms": ["errors"]})

        assert result.status == ToolStatus.FAILED
        assert "bad response" in (result.error_message or "")
