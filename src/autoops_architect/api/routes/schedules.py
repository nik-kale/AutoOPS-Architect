"""Schedule management routes."""

import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from autoops_architect.models.goal import Environment, Goal
from autoops_architect.planner.architect import Architect
from autoops_architect.scheduler import (
    Schedule,
    ScheduleExecution,
    add_schedule,
    get_schedule,
    get_schedule_executions,
    list_schedules,
    pause_schedule,
    record_execution,
    remove_schedule,
    resume_schedule,
)

router = APIRouter(prefix="/schedules", tags=["schedules"])


class CreateScheduleRequest(BaseModel):
    """Request to create a schedule."""

    name: str = Field(..., min_length=3, max_length=100)
    cron: str = Field(..., description="Cron expression (minute hour day month day_of_week)")
    timezone: str = Field(default="UTC")
    template_id: str | None = None
    goal_description: str | None = None
    parameters: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)


# Callback function for scheduled executions
async def execute_scheduled_workflow(schedule_id: str) -> None:
    """Execute a workflow from a schedule."""
    schedule = get_schedule(schedule_id)
    if not schedule or not schedule.enabled:
        return
    
    try:
        # Create goal
        goal = Goal(
            description=schedule.goal_description or f"Scheduled: {schedule.name}",
            services=schedule.parameters.get("services", []),
            environment=Environment(schedule.parameters.get("environment", "production")),
        )
        
        # Plan workflow
        architect = Architect()
        workflow = await architect.plan(goal)
        
        # Record execution
        record_execution(
            schedule_id=schedule_id,
            workflow_id=workflow.id,
            status="completed",
        )
    
    except Exception as e:
        # Record failure
        record_execution(
            schedule_id=schedule_id,
            status="failed",
            error=str(e),
        )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_schedule(request: CreateScheduleRequest) -> Schedule:
    """Create a new workflow schedule."""
    schedule_id = f"sched-{uuid.uuid4().hex[:12]}"
    
    schedule = Schedule(
        id=schedule_id,
        name=request.name,
        cron=request.cron,
        timezone=request.timezone,
        template_id=request.template_id,
        goal_description=request.goal_description,
        parameters=request.parameters,
        metadata=request.metadata,
    )
    
    try:
        add_schedule(schedule, execute_scheduled_workflow)
        return schedule
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("")
async def list_all_schedules() -> list[Schedule]:
    """List all schedules."""
    return list_schedules()


@router.get("/{schedule_id}")
async def get_schedule_by_id(schedule_id: str) -> Schedule:
    """Get a schedule by ID."""
    schedule = get_schedule(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return schedule


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(schedule_id: str) -> None:
    """Delete a schedule."""
    if not remove_schedule(schedule_id):
        raise HTTPException(status_code=404, detail="Schedule not found")


@router.post("/{schedule_id}/pause", status_code=status.HTTP_200_OK)
async def pause_schedule_endpoint(schedule_id: str) -> dict:
    """Pause a schedule."""
    if not pause_schedule(schedule_id):
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"status": "paused"}


@router.post("/{schedule_id}/resume", status_code=status.HTTP_200_OK)
async def resume_schedule_endpoint(schedule_id: str) -> dict:
    """Resume a paused schedule."""
    if not resume_schedule(schedule_id):
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"status": "resumed"}


@router.get("/{schedule_id}/executions")
async def list_schedule_executions(
    schedule_id: str,
    limit: int = 50,
) -> list[ScheduleExecution]:
    """Get execution history for a schedule."""
    schedule = get_schedule(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    
    return get_schedule_executions(schedule_id, limit)

