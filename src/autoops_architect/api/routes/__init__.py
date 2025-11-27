"""API route modules."""

from autoops_architect.api.routes.memory import router as memory_router
from autoops_architect.api.routes.templates import router as templates_router
from autoops_architect.api.routes.workflows import router as workflows_router

__all__ = ["workflows_router", "templates_router", "memory_router"]
