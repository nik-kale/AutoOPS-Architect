"""Request and response models for the API."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class GoalRequest(BaseModel):
    """Request to create a workflow from a goal."""

    description: str = Field(
        ...,
        min_length=10,
        max_length=2000,
        description="Natural language description of the goal",
    )
    services: list[str] = Field(
        default_factory=list,
        description="List of affected services",
    )
    environment: Optional[str] = Field(
        default=None,
        description="Target environment (production, staging, development)",
    )
    priority: Optional[str] = Field(
        default=None,
        description="Priority level (critical, high, medium, low)",
    )
    time_window: Optional[str] = Field(
        default=None,
        description="Relevant time window (e.g., 'last 1 hour')",
    )
    constraints: list[str] = Field(
        default_factory=list,
        description="Additional constraints for workflow generation",
    )
    use_template: Optional[str] = Field(
        default=None,
        description="Template ID to use instead of LLM generation",
    )


class NodeResponse(BaseModel):
    """A node in the workflow response."""

    id: str
    name: str
    description: str
    type: str
    tool: str
    params: dict[str, Any]
    requires_human_approval: bool
    timeout_seconds: Optional[int]
    retry_count: int
    continue_on_failure: bool


class EdgeResponse(BaseModel):
    """An edge in the workflow response."""

    from_node_id: str
    to_node_id: str
    condition: Optional[str]


class WorkflowResponse(BaseModel):
    """Response containing a workflow graph."""

    id: str
    name: str
    goal_description: str
    nodes: list[NodeResponse]
    edges: list[EdgeResponse]
    created_at: datetime
    version: str
    metadata: dict[str, Any]
    mermaid_diagram: str
    dot_diagram: str


class WorkflowUpdateRequest(BaseModel):
    """Request to update a workflow before execution."""

    nodes: Optional[list[dict[str, Any]]] = Field(
        default=None,
        description="Updated nodes (partial updates supported)",
    )
    disabled_node_ids: list[str] = Field(
        default_factory=list,
        description="Node IDs to disable/skip during execution",
    )


class ExecutionStatus(str, Enum):
    """Status of workflow execution."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class NodeExecutionEvent(BaseModel):
    """Event for node execution status updates (SSE)."""

    event_type: str = Field(
        ...,
        description="Type: node_started, node_completed, node_failed, workflow_completed",
    )
    node_id: Optional[str] = None
    node_name: Optional[str] = None
    status: str
    message: Optional[str] = None
    result: Optional[dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ExecutionRequest(BaseModel):
    """Request to execute a workflow."""

    workflow_id: str = Field(
        ...,
        description="ID of the workflow to execute",
    )
    dry_run: bool = Field(
        default=False,
        description="If true, simulate execution without side effects",
    )
    disabled_node_ids: list[str] = Field(
        default_factory=list,
        description="Node IDs to skip during execution",
    )
    approval_callback_url: Optional[str] = Field(
        default=None,
        description="URL to call for human approval requests",
    )


class ExecutionResponse(BaseModel):
    """Response for workflow execution."""

    execution_id: str
    workflow_id: str
    status: ExecutionStatus
    started_at: datetime
    completed_at: Optional[datetime]
    node_results: list[dict[str, Any]]
    summary: Optional[str]
    success_count: int
    failed_count: int
    skipped_count: int


class TemplateResponse(BaseModel):
    """Response for a workflow template."""

    id: str
    name: str
    description: str
    category: str
    tags: list[str]
    variables: list[str]


class MemoryEntryResponse(BaseModel):
    """Response for a memory entry."""

    id: str
    goal_description: str
    workflow_id: str
    workflow_summary: Optional[str]
    outcome_status: str
    outcome_summary: Optional[str]
    keywords: list[str]
    services: list[str]
    environment: Optional[str]
    created_at: datetime
    relevance_score: Optional[float]


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "healthy"
    version: str
    llm_available: bool
    memory_backend: str
