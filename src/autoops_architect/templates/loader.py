"""Template loader for loading templates from files and directories."""

import json
from pathlib import Path
from typing import Optional

import yaml

from autoops_architect.templates.registry import TemplateRegistry, WorkflowTemplate


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
