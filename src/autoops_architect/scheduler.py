"""Workflow scheduling with cron support."""

import uuid
from datetime import datetime
from typing import Any, Callable, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from pydantic import BaseModel, Field


class Schedule(BaseModel):
    """Scheduled workflow configuration."""

    id: str = Field(..., description="Unique schedule ID")
    name: str = Field(..., min_length=3, max_length=100)
    cron: str = Field(..., description="Cron expression (e.g., '0 9 * * *')")
    timezone: str = Field(default="UTC", description="Timezone for schedule")
    template_id: Optional[str] = Field(None, description="Workflow template ID")
    goal_description: Optional[str] = Field(None, description="Goal description")
    parameters: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    run_count: int = Field(default=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScheduleExecution(BaseModel):
    """Record of a scheduled execution."""

    id: str
    schedule_id: str
    workflow_id: Optional[str] = None
    status: str = "scheduled"  # scheduled, running, completed, failed
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    error: Optional[str] = None


# Global scheduler instance
_scheduler: Optional[AsyncIOScheduler] = None
_schedules_db: dict[str, Schedule] = {}
_executions_db: dict[str, ScheduleExecution] = {}


def get_scheduler() -> AsyncIOScheduler:
    """Get or create the global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
        _scheduler.start()
    return _scheduler


def add_schedule(
    schedule: Schedule,
    callback: Callable,
) -> str:
    """
    Add a scheduled job.

    Args:
        schedule: Schedule configuration.
        callback: Async function to call on schedule.

    Returns:
        Job ID from APScheduler.
    """
    scheduler = get_scheduler()
    
    # Parse cron expression
    cron_parts = schedule.cron.split()
    if len(cron_parts) != 5:
        raise ValueError(
            "Invalid cron expression. Expected format: 'minute hour day month day_of_week'"
        )
    
    minute, hour, day, month, day_of_week = cron_parts
    
    # Create trigger
    trigger = CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=day_of_week,
        timezone=schedule.timezone,
    )
    
    # Add job
    job = scheduler.add_job(
        callback,
        trigger,
        id=schedule.id,
        name=schedule.name,
        args=[schedule.id],
        replace_existing=True,
    )
    
    # Update next run time
    schedule.next_run = job.next_run_time
    _schedules_db[schedule.id] = schedule
    
    return job.id


def remove_schedule(schedule_id: str) -> bool:
    """
    Remove a scheduled job.

    Args:
        schedule_id: Schedule ID to remove.

    Returns:
        True if removed, False if not found.
    """
    scheduler = get_scheduler()
    
    try:
        scheduler.remove_job(schedule_id)
        if schedule_id in _schedules_db:
            del _schedules_db[schedule_id]
        return True
    except Exception:
        return False


def pause_schedule(schedule_id: str) -> bool:
    """Pause a schedule."""
    scheduler = get_scheduler()
    schedule = _schedules_db.get(schedule_id)
    
    if not schedule:
        return False
    
    try:
        scheduler.pause_job(schedule_id)
        schedule.enabled = False
        return True
    except Exception:
        return False


def resume_schedule(schedule_id: str) -> bool:
    """Resume a paused schedule."""
    scheduler = get_scheduler()
    schedule = _schedules_db.get(schedule_id)
    
    if not schedule:
        return False
    
    try:
        scheduler.resume_job(schedule_id)
        schedule.enabled = True
        return True
    except Exception:
        return False


def get_schedule(schedule_id: str) -> Optional[Schedule]:
    """Get schedule by ID."""
    schedule = _schedules_db.get(schedule_id)
    if schedule:
        # Update next run time from scheduler
        scheduler = get_scheduler()
        try:
            job = scheduler.get_job(schedule_id)
            if job:
                schedule.next_run = job.next_run_time
        except Exception:
            pass
    return schedule


def list_schedules() -> list[Schedule]:
    """List all schedules."""
    scheduler = get_scheduler()
    
    # Update next run times
    for schedule in _schedules_db.values():
        try:
            job = scheduler.get_job(schedule.id)
            if job:
                schedule.next_run = job.next_run_time
        except Exception:
            pass
    
    return list(_schedules_db.values())


def record_execution(
    schedule_id: str,
    workflow_id: Optional[str] = None,
    status: str = "completed",
    error: Optional[str] = None,
) -> ScheduleExecution:
    """Record a schedule execution."""
    execution = ScheduleExecution(
        id=f"exec-{uuid.uuid4().hex[:12]}",
        schedule_id=schedule_id,
        workflow_id=workflow_id,
        status=status,
        completed_at=datetime.utcnow() if status in ["completed", "failed"] else None,
        error=error,
    )
    
    _executions_db[execution.id] = execution
    
    # Update schedule
    schedule = _schedules_db.get(schedule_id)
    if schedule:
        schedule.last_run = execution.started_at
        schedule.run_count += 1
    
    return execution


def get_schedule_executions(schedule_id: str, limit: int = 50) -> list[ScheduleExecution]:
    """Get execution history for a schedule."""
    executions = [
        e for e in _executions_db.values()
        if e.schedule_id == schedule_id
    ]
    executions.sort(key=lambda x: x.started_at, reverse=True)
    return executions[:limit]


def shutdown_scheduler() -> None:
    """Shutdown the scheduler gracefully."""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=True)
        _scheduler = None

