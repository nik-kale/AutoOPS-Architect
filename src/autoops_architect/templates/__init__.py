"""Workflow templates for common operations scenarios."""

from autoops_architect.templates.registry import (
    TemplateRegistry,
    WorkflowTemplate,
    get_builtin_templates,
    create_default_template_registry,
)
from autoops_architect.templates.loader import (
    TemplateLoader,
    TemplateDiscovery,
    get_user_templates_dir,
    get_builtin_templates_dir,
    get_project_templates_dir,
    discover_template_directories,
    load_all_file_templates,
    create_registry_with_file_templates,
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
