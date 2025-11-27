"""Export formats for workflows."""

import json
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import yaml

from autoops_architect.models.workflow import WorkflowGraph


class ExportFormat(str, Enum):
    """Supported export formats."""
    YAML = "yaml"
    JSON = "json"
    MERMAID = "mermaid"
    DOT = "dot"
    ARGO = "argo"
    GITHUB_ACTIONS = "github-actions"


class WorkflowExporter:
    """
    Export workflows to various formats.

    Supports exporting to:
    - YAML: Standard AutoOps format
    - JSON: For programmatic use
    - Mermaid: For documentation
    - DOT: For Graphviz
    - Argo: For Argo Workflows
    - GitHub Actions: For CI/CD
    """

    def __init__(self, workflow: WorkflowGraph) -> None:
        """Initialize exporter with a workflow."""
        self.workflow = workflow

    def export(self, format: ExportFormat) -> str:
        """
        Export workflow to the specified format.

        Args:
            format: Target export format.

        Returns:
            Exported content as string.
        """
        exporters = {
            ExportFormat.YAML: self._to_yaml,
            ExportFormat.JSON: self._to_json,
            ExportFormat.MERMAID: self._to_mermaid,
            ExportFormat.DOT: self._to_dot,
            ExportFormat.ARGO: self._to_argo,
            ExportFormat.GITHUB_ACTIONS: self._to_github_actions,
        }

        exporter = exporters.get(format)
        if not exporter:
            raise ValueError(f"Unsupported format: {format}")

        return exporter()

    def save(self, path: Path, format: Optional[ExportFormat] = None) -> None:
        """
        Save workflow to file.

        Args:
            path: Output file path.
            format: Optional format (auto-detected from extension if not provided).
        """
        if format is None:
            format = self._detect_format(path)

        content = self.export(format)
        path.write_text(content)

    def _detect_format(self, path: Path) -> ExportFormat:
        """Detect format from file extension."""
        suffix = path.suffix.lower()
        format_map = {
            ".yaml": ExportFormat.YAML,
            ".yml": ExportFormat.YAML,
            ".json": ExportFormat.JSON,
            ".mmd": ExportFormat.MERMAID,
            ".dot": ExportFormat.DOT,
        }
        return format_map.get(suffix, ExportFormat.YAML)

    def _to_yaml(self) -> str:
        """Export to YAML format."""
        return self.workflow.to_yaml()

    def _to_json(self) -> str:
        """Export to JSON format."""
        return self.workflow.model_dump_json(indent=2)

    def _to_mermaid(self) -> str:
        """Export to Mermaid diagram."""
        return self.workflow.to_mermaid()

    def _to_dot(self) -> str:
        """Export to Graphviz DOT format."""
        return self.workflow.to_dot()

    def _to_argo(self) -> str:
        """
        Export to Argo Workflows format.

        Generates a Workflow manifest compatible with Argo Workflows.
        """
        argo_workflow = {
            "apiVersion": "argoproj.io/v1alpha1",
            "kind": "Workflow",
            "metadata": {
                "generateName": f"{self.workflow.id}-",
                "labels": {
                    "app": "autoops-architect",
                    "workflow-id": self.workflow.id,
                },
            },
            "spec": {
                "entrypoint": "main",
                "templates": [],
            },
        }

        # Generate DAG template
        dag_template = {
            "name": "main",
            "dag": {
                "tasks": [],
            },
        }

        # Build dependency map
        node_deps = {node.id: [] for node in self.workflow.nodes}
        for edge in self.workflow.edges:
            node_deps[edge.to_node_id].append(edge.from_node_id)

        # Create tasks
        for node in self.workflow.nodes:
            task = {
                "name": node.id,
                "template": f"task-{node.id}",
            }

            if node_deps[node.id]:
                task["dependencies"] = node_deps[node.id]

            dag_template["dag"]["tasks"].append(task)

            # Create task template
            task_template = {
                "name": f"task-{node.id}",
                "container": {
                    "image": "autoops-architect/runner:latest",
                    "command": ["autoops-runner"],
                    "args": [
                        "--tool", node.tool or "echo",
                        "--params", json.dumps(node.params),
                    ],
                    "resources": {
                        "requests": {
                            "memory": "256Mi",
                            "cpu": "100m",
                        },
                    },
                },
                "metadata": {
                    "labels": {
                        "node-type": node.type.value,
                        "node-id": node.id,
                    },
                },
            }

            argo_workflow["spec"]["templates"].append(task_template)

        argo_workflow["spec"]["templates"].insert(0, dag_template)

        return yaml.dump(argo_workflow, default_flow_style=False, sort_keys=False)

    def _to_github_actions(self) -> str:
        """
        Export to GitHub Actions workflow format.

        Generates a workflow file for GitHub Actions.
        """
        # Sort nodes topologically for job ordering
        sorted_nodes = self.workflow.topological_sort()

        # Build dependency map
        node_deps = {node.id: [] for node in self.workflow.nodes}
        for edge in self.workflow.edges:
            node_deps[edge.to_node_id].append(edge.from_node_id)

        gha_workflow = {
            "name": self.workflow.name,
            "on": {
                "workflow_dispatch": {
                    "inputs": {
                        "dry_run": {
                            "description": "Run in dry-run mode",
                            "required": False,
                            "default": "false",
                            "type": "boolean",
                        },
                    },
                },
            },
            "env": {
                "WORKFLOW_ID": self.workflow.id,
                "GOAL": self.workflow.goal_description,
            },
            "jobs": {},
        }

        for node in sorted_nodes:
            job = {
                "runs-on": "ubuntu-latest",
                "steps": [
                    {
                        "name": "Checkout",
                        "uses": "actions/checkout@v4",
                    },
                    {
                        "name": "Setup Python",
                        "uses": "actions/setup-python@v5",
                        "with": {
                            "python-version": "3.11",
                        },
                    },
                    {
                        "name": "Install AutoOps",
                        "run": "pip install autoops-architect",
                    },
                    {
                        "name": f"Execute: {node.name}",
                        "run": (
                            f"autoops run-node "
                            f"--tool '{node.tool or 'echo'}' "
                            f"--params '{json.dumps(node.params)}'"
                        ),
                        "env": {
                            "NODE_ID": node.id,
                            "NODE_TYPE": node.type.value,
                        },
                    },
                ],
            }

            # Add dependencies (convert to valid job names)
            if node_deps[node.id]:
                job["needs"] = [
                    dep.replace("-", "_") for dep in node_deps[node.id]
                ]

            # Use valid job name
            job_name = node.id.replace("-", "_")
            gha_workflow["jobs"][job_name] = job

        return yaml.dump(gha_workflow, default_flow_style=False, sort_keys=False)


# Convenience functions

def export_to_yaml(workflow: WorkflowGraph) -> str:
    """Export workflow to YAML."""
    return WorkflowExporter(workflow).export(ExportFormat.YAML)


def export_to_json(workflow: WorkflowGraph) -> str:
    """Export workflow to JSON."""
    return WorkflowExporter(workflow).export(ExportFormat.JSON)


def export_to_argo(workflow: WorkflowGraph) -> str:
    """Export workflow to Argo Workflows format."""
    return WorkflowExporter(workflow).export(ExportFormat.ARGO)


def export_to_mermaid(workflow: WorkflowGraph) -> str:
    """Export workflow to Mermaid diagram."""
    return WorkflowExporter(workflow).export(ExportFormat.MERMAID)


def export_to_github_actions(workflow: WorkflowGraph) -> str:
    """Export workflow to GitHub Actions format."""
    return WorkflowExporter(workflow).export(ExportFormat.GITHUB_ACTIONS)
