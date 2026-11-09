"""Workflow templates for common operations scenarios."""

from autoops_architect.templates.loader import (
    TemplateDiscovery,
    TemplateLoader,
    create_registry_with_file_templates,
    discover_template_directories,
    get_builtin_templates_dir,
    get_project_templates_dir,
    get_user_templates_dir,
    load_all_file_templates,
)
from autoops_architect.templates.registry import (
    TemplateRegistry,
    WorkflowTemplate,
    create_default_template_registry,
    get_builtin_templates,
)

__all__ = [
    "TemplateRegistry",
    "WorkflowTemplate",
    "TemplateLoader",
    "TemplateDiscovery",
    "get_builtin_templates",
    "get_user_templates_dir",
    "get_builtin_templates_dir",
    "get_project_templates_dir",
    "discover_template_directories",
    "load_all_file_templates",
    "create_default_template_registry",
    "create_registry_with_file_templates",
]
