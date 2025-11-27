"""Workflow templates for common operations scenarios."""

from autoops_architect.templates.registry import (
    TemplateRegistry,
    WorkflowTemplate,
    get_builtin_templates,
)
from autoops_architect.templates.loader import TemplateLoader

__all__ = [
    "TemplateRegistry",
    "WorkflowTemplate",
    "TemplateLoader",
    "get_builtin_templates",
]
