"""Workflow execution engine."""

import asyncio
import operator
import re
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, Field

from autoops_architect.asyncio_utils import ensure_no_running_loop
from autoops_architect.logging import LogContext, get_logger
from autoops_architect.models.execution import (
    ExecutionStatus,
    NodeResult,
    WorkflowRunResult,
)
from autoops_architect.models.workflow import Node, WorkflowGraph
from autoops_architect.tools.base import ToolRegistry, ToolStatus

logger = get_logger(__name__)


class ConditionEvaluator:
    """
    Evaluates conditional expressions for edge conditions.

    Supports simple expressions like:
    - "{{ node_id.output_key > 10 }}"
    - "{{ error_count > 5 }}"
    - "{{ status == 'success' }}"
    - "{{ logs.error_count >= 3 and logs.warn_count > 0 }}"
    """

    # Supported operators
    OPERATORS = {
        "==": operator.eq,
        "!=": operator.ne,
        ">": operator.gt,
        ">=": operator.ge,
        "<": operator.lt,
        "<=": operator.le,
        "and": lambda a, b: a and b,
        "or": lambda a, b: a or b,
        "not": lambda a: not a,
        "in": lambda a, b: a in b,
    }

    def __init__(self, context: dict[str, Any]) -> None:
        """
        Initialize the evaluator with execution context.

        Args:
            context: Dictionary mapping node IDs to their outputs.
        """
        self.context = context

    def evaluate(self, condition: str) -> bool:
        """
        Evaluate a condition expression.

        Args:
            condition: Condition expression (e.g., "{{ error_count > 5 }}")

        Returns:
            Boolean result of the condition evaluation.
        """
        if not condition or not condition.strip():
            return True  # No condition means always true

        # Extract expression from {{ }} if present
        match = re.match(r"\{\{\s*(.+?)\s*\}\}", condition.strip())
        if match:
            expression = match.group(1)
        else:
            expression = condition.strip()

        try:
            return self._evaluate_expression(expression)
        except Exception as e:
            # A guard that cannot be evaluated must not open the edge
            logger.warning("edge_condition_evaluation_failed", condition=condition, error=str(e))
            return False

    def _evaluate_expression(self, expression: str) -> bool:
        """Evaluate a simple expression."""
        # Handle 'and' / 'or' first (lowest precedence)
        if " and " in expression:
            parts = expression.split(" and ", 1)
            return self._evaluate_expression(parts[0]) and self._evaluate_expression(parts[1])

        if " or " in expression:
            parts = expression.split(" or ", 1)
            return self._evaluate_expression(parts[0]) or self._evaluate_expression(parts[1])

        # Handle 'not'
        if expression.strip().startswith("not "):
            return not self._evaluate_expression(expression[4:])

        # Handle comparison operators
        for op_str, op_func in [
            (">=", operator.ge),
            ("<=", operator.le),
            ("!=", operator.ne),
            ("==", operator.eq),
            (">", operator.gt),
            ("<", operator.lt),
            (" in ", lambda a, b: a in b),
        ]:
            if op_str in expression:
                parts = expression.split(op_str, 1)
                left = self._resolve_value(parts[0].strip())
                right = self._resolve_value(parts[1].strip())
                return op_func(left, right)

        # If no operator, treat as a boolean check
        value = self._resolve_value(expression.strip())
        return bool(value)

    def _resolve_value(self, token: str) -> Any:
        """Resolve a token to its actual value."""
        # Handle string literals
        if (token.startswith("'") and token.endswith("'")) or (
            token.startswith('"') and token.endswith('"')
        ):
            return token[1:-1]

        # Handle numeric literals
        try:
            if "." in token:
                return float(token)
            return int(token)
        except ValueError:
            pass

        # Handle boolean literals
        if token.lower() == "true":
            return True
        if token.lower() == "false":
            return False
        if token.lower() == "none":
            return None

        # Handle context references (node_id.field or just field)
        return self._get_context_value(token)

    def _get_context_value(self, path: str) -> Any:
        """Get a value from the execution context by path."""
        parts = path.split(".")

        if len(parts) == 1:
            # Single field - search in all node outputs
            field = parts[0]
            for node_outputs in self.context.values():
                if isinstance(node_outputs, dict) and field in node_outputs:
                    return node_outputs[field]
            return None

        # node_id.field.subfield...
        node_id = parts[0]
        if node_id not in self.context:
            return None

        value = self.context[node_id]
        for part in parts[1:]:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return None

        return value


class ExecutionCallback(Protocol):
    """Protocol for execution callbacks."""

    def __call__(
        self,
        node_id: str,
        status: ExecutionStatus,
        result: NodeResult | None = None,
    ) -> None:
        """Called when a node's status changes."""
        ...


@dataclass
class _RunState:
    """What has happened so far in a run, used to decide what may still run."""

    completed: set[str] = field(default_factory=set)
    failed: set[str] = field(default_factory=set)
    # Failed without continue_on_failure, or skipped because of a node that did.
    blocking: set[str] = field(default_factory=set)
    # Held at an approval gate, or downstream of a node that was.
    unapproved: set[str] = field(default_factory=set)
    skipped_by_condition: set[str] = field(default_factory=set)


class ExecutorConfig(BaseModel):
    """Configuration for the workflow executor."""

    max_concurrency: int = Field(
        default=1, ge=1, le=10, description="Maximum number of nodes to execute in parallel"
    )

    default_timeout_seconds: int = Field(
        default=120, ge=1, le=3600, description="Default timeout for node execution"
    )

    stop_on_failure: bool = Field(
        default=True, description="Whether to stop execution when a node fails"
    )

    require_approval_for_dangerous: bool = Field(
        default=True, description="Require human approval for dangerous operations"
    )

    auto_approve: bool = Field(
        default=False, description="Automatically approve all approval requests (use with caution)"
    )

    dry_run: bool = Field(default=False, description="Simulate execution without running tools")


class WorkflowExecutor:
    """
    Engine for executing workflow graphs.

    The executor:
    1. Topologically sorts nodes to determine execution order
    2. Executes nodes when their dependencies are satisfied
    3. Passes outputs from parent nodes as context to child nodes
    4. Handles failures, timeouts, and approval gates
    5. Collects results and generates a summary

    Example:
        >>> executor = WorkflowExecutor(tool_registry=registry)
        >>> result = await executor.execute(workflow)
        >>> print(result.summary)
    """

    def __init__(
        self,
        config: ExecutorConfig | None = None,
        tool_registry: ToolRegistry | None = None,
        approval_callback: Callable[[Node], bool] | None = None,
    ) -> None:
        """
        Initialize the executor.

        Args:
            config: Executor configuration.
            tool_registry: Registry of available tools.
            approval_callback: Optional callback for human approval gates.
                If not provided, nodes requiring approval will block or
                fail depending on configuration.
        """
        self.config = config or ExecutorConfig()
        self.tool_registry = tool_registry or self._create_default_registry()
        self.approval_callback = approval_callback

        self._status_callbacks: list[ExecutionCallback] = []
        self._execution_context: dict[str, dict[str, Any]] = {}

    def _create_default_registry(self) -> ToolRegistry:
        """Create a default tool registry with built-in tools."""
        from autoops_architect.tools.base import create_default_registry

        return create_default_registry()

    def add_status_callback(self, callback: ExecutionCallback) -> None:
        """Add a callback to be notified of node status changes."""
        self._status_callbacks.append(callback)

    def _notify_status(
        self,
        node_id: str,
        status: ExecutionStatus,
        result: NodeResult | None = None,
    ) -> None:
        """Notify all callbacks of a status change."""
        for callback in self._status_callbacks:
            try:
                callback(node_id, status, result)
            except Exception:
                pass  # Don't let callback errors break execution

    async def execute(
        self,
        workflow: WorkflowGraph,
        initial_context: dict[str, Any] | None = None,
    ) -> WorkflowRunResult:
        """
        Execute a workflow graph.

        Args:
            workflow: The workflow to execute.
            initial_context: Optional initial context data.

        Returns:
            WorkflowRunResult with all node results and summary.
        """
        # Initialize result tracking
        run_result = WorkflowRunResult(
            workflow_id=workflow.id,
            goal_description=workflow.goal_description,
            started_at=datetime.utcnow(),
        )

        logger.info(
            "workflow_execution_started",
            workflow_id=workflow.id,
            workflow_name=workflow.name,
            node_count=len(workflow.nodes),
            edge_count=len(workflow.edges),
            dry_run=self.config.dry_run,
        )

        # Initialize execution context
        self._execution_context = dict(initial_context) if initial_context else {}

        # Create node results map
        node_results: dict[str, NodeResult] = {}
        for node in workflow.nodes:
            node_results[node.id] = NodeResult(node_id=node.id)

        # Get execution order
        try:
            execution_order = workflow.topological_sort()
        except ValueError as e:
            logger.error("workflow_topological_sort_failed", workflow_id=workflow.id, error=str(e))
            run_result.overall_status = ExecutionStatus.FAILED
            run_result.summary = f"Failed to sort workflow: {e}"
            run_result.finished_at = datetime.utcnow()
            return run_result

        state = _RunState()

        # Execute nodes in order
        for node in execution_order:
            node_result = node_results[node.id]

            if not self._passes_gates(node, workflow, node_result, state):
                continue

            with LogContext(workflow_id=workflow.id, node_id=node.id):
                logger.info(
                    "node_execution_started",
                    node_id=node.id,
                    node_name=node.name,
                    tool=node.tool,
                    requires_approval=node.requires_human_approval,
                )

                await self._run_node(node, node_result, state)

                if self._should_stop([node], state):
                    logger.warning(
                        "workflow_execution_stopping",
                        reason="node_failure",
                        failed_node=node.id,
                    )
                    self._skip_pending(node_results)
                    break

        # Finalize run result
        run_result.node_results = list(node_results.values())
        run_result.finished_at = datetime.utcnow()
        run_result.overall_status = run_result.compute_overall_status()
        run_result.summary = run_result.generate_summary()

        logger.info(
            "workflow_execution_completed",
            workflow_id=workflow.id,
            overall_status=run_result.overall_status.value,
            total_nodes=len(workflow.nodes),
            completed_nodes=len(state.completed),
            failed_nodes=len(state.failed),
            skipped_nodes=run_result.skipped_count,
            duration_seconds=(run_result.finished_at - run_result.started_at).total_seconds(),
        )

        return run_result

    def _skip_reason(
        self,
        node: Node,
        workflow: WorkflowGraph,
        result: NodeResult,
        state: _RunState,
    ) -> str | None:
        """Return why a node must not run, recording the skip in the run state."""
        deps = workflow.get_dependencies(node.id)

        evaluator = ConditionEvaluator(self._execution_context)
        for edge in workflow.edges:
            if (
                edge.to_node_id == node.id
                and edge.condition
                and not evaluator.evaluate(edge.condition)
            ):
                state.skipped_by_condition.add(node.id)
                return "Edge condition not met"

        if deps and all(d in state.skipped_by_condition for d in deps):
            state.skipped_by_condition.add(node.id)
            return "All dependencies skipped by condition"

        # continue_on_failure tolerates failures; it never bypasses an approval gate.
        if any(d in state.unapproved for d in deps):
            state.unapproved.add(node.id)
            return "Dependency not approved"

        if not node.continue_on_failure and any(d in state.blocking for d in deps):
            state.blocking.add(node.id)
            return (
                "Dependency failed"
                if any(d in state.failed for d in deps)
                else ("Dependency skipped")
            )

        if (
            node.requires_human_approval
            and self.config.require_approval_for_dangerous
            and not self.config.auto_approve
        ):
            if self.approval_callback is None:
                result.status = ExecutionStatus.WAITING_APPROVAL
                self._notify_status(node.id, ExecutionStatus.WAITING_APPROVAL, result)
                state.unapproved.add(node.id)
                return "No approval mechanism available"

            if not self.approval_callback(node):
                state.unapproved.add(node.id)
                return "Human approval denied"

        return None

    def _passes_gates(
        self,
        node: Node,
        workflow: WorkflowGraph,
        result: NodeResult,
        state: _RunState,
    ) -> bool:
        """Check whether a node may run, marking it skipped if it may not."""
        reason = self._skip_reason(node, workflow, result, state)
        if reason is None:
            return True

        result.mark_skipped(reason)
        self._notify_status(node.id, ExecutionStatus.SKIPPED, result)
        return False

    async def _run_node(self, node: Node, result: NodeResult, state: _RunState) -> None:
        """Run one node and record its outcome in the run state."""
        self._notify_status(node.id, ExecutionStatus.RUNNING)
        result.mark_started()

        try:
            if self.config.dry_run:
                await self._dry_run_node(node, result)
            else:
                await self._execute_node(node, result)
        except Exception as e:
            result.mark_failed(str(e))

        # _execute_node reports tool failures through the result rather than by
        # raising, so the outcome has to be read from the result.
        if result.status == ExecutionStatus.FAILED:
            state.failed.add(node.id)
            if not node.continue_on_failure:
                state.blocking.add(node.id)
            logger.error("node_execution_failed", node_id=node.id, error=result.error_message)
        else:
            state.completed.add(node.id)
            self._execution_context[node.id] = result.outputs
            logger.info(
                "node_execution_completed",
                node_id=node.id,
                status=result.status.value,
                duration_seconds=result.duration_seconds,
            )

        self._notify_status(node.id, result.status, result)

    def _should_stop(self, nodes: Iterable[Node], state: _RunState) -> bool:
        """Check whether any of the given nodes ended the run with a failure."""
        return self.config.stop_on_failure and any(node.id in state.blocking for node in nodes)

    @staticmethod
    def _skip_pending(node_results: dict[str, NodeResult]) -> None:
        """Mark every node that has not started as skipped."""
        for result in node_results.values():
            if result.status == ExecutionStatus.PENDING:
                result.mark_skipped("Execution stopped due to failure")

    async def _execute_node(
        self,
        node: Node,
        result: NodeResult,
    ) -> None:
        """Execute a single node."""
        # Get the tool
        tool, implied_params = self.tool_registry.resolve(node.tool)

        if tool is None:
            logger.error("tool_not_found", node_id=node.id, tool=node.tool)
            result.mark_failed(f"Tool not found: {node.tool}")
            return

        # Build context from parent node outputs
        deps = self._get_dependency_outputs(node.id)

        # Execute with timeout
        timeout = node.timeout_seconds or self.config.default_timeout_seconds

        try:
            tool_result = await asyncio.wait_for(
                tool.execute({**implied_params, **node.params}, context=deps),
                timeout=timeout,
            )

            # Map tool result to node result
            if tool_result.status == ToolStatus.SUCCESS:
                result.mark_success(tool_result.outputs)
                result.raw_output = tool_result.raw_output
                result.artifacts = tool_result.artifacts
            elif tool_result.status == ToolStatus.TIMEOUT:
                result.mark_failed(tool_result.error_message or "Tool timeout")
            else:
                result.mark_failed(tool_result.error_message or "Tool execution failed")

        except TimeoutError:
            result.mark_failed(f"Execution timed out after {timeout} seconds")

    async def _dry_run_node(
        self,
        node: Node,
        result: NodeResult,
    ) -> None:
        """Simulate node execution for dry run."""
        # A step that cannot run for real should not look fine in a rehearsal
        if self.tool_registry.resolve(node.tool)[0] is None:
            result.mark_failed(f"Tool not found: {node.tool}")
            return

        # Just mark as success with mock outputs
        await asyncio.sleep(0.1)  # Simulate some work

        result.mark_success(
            {
                "dry_run": True,
                "node_id": node.id,
                "tool": node.tool,
                "params": node.params,
            }
        )
        result.raw_output = f"[DRY RUN] Would execute {node.tool} with params: {node.params}"

    def _get_dependency_outputs(self, node_id: str) -> dict[str, dict[str, Any]]:
        """Get outputs from all nodes this node depends on."""
        # This would use the workflow graph, but we track it in execution_context
        return dict(self._execution_context)

    async def execute_parallel(
        self,
        workflow: WorkflowGraph,
        initial_context: dict[str, Any] | None = None,
    ) -> WorkflowRunResult:
        """
        Execute a workflow graph with parallel node execution.

        Independent nodes (nodes at the same level with no dependencies
        on each other) are executed concurrently up to max_concurrency.

        Args:
            workflow: The workflow to execute.
            initial_context: Optional initial context data.

        Returns:
            WorkflowRunResult with all node results and summary.
        """
        # Initialize result tracking
        run_result = WorkflowRunResult(
            workflow_id=workflow.id,
            goal_description=workflow.goal_description,
            started_at=datetime.utcnow(),
        )

        # Initialize execution context
        self._execution_context = dict(initial_context) if initial_context else {}

        # Create node results map
        node_results: dict[str, NodeResult] = {}
        for node in workflow.nodes:
            node_results[node.id] = NodeResult(node_id=node.id)

        # Compute node levels (distance from root nodes)
        node_levels = self._compute_node_levels(workflow)

        # Group nodes by level
        levels: dict[int, list[Node]] = {}
        for node in workflow.nodes:
            level = node_levels.get(node.id, 0)
            if level not in levels:
                levels[level] = []
            levels[level].append(node)

        state = _RunState()
        semaphore = asyncio.Semaphore(self.config.max_concurrency)

        async def run_limited(node: Node) -> None:
            async with semaphore:
                await self._run_node(node, node_results[node.id], state)

        # Execute level by level
        for level in sorted(levels):
            ready_nodes = [
                node
                for node in levels[level]
                if self._passes_gates(node, workflow, node_results[node.id], state)
            ]

            await asyncio.gather(*(run_limited(node) for node in ready_nodes))

            if self._should_stop(ready_nodes, state):
                self._skip_pending(node_results)
                break

        # Finalize run result
        run_result.node_results = list(node_results.values())
        run_result.finished_at = datetime.utcnow()
        run_result.overall_status = run_result.compute_overall_status()
        run_result.summary = run_result.generate_summary()

        return run_result

    def _compute_node_levels(self, workflow: WorkflowGraph) -> dict[str, int]:
        """
        Compute the level (depth) of each node in the workflow.

        Root nodes have level 0. Each subsequent level is determined by
        the maximum level of all dependencies plus 1.

        Args:
            workflow: The workflow graph.

        Returns:
            Dictionary mapping node IDs to their levels.
        """
        levels: dict[str, int] = {}

        # Start with root nodes at level 0
        root_nodes = workflow.get_root_nodes()
        for node in root_nodes:
            levels[node.id] = 0

        # BFS to compute levels
        queue = list(root_nodes)
        while queue:
            node = queue.pop(0)
            current_level = levels.get(node.id, 0)

            # Get dependents
            for dependent_id in workflow.get_dependents(node.id):
                # Dependent level is max of all dependency levels + 1
                new_level = current_level + 1
                if dependent_id not in levels or levels[dependent_id] < new_level:
                    levels[dependent_id] = new_level
                    # Add to queue to process its dependents
                    dependent_node = workflow.get_node(dependent_id)
                    if dependent_node:
                        queue.append(dependent_node)

        return levels

    def execute_sync(
        self,
        workflow: WorkflowGraph,
        initial_context: dict[str, Any] | None = None,
    ) -> WorkflowRunResult:
        """
        Synchronous wrapper for execute().

        Uses asyncio.run() to execute the async method in a new event loop.

        Args:
            workflow: The workflow to execute.
            initial_context: Optional initial context data.

        Returns:
            WorkflowRunResult with all node results.

        Raises:
            RuntimeError: If called from inside a running event loop.
        """
        ensure_no_running_loop("execute_sync", "execute")
        return asyncio.run(self.execute(workflow, initial_context=initial_context))

    async def execute_single_node(
        self,
        node: Node,
        context: dict[str, Any] | None = None,
    ) -> NodeResult:
        """
        Execute a single node independently.

        Useful for testing or manual step-by-step execution.

        Args:
            node: The node to execute.
            context: Optional context data.

        Returns:
            NodeResult for the executed node.
        """
        result = NodeResult(node_id=node.id)
        result.mark_started()

        if context:
            self._execution_context = context

        try:
            if self.config.dry_run:
                await self._dry_run_node(node, result)
            else:
                await self._execute_node(node, result)
        except Exception as e:
            result.mark_failed(str(e))

        return result


class InteractiveExecutor(WorkflowExecutor):
    """
    Interactive executor that pauses for human review at each step.

    This executor is useful for:
    - Learning and understanding workflows
    - Debugging workflow issues
    - High-stakes operations requiring step-by-step approval

    Example:
        >>> executor = InteractiveExecutor()
        >>> async for node, result in executor.execute_interactive(workflow):
        ...     print(f"Executed: {node.name}")
        ...     if not confirm_continue():
        ...         break
    """

    async def execute_interactive(
        self,
        workflow: WorkflowGraph,
        initial_context: dict[str, Any] | None = None,
    ) -> AsyncIterator[tuple[Node, NodeResult]]:
        """
        Execute workflow interactively, yielding after each node.

        Yields:
            Tuple of (node, result) after each node execution.
        """
        # Initialize
        self._execution_context = dict(initial_context) if initial_context else {}

        execution_order = workflow.topological_sort()
        state = _RunState()

        for node in execution_order:
            result = NodeResult(node_id=node.id)

            if self._passes_gates(node, workflow, result, state):
                await self._run_node(node, result, state)

            yield node, result

            if self._should_stop([node], state):
                break
