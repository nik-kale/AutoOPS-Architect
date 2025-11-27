"""Memory-related API routes."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from autoops_architect.api.models import MemoryEntryResponse
from autoops_architect.memory.backend import get_memory_backend

router = APIRouter(prefix="/memory", tags=["memory"])


def _get_backend():
    """Get the memory backend."""
    return get_memory_backend(backend_type="json")


@router.get("", response_model=list[MemoryEntryResponse])
async def list_memory_entries(
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[MemoryEntryResponse]:
    """List all memory entries (past workflow executions)."""
    backend = _get_backend()
    entries = backend.list_entries(limit=limit, offset=offset)

    return [
        MemoryEntryResponse(
            id=e.id,
            goal_description=e.goal_description,
            workflow_id=e.workflow_id,
            workflow_summary=e.workflow_summary,
            outcome_status=e.outcome_status,
            outcome_summary=e.outcome_summary,
            keywords=e.keywords,
            services=e.services,
            environment=e.environment,
            created_at=e.created_at,
            relevance_score=e.relevance_score,
        )
        for e in entries
    ]


@router.get("/search", response_model=list[MemoryEntryResponse])
async def search_memory(
    keywords: str = Query(..., description="Comma-separated keywords to search"),
    limit: int = Query(default=5, le=20),
) -> list[MemoryEntryResponse]:
    """
    Search memory for similar past workflows.

    This is useful for finding relevant past experiences to inform planning.
    """
    backend = _get_backend()
    keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]

    if not keyword_list:
        raise HTTPException(status_code=400, detail="At least one keyword is required")

    entries = backend.search(keywords=keyword_list, limit=limit)

    return [
        MemoryEntryResponse(
            id=e.id,
            goal_description=e.goal_description,
            workflow_id=e.workflow_id,
            workflow_summary=e.workflow_summary,
            outcome_status=e.outcome_status,
            outcome_summary=e.outcome_summary,
            keywords=e.keywords,
            services=e.services,
            environment=e.environment,
            created_at=e.created_at,
            relevance_score=e.relevance_score,
        )
        for e in entries
    ]


@router.get("/{entry_id}", response_model=MemoryEntryResponse)
async def get_memory_entry(entry_id: str) -> MemoryEntryResponse:
    """Get a specific memory entry by ID."""
    backend = _get_backend()
    entry = backend.get_entry(entry_id)

    if not entry:
        raise HTTPException(status_code=404, detail="Memory entry not found")

    return MemoryEntryResponse(
        id=entry.id,
        goal_description=entry.goal_description,
        workflow_id=entry.workflow_id,
        workflow_summary=entry.workflow_summary,
        outcome_status=entry.outcome_status,
        outcome_summary=entry.outcome_summary,
        keywords=entry.keywords,
        services=entry.services,
        environment=entry.environment,
        created_at=entry.created_at,
        relevance_score=entry.relevance_score,
    )


@router.delete("/{entry_id}")
async def delete_memory_entry(entry_id: str) -> dict[str, str]:
    """Delete a memory entry."""
    backend = _get_backend()

    if not backend.delete_entry(entry_id):
        raise HTTPException(status_code=404, detail="Memory entry not found")

    return {"status": "deleted", "entry_id": entry_id}


@router.get("/stats", response_model=dict)
async def get_memory_stats() -> dict:
    """Get memory statistics."""
    backend = _get_backend()
    entries = backend.list_entries(limit=1000)

    if not entries:
        return {
            "total_entries": 0,
            "success_count": 0,
            "failure_count": 0,
            "services": [],
            "environments": [],
        }

    success_count = sum(1 for e in entries if e.outcome_status == "success")
    failure_count = sum(1 for e in entries if e.outcome_status == "failure")

    # Collect unique services and environments
    services = set()
    environments = set()
    for e in entries:
        services.update(e.services)
        if e.environment:
            environments.add(e.environment)

    return {
        "total_entries": len(entries),
        "success_count": success_count,
        "failure_count": failure_count,
        "success_rate": success_count / len(entries) if entries else 0,
        "services": sorted(services),
        "environments": sorted(environments),
    }
