"""Template loader for loading templates from files and directories."""

import json
import logging
import os
from pathlib import Path
from typing import Optional

import yaml

from autoops_architect.templates.registry import TemplateRegistry, WorkflowTemplate

logger = logging.getLogger(__name__)


def get_builtin_templates_dir() -> Path:
    """
    Get the directory containing built-in YAML templates.

    Returns:
        Path to the templates/ directory in the project root.
    """
    # Try to find relative to this file
    module_dir = Path(__file__).parent.parent.parent.parent
    templates_dir = module_dir / "templates"
    if templates_dir.exists():
        return templates_dir

    # Try current working directory
    cwd_templates = Path.cwd() / "templates"
    if cwd_templates.exists():
        return cwd_templates

    # Return module dir path even if it doesn't exist yet
    return templates_dir


def get_project_templates_dir() -> Optional[Path]:
    """
    Get the project-level templates directory.

    Looks for .autoops/templates/ in the current directory
    or any parent directory (like .git discovery).

    Returns:
        Path to project templates or None if not found.
    """
    current = Path.cwd()

    # Walk up the directory tree
    for parent in [current] + list(current.parents):
        project_dir = parent / ".autoops" / "templates"
        if project_dir.exists():
            return project_dir

        # Stop at git root or filesystem root
        if (parent / ".git").exists():
            # Return the path even if templates dir doesn't exist
            return parent / ".autoops" / "templates"

    return None


class TemplateLoader:
    """
    Load workflow templates from files and directories.

    Supports JSON and YAML formats.
    """

    @staticmethod
    def load_from_file(file_path: str | Path) -> WorkflowTemplate:
        """
        Load a single template from a file.

        Args:
            file_path: Path to the template file (JSON or YAML).

        Returns:
            The loaded WorkflowTemplate.

        Raises:
            FileNotFoundError: If the file doesn't exist.
            ValueError: If the file format is invalid.
        """
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"Template file not found: {path}")

        content = path.read_text()

        if path.suffix in (".yaml", ".yml"):
            data = yaml.safe_load(content)
        elif path.suffix == ".json":
            data = json.loads(content)
        else:
            raise ValueError(f"Unsupported file format: {path.suffix}")

        return WorkflowTemplate.model_validate(data)

    @staticmethod
    def load_from_directory(
        directory: str | Path,
        recursive: bool = False,
    ) -> list[WorkflowTemplate]:
        """
        Load all templates from a directory.

        Args:
            directory: Path to the templates directory.
            recursive: Whether to search subdirectories.

        Returns:
            List of loaded templates.
        """
        path = Path(directory)

        if not path.exists():
            raise FileNotFoundError(f"Template directory not found: {path}")

        if not path.is_dir():
            raise ValueError(f"Not a directory: {path}")

        templates = []
        patterns = ["*.json", "*.yaml", "*.yml"]

        for pattern in patterns:
            if recursive:
                files = path.rglob(pattern)
            else:
                files = path.glob(pattern)

            for file_path in files:
                try:
                    template = TemplateLoader.load_from_file(file_path)
                    templates.append(template)
                except Exception as e:
                    # Log warning but continue loading other templates
                    print(f"Warning: Failed to load template {file_path}: {e}")

        return templates

    @staticmethod
    def load_into_registry(
        registry: TemplateRegistry,
        source: str | Path,
        recursive: bool = False,
    ) -> int:
        """
        Load templates from a file or directory into a registry.

        Args:
            registry: The registry to load templates into.
            source: Path to a file or directory.
            recursive: Whether to search subdirectories (for directories).

        Returns:
            Number of templates loaded.
        """
        path = Path(source)
        count = 0

        if path.is_file():
            template = TemplateLoader.load_from_file(path)
            registry.register(template)
            count = 1
        elif path.is_dir():
            templates = TemplateLoader.load_from_directory(path, recursive=recursive)
            for template in templates:
                try:
                    registry.register(template)
                    count += 1
                except ValueError:
                    # Template already registered
                    pass

        return count

    @staticmethod
    def save_template(
        template: WorkflowTemplate,
        file_path: str | Path,
        format: str = "yaml",
    ) -> None:
        """
        Save a template to a file.

        Args:
            template: The template to save.
            file_path: Destination file path.
            format: Output format ("json" or "yaml").
        """
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = template.model_dump(mode="json")

        if format == "yaml":
            content = yaml.dump(data, default_flow_style=False, sort_keys=False)
        else:
            content = json.dumps(data, indent=2, default=str)

        path.write_text(content)


def get_user_templates_dir() -> Path:
    """
    Get the user's templates directory.

    Creates it if it doesn't exist.

    Returns:
        Path to ~/.autoops/templates/
    """
    templates_dir = Path.home() / ".autoops" / "templates"
    templates_dir.mkdir(parents=True, exist_ok=True)
    return templates_dir


def discover_template_directories() -> list[Path]:
    """
    Discover all template directories in priority order.

    Order (later sources override earlier):
    1. Built-in templates (from package)
    2. Project templates (.autoops/templates/)
    3. User templates (~/.autoops/templates/)

    Returns:
        List of existing template directories.
    """
    directories = []

    # Built-in templates
    builtin_dir = get_builtin_templates_dir()
    if builtin_dir.exists():
        directories.append(builtin_dir)

    # Project templates
    project_dir = get_project_templates_dir()
    if project_dir and project_dir.exists():
        directories.append(project_dir)

    # User templates
    user_dir = get_user_templates_dir()
    if user_dir.exists():
        directories.append(user_dir)

    return directories


def load_all_file_templates() -> list[WorkflowTemplate]:
    """
    Load templates from all discovered directories.

    Returns:
        List of all loaded templates from files.
    """
    templates = []
    seen_ids = set()

    # Load in order, later templates override earlier ones
    for directory in discover_template_directories():
        dir_templates = TemplateLoader.load_from_directory(directory, recursive=True)
        for template in dir_templates:
            # Keep track of IDs - later directories win
            if template.id in seen_ids:
                # Remove the old one
                templates = [t for t in templates if t.id != template.id]
            seen_ids.add(template.id)
            templates.append(template)

    return templates


def create_registry_with_file_templates(
    include_builtin_code: bool = True,
) -> TemplateRegistry:
    """
    Create a template registry with both code-defined and file-based templates.

    This is the recommended way to get a registry with all available templates.

    Args:
        include_builtin_code: Whether to include code-defined built-in templates.

    Returns:
        A TemplateRegistry with all templates.
    """
    from autoops_architect.templates.registry import (
        create_default_template_registry,
        get_builtin_templates,
    )

    registry = TemplateRegistry()

    # First add code-defined templates
    if include_builtin_code:
        for template in get_builtin_templates():
            try:
                registry.register(template)
            except ValueError:
                pass  # Skip duplicates

    # Then add file-based templates (can override code-defined ones)
    file_templates = load_all_file_templates()
    for template in file_templates:
        try:
            registry.register(template)
        except ValueError:
            # Template ID already exists, this is a code-defined template
            # We can't override in-place, so we just skip
            logger.debug(f"Template {template.id} already registered from code")

    return registry


class TemplateDiscovery:
    """
    Utility class for discovering and managing templates across multiple sources.
    """

    def __init__(self) -> None:
        """Initialize template discovery."""
        self._cache: Optional[list[WorkflowTemplate]] = None

    def get_template_sources(self) -> dict[str, Path]:
        """
        Get information about all template sources.

        Returns:
            Dict mapping source names to paths.
        """
        sources = {}

        builtin_dir = get_builtin_templates_dir()
        if builtin_dir.exists():
            sources["builtin"] = builtin_dir

        project_dir = get_project_templates_dir()
        if project_dir and project_dir.exists():
            sources["project"] = project_dir

        user_dir = get_user_templates_dir()
        if user_dir.exists():
            sources["user"] = user_dir

        return sources

    def list_templates_by_source(self) -> dict[str, list[WorkflowTemplate]]:
        """
        List templates grouped by source.

        Returns:
            Dict mapping source names to template lists.
        """
        result = {}

        for source_name, source_path in self.get_template_sources().items():
            templates = TemplateLoader.load_from_directory(source_path, recursive=True)
            result[source_name] = templates

        return result

    def find_template(
        self,
        template_id: str,
    ) -> Optional[tuple[WorkflowTemplate, str]]:
        """
        Find a template by ID and return it with its source.

        Args:
            template_id: The template ID to find.

        Returns:
            Tuple of (template, source_name) or None.
        """
        # Search in reverse priority order (user, project, builtin)
        for source_name, source_path in reversed(list(self.get_template_sources().items())):
            templates = TemplateLoader.load_from_directory(source_path, recursive=True)
            for template in templates:
                if template.id == template_id:
                    return (template, source_name)

        return None

    def refresh(self) -> None:
        """Clear the template cache to force reload."""
        self._cache = None


# Global discovery instance for convenience
_discovery = TemplateDiscovery()
