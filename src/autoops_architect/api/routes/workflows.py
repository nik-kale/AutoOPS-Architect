"""Workflow-related API routes."""

import asyncio
import contextlib
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import StreamingResponse

from autoops_architect.api.auth import requires
from autoops_architect.api.models import (
    EdgeResponse,
    ExecutionResponse,
    ExecutionStatus,
    GoalRequest,
    NodeExecutionEvent,
    NodeResponse,
    WorkflowResponse,
    WorkflowUpdateRequest,
)
from autoops_architect.executor.engine import ExecutorConfig, WorkflowExecutor
from autoops_architect.models.execution import ExecutionStatus as NodeExecutionStatus
from autoops_architect.models.execution import NodeResult
from autoops_architect.models.goal import Environment, Goal, Priority
from autoops_architect.models.workflow import APPROVAL_REQUIRED_TYPES, WorkflowGraph
from autoops_architect.planner.architect import Architect, PlannerConfig
from autoops_architect.timeutils import utcnow

router = APIRouter(prefix="/workflows", tags=["workflows"])

_NODE_EVENT_TYPES = {
    NodeExecutionStatus.RUNNING: "node_started",
    NodeExecutionStatus.SUCCESS: "node_completed",
    NodeExecutionStatus.FAILED: "node_failed",
    NodeExecutionStatus.SKIPPED: "node_skipped",
}

# In-memory storage for active workflows and executions
# In production, this would be backed by a database
_active_workflows: dict[str, WorkflowGraph] = {}
_active_executions: dict[str, dict[str, Any]] = {}


def _workflow_to_response(workflow: WorkflowGraph) -> WorkflowResponse:
    """Convert a WorkflowGraph to API response."""
    return WorkflowResponse(
        id=workflow.id,
        name=workflow.name,
        goal_description=workflow.goal_description,
        nodes=[
            NodeResponse(
                id=node.id,
                name=node.name,
                description=node.description,
                type=node.type.value,
                tool=node.tool,
                params=node.params,
                requires_human_approval=node.requires_human_approval,
                timeout_seconds=node.timeout_seconds,
                retry_count=node.retry_count,
                continue_on_failure=node.continue_on_failure,
            )
            for node in workflow.nodes
        ],
        edges=[
            EdgeResponse(
                from_node_id=edge.from_node_id,
                to_node_id=edge.to_node_id,
                condition=edge.condition,
            )
            for edge in workflow.edges
        ],
        created_at=workflow.created_at,
        version=workflow.version,
        metadata=workflow.metadata,
        mermaid_diagram=workflow.to_mermaid(),
        dot_diagram=workflow.to_dot(),
    )


def _get_execution(workflow_id: str, execution_id: str) -> dict[str, Any]:
    """Look up an execution, requiring that it belongs to the workflow in the URL."""
    execution = _active_executions.get(execution_id)
    if execution is None or execution["workflow_id"] != workflow_id:
        raise HTTPException(status_code=404, detail="Execution not found")
    return execution


@router.post("", response_model=WorkflowResponse, dependencies=[requires("create:workflows")])
async def create_workflow(
    request: GoalRequest,
) -> WorkflowResponse:
    """
    Generate a workflow from a natural language goal.

    This endpoint accepts a goal description and generates a workflow DAG
    that can be reviewed and modified before execution.

    Requires: create:workflows permission (if auth enabled)
    """
    # Build the Goal object
    environment = Environment.UNKNOWN
    if request.environment:
        with contextlib.suppress(ValueError):
            environment = Environment(request.environment.lower())

    priority = Priority.UNKNOWN
    if request.priority:
        with contextlib.suppress(ValueError):
            priority = Priority(request.priority.lower())

    goal = Goal(
        description=request.description,
        services=request.services,
        environment=environment,
        priority=priority,
        context=f"Time window: {request.time_window}" if request.time_window else None,
    )

    # Create the architect and generate the workflow
    config = PlannerConfig(enable_remediation=False)
    architect = Architect(config=config)

    try:
        if request.use_template:
            workflow = architect.plan_from_template(
                template_id=request.use_template,
                goal=goal,
            )
        else:
            workflow = await architect.plan(
                goal=goal,
                constraints=request.constraints,
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate workflow: {str(e)}",
        ) from e

    # Store the workflow for later execution
    _active_workflows[workflow.id] = workflow

    return _workflow_to_response(workflow)


@router.get(
    "/{workflow_id}", response_model=WorkflowResponse, dependencies=[requires("read:workflows")]
)
async def get_workflow(workflow_id: str) -> WorkflowResponse:
    """Get a workflow by ID."""
    if workflow_id not in _active_workflows:
        raise HTTPException(status_code=404, detail="Workflow not found")

    return _workflow_to_response(_active_workflows[workflow_id])


@router.patch(
    "/{workflow_id}", response_model=WorkflowResponse, dependencies=[requires("create:workflows")]
)
async def update_workflow(
    workflow_id: str,
    request: WorkflowUpdateRequest,
) -> WorkflowResponse:
    """
    Update a workflow before execution.

    Allows modifying node parameters or disabling specific nodes.
    """
    if workflow_id not in _active_workflows:
        raise HTTPException(status_code=404, detail="Workflow not found")

    workflow = _active_workflows[workflow_id]

    # Apply node updates if provided
    if request.nodes:
        node_updates = {n["id"]: n for n in request.nodes if "id" in n}
        for node in workflow.nodes:
            if node.id in node_updates:
                updates = node_updates[node.id]
                if "params" in updates:
                    node.params.update(updates["params"])
                if "requires_human_approval" in updates:
                    required = bool(updates["requires_human_approval"])
                    if not required and node.type in APPROVAL_REQUIRED_TYPES:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Node '{node.id}' ({node.type.value}) always requires approval",
                        )
                    node.requires_human_approval = required

    # Store disabled nodes in metadata
    if request.disabled_node_ids:
        workflow.metadata["disabled_nodes"] = request.disabled_node_ids

    return _workflow_to_response(workflow)


@router.delete("/{workflow_id}", dependencies=[requires("create:workflows")])
async def delete_workflow(workflow_id: str) -> dict[str, str]:
    """Delete a workflow."""
    if workflow_id not in _active_workflows:
        raise HTTPException(status_code=404, detail="Workflow not found")

    del _active_workflows[workflow_id]
    return {"status": "deleted", "workflow_id": workflow_id}


@router.get("", response_model=list[WorkflowResponse], dependencies=[requires("read:workflows")])
async def list_workflows(
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[WorkflowResponse]:
    """List all active workflows."""
    workflows = list(_active_workflows.values())
    workflows.sort(key=lambda w: w.created_at, reverse=True)
    return [_workflow_to_response(w) for w in workflows[offset : offset + limit]]


@router.post(
    "/{workflow_id}/execute",
    response_model=ExecutionResponse,
    dependencies=[requires("execute:workflows")],
)
async def execute_workflow(
    workflow_id: str,
    dry_run: bool = Query(default=False),
    background_tasks: BackgroundTasks = BackgroundTasks(),
) -> ExecutionResponse:
    """
    Execute a workflow.

    Returns execution status. Use the SSE endpoint for real-time updates.
    """
    if workflow_id not in _active_workflows:
        raise HTTPException(status_code=404, detail="Workflow not found")

    workflow = _active_workflows[workflow_id]
    execution_id = f"exec-{uuid.uuid4().hex[:8]}"

    # Initialize execution state
    _active_executions[execution_id] = {
        "workflow_id": workflow_id,
        "status": ExecutionStatus.PENDING,
        "started_at": utcnow(),
        "completed_at": None,
        "node_results": [],
        "events": [],
    }

    # Start execution in background
    async def run_execution() -> None:
        execution = _active_executions[execution_id]
        execution["status"] = ExecutionStatus.RUNNING

        def on_status_change(
            node_id: str, status: NodeExecutionStatus, _result: NodeResult | None = None
        ) -> None:
            if status not in _NODE_EVENT_TYPES:
                return

            node = workflow.get_node(node_id)
            execution["events"].append(
                NodeExecutionEvent(
                    event_type=_NODE_EVENT_TYPES[status],
                    node_id=node_id,
                    node_name=node.name if node else node_id,
                    status=status.value,
                )
            )
            if status != NodeExecutionStatus.RUNNING:
                execution["node_results"].append({"node_id": node_id, "status": status.value})

        try:
            # Filter out disabled nodes
            filtered_workflow = workflow
            disabled_nodes = workflow.metadata.get("disabled_nodes", [])
            if disabled_nodes:
                filtered_workflow = WorkflowGraph(
                    id=workflow.id,
                    name=workflow.name,
                    goal_description=workflow.goal_description,
                    nodes=[n for n in workflow.nodes if n.id not in disabled_nodes],
                    edges=[
                        e
                        for e in workflow.edges
                        if e.from_node_id not in disabled_nodes
                        and e.to_node_id not in disabled_nodes
                    ],
                    metadata=workflow.metadata,
                )

            executor = WorkflowExecutor(config=ExecutorConfig(dry_run=dry_run))
            executor.add_status_callback(on_status_change)
            result = await executor.execute(filtered_workflow)

            execution["status"] = (
                ExecutionStatus.COMPLETED
                if result.overall_status == NodeExecutionStatus.SUCCESS
                else ExecutionStatus.FAILED
            )
            execution["completed_at"] = utcnow()
            execution["summary"] = result.summary
            execution["events"].append(
                NodeExecutionEvent(
                    event_type="workflow_completed",
                    status=execution["status"].value,
                    message=result.summary,
                )
            )

        except Exception as e:
            execution["status"] = ExecutionStatus.FAILED
            execution["completed_at"] = utcnow()
            execution["events"].append(
                NodeExecutionEvent(
                    event_type="workflow_failed",
                    status="failed",
                    message=str(e),
                )
            )

    background_tasks.add_task(run_execution)

    return ExecutionResponse(
        execution_id=execution_id,
        workflow_id=workflow_id,
        status=ExecutionStatus.PENDING,
        started_at=utcnow(),
        completed_at=None,
        node_results=[],
        summary=None,
        success_count=0,
        failed_count=0,
        skipped_count=0,
    )


@router.get(
    "/{workflow_id}/execute/{execution_id}/stream", dependencies=[requires("read:workflows")]
)
async def stream_execution(
    workflow_id: str,
    execution_id: str,
) -> StreamingResponse:
    """
    Stream execution events using Server-Sent Events (SSE).

    Connect to this endpoint to receive real-time updates during workflow execution.
    """
    _get_execution(workflow_id, execution_id)

    async def event_generator() -> AsyncGenerator[str, None]:
        last_event_count = 0

        while True:
            execution = _active_executions.get(execution_id)
            if not execution:
                break

            events = execution.get("events", [])
            new_events = events[last_event_count:]
            last_event_count = len(events)

            for event in new_events:
                yield f"data: {event.model_dump_json()}\n\n"

            # Check if execution is complete
            if execution["status"] in {
                ExecutionStatus.COMPLETED,
                ExecutionStatus.FAILED,
                ExecutionStatus.CANCELLED,
            }:
                break

            await asyncio.sleep(0.5)

        yield 'data: {"event_type": "stream_end"}\n\n'

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get(
    "/{workflow_id}/execute/{execution_id}",
    response_model=ExecutionResponse,
    dependencies=[requires("read:workflows")],
)
async def get_execution_status(
    workflow_id: str,
    execution_id: str,
) -> ExecutionResponse:
    """Get the current status of a workflow execution."""
    execution = _get_execution(workflow_id, execution_id)

    success_count = sum(1 for r in execution["node_results"] if r.get("status") == "success")
    failed_count = sum(1 for r in execution["node_results"] if r.get("status") == "failed")
    skipped_count = sum(1 for r in execution["node_results"] if r.get("status") == "skipped")

    return ExecutionResponse(
        execution_id=execution_id,
        workflow_id=workflow_id,
        status=execution["status"],
        started_at=execution["started_at"],
        completed_at=execution.get("completed_at"),
        node_results=execution["node_results"],
        summary=execution.get("summary"),
        success_count=success_count,
        failed_count=failed_count,
        skipped_count=skipped_count,
    )
