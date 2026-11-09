"""API route modules."""

from autoops_architect.api.routes.auth import router as auth_router
from autoops_architect.api.routes.memory import router as memory_router
from autoops_architect.api.routes.schedules import router as schedules_router
from autoops_architect.api.routes.templates import router as templates_router
from autoops_architect.api.routes.webhooks import router as webhooks_router
from autoops_architect.api.routes.workflows import router as workflows_router

__all__ = [
    "auth_router",
    "memory_router",
    "schedules_router",
    "templates_router",
    "webhooks_router",
    "workflows_router",
]
