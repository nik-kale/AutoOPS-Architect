"""Tests for template discovery and parameter substitution."""

import json
from pathlib import Path

import pytest

import autoops_architect
from autoops_architect.templates.loader import (
    TemplateLoader,
    create_registry_with_file_templates,
    get_builtin_templates_dir,
)
from autoops_architect.templates.registry import WorkflowTemplate, create_default_template_registry
from autoops_architect.tools.base import create_default_registry


def template_with(params: dict[str, object], parameters: dict[str, object]) -> WorkflowTemplate:
    return WorkflowTemplate.model_validate(
        {
            "id": "t",
            "name": "Template",
            "description": "Test",
            "parameters": parameters,
            "nodes": [
                {
                    "id": "n",
                    "name": "Check {{service}}",
                    "description": "For {{duration}}",
                    "type": "metric_query",
                    "tool": "metric_query",
                    "params": params,
                }
            ],
            "edges": [],
        }
    )


class TestSubstitution:
    def test_every_declared_parameter_is_substituted(self) -> None:
        template = template_with(
            {"service": "{{service}}", "duration": "{{duration}}"},
            {"service": "{{service}}", "duration": "6h"},
        )

        node = template.instantiate("Goal", service="api").nodes[0]

        assert node.params == {"service": "api", "duration": "6h"}
        assert node.name == "Check api"
        assert node.description == "For 6h"

    def test_overrides_win_over_defaults(self) -> None:
        template = template_with({"duration": "{{duration}}"}, {"duration": "6h"})

        node = template.instantiate("Goal", duration="15m").nodes[0]

        assert node.params == {"duration": "15m"}

    def test_placeholders_inside_nested_params_and_strings(self) -> None:
        template = template_with(
            {"query": {"text": "svc={{ service }} over {{duration}}", "tags": ["{{service}}"]}},
            {"duration": "1h"},
        )

        node = template.instantiate("Goal", service="api").nodes[0]

        assert node.params == {"query": {"text": "svc=api over 1h", "tags": ["api"]}}

    def test_a_lone_placeholder_keeps_the_parameter_type(self) -> None:
        template = template_with({"threshold": "{{limit}}"}, {"limit": 5.0})

        assert template.instantiate("Goal").nodes[0].params == {"threshold": 5.0}

    def test_missing_service_falls_back_to_a_real_value(self) -> None:
        template = template_with({"service": "{{service}}"}, {"service": "{{service}}"})

        workflow = template.instantiate("Goal")

        assert workflow.nodes[0].params == {"service": "unknown-service"}
        assert "{{" not in workflow.name

    def test_unknown_placeholder_is_left_alone(self) -> None:
        template = template_with({"namespace": "{{namespace}}"}, {})

        assert template.instantiate("Goal").nodes[0].params == {"namespace": "{{namespace}}"}


class TestBuiltinFiles:
    def test_builtin_templates_are_inside_the_package(self) -> None:
        package_dir = Path(autoops_architect.__file__).parent

        assert get_builtin_templates_dir().is_relative_to(package_dir)
        assert len(list(get_builtin_templates_dir().glob("*.yaml"))) >= 4

    def test_every_builtin_file_instantiates_fully(self) -> None:
        tools = create_default_registry()

        for path in get_builtin_templates_dir().glob("*.yaml"):
            template = TemplateLoader.load_from_file(path)
            workflow = template.instantiate("Goal", service="api")

            unresolved = {n.id: n.params for n in workflow.nodes if "{{" in json.dumps(n.params)}
            assert unresolved == {}, path.name
            for node in workflow.nodes:
                assert tools.resolve(node.tool)[0] is not None, f"{path.name}: {node.tool}"

    def test_file_templates_are_discovered_regardless_of_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "templates").mkdir()
        (tmp_path / "templates" / "stray.yaml").write_text(
            "id: stray\nname: Stray\ndescription: x\nnodes: []\nedges: []\n"
        )

        registry = create_registry_with_file_templates()

        assert registry.get("k8s-pod-crash-investigation") is not None
        assert registry.get("stray") is None

    def test_code_defined_templates_resolve_their_tools(self) -> None:
        tools = create_default_registry()

        for template in create_default_template_registry().list():
            for node in template.nodes:
                assert tools.resolve(node.tool)[0] is not None, node.tool
