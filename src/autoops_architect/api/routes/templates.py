"""Template-related API routes."""

import re
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from autoops_architect.api.models import TemplateResponse, WorkflowResponse
from autoops_architect.api.routes.workflows import _active_workflows, _workflow_to_response
from autoops_architect.models.goal import Goal
from autoops_architect.templates.registry import create_default_template_registry

router = APIRouter(prefix="/templates", tags=["templates"])

# Initialize template registry
_template_registry = create_default_template_registry()


@router.get("", response_model=list[TemplateResponse])
async def list_templates(
    category: Optional[str] = Query(default=None, description="Filter by category"),
    tag: Optional[str] = Query(default=None, description="Filter by tag"),
) -> list[TemplateResponse]:
    """List all available workflow templates."""
    templates = _template_registry.list(category=category)

    if tag:
        templates = [t for t in templates if tag.lower() in [tg.lower() for tg in t.tags]]

    return [
        TemplateResponse(
            id=t.id,
            name=t.name,
            description=t.description,
            category=t.category,
            tags=t.tags,
            variables=_extract_template_variables(t.nodes),
        )
        for t in templates
    ]


def _extract_template_variables(nodes: list) -> list[str]:
    """Extract variable names from template nodes."""
    variables = set()
    pattern = r"\{\{(\w+)\}\}"

    for node in nodes:
        # Check all string fields that might contain variables
        for value in [node.name, node.description, str(node.params)]:
            matches = re.findall(pattern, value)
            variables.update(matches)

    return sorted(variables)


@router.get("/{template_id}", response_model=TemplateResponse)
async def get_template(template_id: str) -> TemplateResponse:
    """Get a specific template by ID."""
    template = _template_registry.get(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    return TemplateResponse(
        id=template.id,
        name=template.name,
        description=template.description,
        category=template.category,
        tags=template.tags,
        variables=_extract_template_variables(template.nodes),
    )


@router.post("/{template_id}/instantiate", response_model=WorkflowResponse)
async def instantiate_template(
    template_id: str,
    goal_description: str = Query(..., description="Goal description for the workflow"),
    service: Optional[str] = Query(default=None, description="Target service name"),
    duration: str = Query(default="1h", description="Time window for data collection"),
) -> WorkflowResponse:
    """
    Instantiate a workflow from a template.

    This creates a concrete workflow from a template, substituting
    variables with the provided values.
    """
    template = _template_registry.get(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    try:
        workflow = template.instantiate(
            goal_description=goal_description,
            service=service,
            duration=duration,
        )
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to instantiate template: {str(e)}",
        )

    # Store the workflow
    _active_workflows[workflow.id] = workflow

    return _workflow_to_response(workflow)


@router.get("/categories", response_model=list[str])
async def list_categories() -> list[str]:
    """List all template categories."""
    templates = _template_registry.list()
    categories = sorted(set(t.category for t in templates))
    return categories


@router.get("/search", response_model=list[TemplateResponse])
async def search_templates(
    q: str = Query(..., min_length=2, description="Search query"),
) -> list[TemplateResponse]:
    """
    Search templates by keyword.

    Searches template names, descriptions, and tags.
    """
    templates = _template_registry.list()
    query_lower = q.lower()

    results = []
    for t in templates:
        # Score each template based on matches
        score = 0
        if query_lower in t.name.lower():
            score += 3
        if query_lower in t.description.lower():
            score += 2
        for tag in t.tags:
            if query_lower in tag.lower():
                score += 1

        if score > 0:
            results.append((score, t))

    # Sort by score descending
    results.sort(key=lambda x: x[0], reverse=True)

    return [
        TemplateResponse(
            id=t.id,
            name=t.name,
            description=t.description,
            category=t.category,
            tags=t.tags,
            variables=_extract_template_variables(t.nodes),
        )
        for _, t in results
    ]
