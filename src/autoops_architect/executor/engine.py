"""Workflow execution engine."""

import asyncio
import operator
import re
from datetime import datetime
from typing import Any, Callable, Optional, Protocol

from pydantic import BaseModel, Field

from autoops_architect.models.execution import (
    ExecutionStatus,
    NodeResult,
    WorkflowRunResult,
)
from autoops_architect.models.workflow import Edge, Node, WorkflowGraph
from autoops_architect.tools.base import Tool, ToolRegistry, ToolResult, ToolStatus


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
        except Exception:
            # If evaluation fails, default to True (execute the edge)
            return True

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
        if (token.startswith("'") and token.endswith("'")) or \
           (token.startswith('"') and token.endswith('"')):
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
        result: Optional[NodeResult] = None,
    ) -> None:
        """Called when a node's status changes."""
        ...


class ExecutorConfig(BaseModel):
    """Configuration for the workflow executor."""

    max_concurrency: int = Field(
        default=1,
        ge=1,
        le=10,
        description="Maximum number of nodes to execute in parallel"
    )

    default_timeout_seconds: int = Field(
        default=120,
        ge=1,
        le=3600,
        description="Default timeout for node execution"
    )

    stop_on_failure: bool = Field(
        default=True,
        description="Whether to stop execution when a node fails"
    )

    require_approval_for_dangerous: bool = Field(
        default=True,
        description="Require human approval for dangerous operations"
    )

    auto_approve: bool = Field(
        default=False,
        description="Automatically approve all approval requests (use with caution)"
    )

    dry_run: bool = Field(
        default=False,
        description="Simulate execution without running tools"
    )


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
        config: Optional[ExecutorConfig] = None,
        tool_registry: Optional[ToolRegistry] = None,
        approval_callback: Optional[Callable[[Node], bool]] = None,
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
        result: Optional[NodeResult] = None,
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
        initial_context: Optional[dict[str, Any]] = None,
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
            run_result.overall_status = ExecutionStatus.FAILED
            run_result.summary = f"Failed to sort workflow: {e}"
            run_result.finished_at = datetime.utcnow()
            return run_result

        # Track completed nodes for dependency checking
        completed_nodes: set[str] = set()
        failed_nodes: set[str] = set()
        skipped_by_condition: set[str] = set()

        # Build edge lookup for condition checking
        edges_to_node: dict[str, list[Edge]] = {}
        for edge in workflow.edges:
            if edge.to_node_id not in edges_to_node:
                edges_to_node[edge.to_node_id] = []
            edges_to_node[edge.to_node_id].append(edge)

        # Execute nodes in order
        for node in execution_order:
            node_result = node_results[node.id]

            # Check if dependencies are satisfied
            deps = workflow.get_dependencies(node.id)
            deps_failed = any(d in failed_nodes for d in deps)
            deps_skipped_by_condition = all(d in skipped_by_condition for d in deps) if deps else False

            # Check edge conditions - all incoming edges with conditions must pass
            incoming_edges = edges_to_node.get(node.id, [])
            edge_conditions_met = True
            if incoming_edges:
                evaluator = ConditionEvaluator(self._execution_context)
                for edge in incoming_edges:
                    if edge.condition:
                        if not evaluator.evaluate(edge.condition):
                            edge_conditions_met = False
                            break

            if not edge_conditions_met:
                # Skip this node - condition not met
                node_result.mark_skipped(f"Edge condition not met")
                skipped_by_condition.add(node.id)
                self._notify_status(node.id, ExecutionStatus.SKIPPED, node_result)
                continue

            if deps_skipped_by_condition:
                # All dependencies were skipped by condition, skip this too
                node_result.mark_skipped("All dependencies skipped by condition")
                skipped_by_condition.add(node.id)
                self._notify_status(node.id, ExecutionStatus.SKIPPED, node_result)
                continue

            if deps_failed and not node.continue_on_failure:
                # Skip this node - dependency failed
                node_result.mark_skipped("Dependency failed")
                self._notify_status(node.id, ExecutionStatus.SKIPPED, node_result)
                continue

            # Check for human approval if required
            if node.requires_human_approval and self.config.require_approval_for_dangerous:
                if not self.config.auto_approve:
                    if self.approval_callback:
                        approved = self.approval_callback(node)
                        if not approved:
                            node_result.mark_skipped("Human approval denied")
                            self._notify_status(node.id, ExecutionStatus.SKIPPED, node_result)
                            continue
                    else:
                        # No approval callback - mark as waiting
                        node_result.status = ExecutionStatus.WAITING_APPROVAL
                        self._notify_status(
                            node.id, ExecutionStatus.WAITING_APPROVAL, node_result
                        )
                        # In a real implementation, we would wait for approval
                        # For now, skip the node
                        node_result.mark_skipped("No approval mechanism available")
                        continue

            # Execute the node
            self._notify_status(node.id, ExecutionStatus.RUNNING)
            node_result.mark_started()

            try:
                if self.config.dry_run:
                    # Simulate execution
                    await self._dry_run_node(node, node_result)
                else:
                    # Real execution
                    await self._execute_node(node, node_result)

                completed_nodes.add(node.id)

                # Store outputs in context for downstream nodes
                self._execution_context[node.id] = node_result.outputs

            except Exception as e:
                node_result.mark_failed(str(e))
                failed_nodes.add(node.id)

                if self.config.stop_on_failure and not node.continue_on_failure:
                    # Mark remaining nodes as skipped
                    for remaining in execution_order:
                        if remaining.id not in completed_nodes and remaining.id not in failed_nodes:
                            node_results[remaining.id].mark_skipped("Execution stopped due to failure")
                    break

            self._notify_status(node.id, node_result.status, node_result)

        # Finalize run result
        run_result.node_results = list(node_results.values())
        run_result.finished_at = datetime.utcnow()
        run_result.overall_status = run_result.compute_overall_status()
        run_result.summary = run_result.generate_summary()

        return run_result

    async def _execute_node(
        self,
        node: Node,
        result: NodeResult,
    ) -> None:
        """Execute a single node."""
        # Get the tool
        tool = self.tool_registry.get(node.tool)

        if tool is None:
            result.mark_failed(f"Tool not found: {node.tool}")
            return

        # Build context from parent node outputs
        deps = self._get_dependency_outputs(node.id)

        # Execute with timeout
        timeout = node.timeout_seconds or self.config.default_timeout_seconds

        try:
            tool_result = await asyncio.wait_for(
                tool.execute(node.params, context=deps),
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

        except asyncio.TimeoutError:
            result.mark_failed(f"Execution timed out after {timeout} seconds")

    async def _dry_run_node(
        self,
        node: Node,
        result: NodeResult,
    ) -> None:
        """Simulate node execution for dry run."""
        # Just mark as success with mock outputs
        await asyncio.sleep(0.1)  # Simulate some work

        result.mark_success({
            "dry_run": True,
            "node_id": node.id,
            "tool": node.tool,
            "params": node.params,
        })
        result.raw_output = f"[DRY RUN] Would execute {node.tool} with params: {node.params}"

    def _get_dependency_outputs(self, node_id: str) -> dict[str, dict[str, Any]]:
        """Get outputs from all nodes this node depends on."""
        # This would use the workflow graph, but we track it in execution_context
        return dict(self._execution_context)

    async def execute_parallel(
        self,
        workflow: WorkflowGraph,
        initial_context: Optional[dict[str, Any]] = None,
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

        # Track status
        completed_nodes: set[str] = set()
        failed_nodes: set[str] = set()
        skipped_nodes: set[str] = set()

        # Build edge lookup for condition checking
        edges_to_node: dict[str, list[Edge]] = {}
        for edge in workflow.edges:
            if edge.to_node_id not in edges_to_node:
                edges_to_node[edge.to_node_id] = []
            edges_to_node[edge.to_node_id].append(edge)

        # Execute level by level
        for level in sorted(levels.keys()):
            nodes_at_level = levels[level]

            # Filter nodes that are ready to execute
            ready_nodes = []
            for node in nodes_at_level:
                node_result = node_results[node.id]

                # Check dependencies
                deps = workflow.get_dependencies(node.id)
                deps_failed = any(d in failed_nodes for d in deps)
                deps_skipped = all(d in skipped_nodes for d in deps) if deps else False

                if deps_failed and not node.continue_on_failure:
                    node_result.mark_skipped("Dependency failed")
                    skipped_nodes.add(node.id)
                    self._notify_status(node.id, ExecutionStatus.SKIPPED, node_result)
                    continue

                if deps_skipped:
                    node_result.mark_skipped("All dependencies skipped")
                    skipped_nodes.add(node.id)
                    self._notify_status(node.id, ExecutionStatus.SKIPPED, node_result)
                    continue

                # Check edge conditions
                incoming_edges = edges_to_node.get(node.id, [])
                conditions_met = True
                if incoming_edges:
                    evaluator = ConditionEvaluator(self._execution_context)
                    for edge in incoming_edges:
                        if edge.condition and not evaluator.evaluate(edge.condition):
                            conditions_met = False
                            break

                if not conditions_met:
                    node_result.mark_skipped("Edge condition not met")
                    skipped_nodes.add(node.id)
                    self._notify_status(node.id, ExecutionStatus.SKIPPED, node_result)
                    continue

                # Check approval
                if node.requires_human_approval and self.config.require_approval_for_dangerous:
                    if not self.config.auto_approve:
                        if self.approval_callback:
                            if not self.approval_callback(node):
                                node_result.mark_skipped("Approval denied")
                                skipped_nodes.add(node.id)
                                self._notify_status(node.id, ExecutionStatus.SKIPPED, node_result)
                                continue
                        else:
                            node_result.mark_skipped("No approval mechanism")
                            skipped_nodes.add(node.id)
                            self._notify_status(node.id, ExecutionStatus.SKIPPED, node_result)
                            continue

                ready_nodes.append(node)

            if not ready_nodes:
                continue

            # Execute ready nodes in parallel with concurrency limit
            semaphore = asyncio.Semaphore(self.config.max_concurrency)

            async def execute_with_semaphore(node: Node) -> None:
                async with semaphore:
                    node_result = node_results[node.id]
                    self._notify_status(node.id, ExecutionStatus.RUNNING)
                    node_result.mark_started()

                    try:
                        if self.config.dry_run:
                            await self._dry_run_node(node, node_result)
                        else:
                            await self._execute_node(node, node_result)

                        completed_nodes.add(node.id)
                        self._execution_context[node.id] = node_result.outputs

                    except Exception as e:
                        node_result.mark_failed(str(e))
                        failed_nodes.add(node.id)

                    self._notify_status(node.id, node_result.status, node_result)

            # Run all ready nodes concurrently
            await asyncio.gather(*[execute_with_semaphore(node) for node in ready_nodes])

            # Check if we should stop due to failure
            if failed_nodes and self.config.stop_on_failure:
                # Mark remaining nodes as skipped
                for remaining_level in range(level + 1, max(levels.keys()) + 1):
                    if remaining_level in levels:
                        for node in levels[remaining_level]:
                            if node.id not in completed_nodes and node.id not in failed_nodes:
                                node_results[node.id].mark_skipped("Execution stopped due to failure")
                                skipped_nodes.add(node.id)
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
        initial_context: Optional[dict[str, Any]] = None,
    ) -> WorkflowRunResult:
        """
        Synchronous wrapper for execute().

        Uses asyncio.run() to execute the async method in a new event loop.
        Compatible with Python 3.11+ and nested async contexts.

        Args:
            workflow: The workflow to execute.
            initial_context: Optional initial context data.

        Returns:
            WorkflowRunResult with all node results.
        """
        try:
            # Check if we're already in an async context
            asyncio.get_running_loop()
            # If we reach here, we're in an async context - this is an error
            raise RuntimeError(
                "execute_sync() cannot be called from an async context. "
                "Use await execute() instead."
            )
        except RuntimeError:
            # No running loop - safe to use asyncio.run()
            pass

        return asyncio.run(self.execute(workflow, initial_context=initial_context))

    async def execute_single_node(
        self,
        node: Node,
        context: Optional[dict[str, Any]] = None,
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
        initial_context: Optional[dict[str, Any]] = None,
    ):
        """
        Execute workflow interactively, yielding after each node.

        Yields:
            Tuple of (node, result) after each node execution.
        """
        # Initialize
        self._execution_context = dict(initial_context) if initial_context else {}

        execution_order = workflow.topological_sort()
        completed_nodes: set[str] = set()
        failed_nodes: set[str] = set()

        for node in execution_order:
            result = NodeResult(node_id=node.id)

            # Check dependencies
            deps = workflow.get_dependencies(node.id)
            if any(d in failed_nodes for d in deps):
                result.mark_skipped("Dependency failed")
                yield node, result
                continue

            # Execute
            result.mark_started()

            try:
                if self.config.dry_run:
                    await self._dry_run_node(node, result)
                else:
                    await self._execute_node(node, result)

                completed_nodes.add(node.id)
                self._execution_context[node.id] = result.outputs

            except Exception as e:
                result.mark_failed(str(e))
                failed_nodes.add(node.id)

            yield node, result

            # Check if we should stop
            if result.status == ExecutionStatus.FAILED and self.config.stop_on_failure:
                break
