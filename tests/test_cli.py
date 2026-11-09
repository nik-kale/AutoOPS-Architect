"""Tests for CLI output and the `run` and `memory` commands."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from autoops_architect.cli import app
from autoops_architect.memory.backend import get_memory_backend
from autoops_architect.models.execution import ExecutionStatus, WorkflowRunResult
from autoops_architect.models.goal import Goal
from autoops_architect.models.workflow import Node, NodeType, WorkflowGraph

runner = CliRunner()

GOAL = "Investigate elevated errors for the checkout service"


def write_workflow(path: Path, goal: str = GOAL, name: str = "Check logs") -> Path:
    workflow = WorkflowGraph(
        id="wf-cli",
        name=name,
        goal_description=goal,
        nodes=[Node(id="n1", name=name, type=NodeType.ANALYSIS, tool="echo")],
    )
    path.write_text(workflow.model_dump_json())
    return path


@pytest.fixture
def saved_entry() -> str:
    goal = Goal(description=GOAL)
    workflow = WorkflowGraph(id="wf-saved", name="Saved", goal_description=goal.description)
    result = WorkflowRunResult(
        workflow_id=workflow.id,
        goal_description=goal.description,
        overall_status=ExecutionStatus.SUCCESS,
    )
    return get_memory_backend().save_workflow_run(goal, workflow, result)


class TestMarkupSafety:
    def test_goal_with_closing_tag_does_not_crash_plan(self) -> None:
        result = runner.invoke(app, ["plan", "Find errors [/bold] in checkout logs", "--mock"])

        assert result.exit_code == 0, result.output
        assert "[/bold]" in result.output

    def test_node_type_is_displayed(self) -> None:
        result = runner.invoke(app, ["plan", GOAL, "--mock"])

        assert result.exit_code == 0, result.output
        assert "[log_collection]" in result.output

    def test_node_name_with_markup_is_shown_literally(self, tmp_path: Path) -> None:
        path = write_workflow(tmp_path / "wf.json", name="Check [red]logs[/red]")

        result = runner.invoke(app, ["run", str(path), "--dry-run"])

        assert result.exit_code == 0, result.output
        assert "[red]logs[/red]" in result.output

    def test_parse_error_containing_brackets_is_reported(self, tmp_path: Path) -> None:
        path = tmp_path / "wf.json"
        path.write_text(json.dumps({"id": "x", "name": ""}))

        result = runner.invoke(app, ["run", str(path)])

        assert result.exit_code == 1
        assert result.exception is None or isinstance(result.exception, SystemExit)
        assert "Error parsing workflow" in result.output


class TestRunCommand:
    def test_result_panel_is_shown(self, tmp_path: Path) -> None:
        path = write_workflow(tmp_path / "wf.json")

        result = runner.invoke(app, ["run", str(path), "--dry-run"])

        assert result.exit_code == 0, result.output
        assert "1 succeeded" in result.output

    def test_result_panel_is_shown_without_a_duration(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from autoops_architect.executor.engine import WorkflowExecutor

        path = write_workflow(tmp_path / "wf.json")

        def no_timing(self: WorkflowExecutor, workflow: WorkflowGraph) -> WorkflowRunResult:
            return WorkflowRunResult(
                workflow_id=workflow.id,
                goal_description=workflow.goal_description,
                overall_status=ExecutionStatus.SUCCESS,
            )

        monkeypatch.setattr(WorkflowExecutor, "execute_sync", no_timing)

        result = runner.invoke(app, ["run", str(path)])

        assert result.exit_code == 0, result.output
        assert "SUCCESS" in result.output

    def test_short_goal_in_a_workflow_file_is_saved(self, tmp_path: Path) -> None:
        path = write_workflow(tmp_path / "wf.json", goal="Short")

        result = runner.invoke(app, ["run", str(path), "--dry-run"])

        assert result.exit_code == 0, result.output
        assert "Saved to memory" in result.output


class TestMemoryShow:
    def test_created_date_is_shown_without_a_duration(self, saved_entry: str) -> None:
        result = runner.invoke(app, ["memory", "show", saved_entry])

        assert result.exit_code == 0, result.output
        assert GOAL[:30] in result.output
        assert "Created:" in result.output

    def test_goal_and_created_are_shown_with_a_duration(self) -> None:
        goal = Goal(description=GOAL)
        workflow = WorkflowGraph(id="wf-timed", name="Timed", goal_description=goal.description)
        result_with_time = WorkflowRunResult(
            workflow_id=workflow.id,
            goal_description=goal.description,
            overall_status=ExecutionStatus.SUCCESS,
            started_at="2026-01-01T00:00:00",
            finished_at="2026-01-01T00:00:05",
        )
        entry_id = get_memory_backend().save_workflow_run(goal, workflow, result_with_time)

        result = runner.invoke(app, ["memory", "show", entry_id])

        assert result.exit_code == 0, result.output
        assert GOAL[:30] in result.output
        assert "Duration:" in result.output
        assert "Created:" in result.output
