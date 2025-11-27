"""Workflow-related API routes."""

import asyncio
import uuid
from datetime import datetime
from typing import Any, AsyncGenerator, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import StreamingResponse

from autoops_architect.api.models import (
    EdgeResponse,
    ExecutionRequest,
    ExecutionResponse,
    ExecutionStatus,
    GoalRequest,
    NodeExecutionEvent,
    NodeResponse,
    WorkflowResponse,
    WorkflowUpdateRequest,
)
from autoops_architect.executor.engine import WorkflowExecutor
from autoops_architect.models.execution import NodeStatus
from autoops_architect.models.goal import Environment, Goal, Priority
from autoops_architect.models.workflow import WorkflowGraph
from autoops_architect.planner.architect import Architect, PlannerConfig
from autoops_architect.tools import get_default_tools

router = APIRouter(prefix="/workflows", tags=["workflows"])

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


@router.post("", response_model=WorkflowResponse)
async def create_workflow(request: GoalRequest) -> WorkflowResponse:
    """
    Generate a workflow from a natural language goal.

    This endpoint accepts a goal description and generates a workflow DAG
    that can be reviewed and modified before execution.
    """
    # Build the Goal object
    environment = None
    if request.environment:
        try:
            environment = Environment(request.environment.lower())
        except ValueError:
            pass

    priority = None
    if request.priority:
        try:
            priority = Priority(request.priority.lower())
        except ValueError:
            pass

    goal = Goal(
        description=request.description,
        services=request.services,
        environment=environment,
        priority=priority,
        time_window=request.time_window,
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
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate workflow: {str(e)}",
        )

    # Store the workflow for later execution
    _active_workflows[workflow.id] = workflow

    return _workflow_to_response(workflow)


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(workflow_id: str) -> WorkflowResponse:
    """Get a workflow by ID."""
    if workflow_id not in _active_workflows:
        raise HTTPException(status_code=404, detail="Workflow not found")

    return _workflow_to_response(_active_workflows[workflow_id])


@router.patch("/{workflow_id}", response_model=WorkflowResponse)
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
                    object.__setattr__(
                        node,
                        "requires_human_approval",
                        updates["requires_human_approval"],
                    )

    # Store disabled nodes in metadata
    if request.disabled_node_ids:
        workflow.metadata["disabled_nodes"] = request.disabled_node_ids

    return _workflow_to_response(workflow)


@router.delete("/{workflow_id}")
async def delete_workflow(workflow_id: str) -> dict[str, str]:
    """Delete a workflow."""
    if workflow_id not in _active_workflows:
        raise HTTPException(status_code=404, detail="Workflow not found")

    del _active_workflows[workflow_id]
    return {"status": "deleted", "workflow_id": workflow_id}


@router.get("", response_model=list[WorkflowResponse])
async def list_workflows(
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[WorkflowResponse]:
    """List all active workflows."""
    workflows = list(_active_workflows.values())
    workflows.sort(key=lambda w: w.created_at, reverse=True)
    return [_workflow_to_response(w) for w in workflows[offset : offset + limit]]


@router.post("/{workflow_id}/execute", response_model=ExecutionResponse)
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
        "started_at": datetime.utcnow(),
        "completed_at": None,
        "node_results": [],
        "events": [],
    }

    # Start execution in background
    async def run_execution() -> None:
        _active_executions[execution_id]["status"] = ExecutionStatus.RUNNING
        tools = get_default_tools()
        executor = WorkflowExecutor(tools=tools)

        disabled_nodes = workflow.metadata.get("disabled_nodes", [])

        def on_node_start(node_id: str) -> None:
            node = workflow.get_node(node_id)
            event = NodeExecutionEvent(
                event_type="node_started",
                node_id=node_id,
                node_name=node.name if node else node_id,
                status="running",
            )
            _active_executions[execution_id]["events"].append(event)

        def on_node_complete(node_id: str, result: Any) -> None:
            node = workflow.get_node(node_id)
            event = NodeExecutionEvent(
                event_type="node_completed",
                node_id=node_id,
                node_name=node.name if node else node_id,
                status="completed",
                result={"success": True},
            )
            _active_executions[execution_id]["events"].append(event)
            _active_executions[execution_id]["node_results"].append(
                {"node_id": node_id, "status": "success"}
            )

        try:
            # Filter out disabled nodes
            filtered_workflow = workflow
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

            result = await executor.execute(
                workflow=filtered_workflow,
                dry_run=dry_run,
            )

            _active_executions[execution_id]["status"] = (
                ExecutionStatus.COMPLETED
                if result.overall_status.value == "success"
                else ExecutionStatus.FAILED
            )
            _active_executions[execution_id]["completed_at"] = datetime.utcnow()
            _active_executions[execution_id]["summary"] = result.summary

            # Add completion event
            event = NodeExecutionEvent(
                event_type="workflow_completed",
                status=_active_executions[execution_id]["status"].value,
                message=result.summary,
            )
            _active_executions[execution_id]["events"].append(event)

        except Exception as e:
            _active_executions[execution_id]["status"] = ExecutionStatus.FAILED
            _active_executions[execution_id]["completed_at"] = datetime.utcnow()
            event = NodeExecutionEvent(
                event_type="workflow_failed",
                status="failed",
                message=str(e),
            )
            _active_executions[execution_id]["events"].append(event)

    background_tasks.add_task(run_execution)

    return ExecutionResponse(
        execution_id=execution_id,
        workflow_id=workflow_id,
        status=ExecutionStatus.PENDING,
        started_at=datetime.utcnow(),
        completed_at=None,
        node_results=[],
        summary=None,
        success_count=0,
        failed_count=0,
        skipped_count=0,
    )


@router.get("/{workflow_id}/execute/{execution_id}/stream")
async def stream_execution(
    workflow_id: str,
    execution_id: str,
) -> StreamingResponse:
    """
    Stream execution events using Server-Sent Events (SSE).

    Connect to this endpoint to receive real-time updates during workflow execution.
    """
    if execution_id not in _active_executions:
        raise HTTPException(status_code=404, detail="Execution not found")

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

        yield "data: {\"event_type\": \"stream_end\"}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/{workflow_id}/execute/{execution_id}", response_model=ExecutionResponse)
async def get_execution_status(
    workflow_id: str,
    execution_id: str,
) -> ExecutionResponse:
    """Get the current status of a workflow execution."""
    if execution_id not in _active_executions:
        raise HTTPException(status_code=404, detail="Execution not found")

    execution = _active_executions[execution_id]

    success_count = sum(
        1 for r in execution["node_results"] if r.get("status") == "success"
    )
    failed_count = sum(
        1 for r in execution["node_results"] if r.get("status") == "failed"
    )

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
        skipped_count=0,
    )
