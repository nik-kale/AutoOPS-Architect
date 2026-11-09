"""Tests for the cron scheduler and the workflow and metrics exporters."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import yaml

from autoops_architect import scheduler
from autoops_architect.export.formats import (
    ExportFormat,
    WorkflowExporter,
    export_to_argo,
    export_to_json,
    export_to_mermaid,
    export_to_yaml,
)
from autoops_architect.export.observability import (
    Tracer,
    TracingConfig,
    setup_tracing,
    trace_node_execution,
    trace_workflow_execution,
)
from autoops_architect.models.workflow import Edge, Node, NodeType, WorkflowGraph


async def noop(_schedule_id: str) -> None:
    return None


def make_schedule(schedule_id: str = "s1", cron: str = "0 9 * * *") -> scheduler.Schedule:
    return scheduler.Schedule(id=schedule_id, name="Nightly", cron=cron)


@pytest.fixture
async def clean_scheduler() -> AsyncIterator[None]:
    yield
    scheduler.shutdown_scheduler()
    scheduler._schedules_db.clear()
    scheduler._executions_db.clear()


@pytest.mark.usefixtures("clean_scheduler")
class TestScheduler:
    async def test_add_sets_the_next_run(self) -> None:
        schedule = make_schedule()

        scheduler.add_schedule(schedule, noop)

        assert schedule.next_run is not None
        assert scheduler.get_schedule("s1") is schedule
        assert scheduler.list_schedules() == [schedule]

    async def test_cron_must_have_five_fields(self) -> None:
        with pytest.raises(ValueError, match="Invalid cron"):
            scheduler.add_schedule(make_schedule(cron="* * *"), noop)

    async def test_pause_and_resume(self) -> None:
        schedule = make_schedule()
        scheduler.add_schedule(schedule, noop)

        assert scheduler.pause_schedule("s1") is True
        assert schedule.enabled is False
        assert scheduler.resume_schedule("s1") is True
        assert schedule.enabled is True

    async def test_unknown_schedules_are_reported(self) -> None:
        assert scheduler.pause_schedule("nope") is False
        assert scheduler.resume_schedule("nope") is False
        assert scheduler.remove_schedule("nope") is False
        assert scheduler.get_schedule("nope") is None

    async def test_remove(self) -> None:
        scheduler.add_schedule(make_schedule(), noop)

        assert scheduler.remove_schedule("s1") is True
        assert scheduler.list_schedules() == []

    async def test_executions_are_recorded_newest_first(self) -> None:
        schedule = make_schedule()
        scheduler.add_schedule(schedule, noop)

        scheduler.record_execution("s1", workflow_id="wf-1")
        scheduler.record_execution("s1", status="failed", error="boom")

        executions = scheduler.get_schedule_executions("s1")
        assert schedule.run_count == 2
        assert schedule.last_run is not None
        assert {e.status for e in executions} == {"completed", "failed"}
        assert all(e.completed_at is not None for e in executions)
        assert len(scheduler.get_schedule_executions("s1", limit=1)) == 1


@pytest.fixture
def workflow() -> WorkflowGraph:
    return WorkflowGraph(
        id="wf-export",
        name="Export",
        goal_description="Goal",
        nodes=[
            Node(id="collect-logs", name="A", type=NodeType.LOG_COLLECTION, tool="log_collector"),
            Node(id="summarize", name="B", type=NodeType.SUMMARY, tool="summary"),
        ],
        edges=[Edge(from_node_id="collect-logs", to_node_id="summarize")],
    )


class TestWorkflowExporter:
    def test_argo_declares_dependencies(self, workflow: WorkflowGraph) -> None:
        document = yaml.safe_load(export_to_argo(workflow))

        tasks = {t["name"]: t for t in document["spec"]["templates"][0]["dag"]["tasks"]}
        assert document["kind"] == "Workflow"
        assert tasks["summarize"]["dependencies"] == ["collect-logs"]
        assert "dependencies" not in tasks["collect-logs"]

    def test_github_actions_job_names_and_needs(self, workflow: WorkflowGraph) -> None:
        document = yaml.safe_load(WorkflowExporter(workflow).export(ExportFormat.GITHUB_ACTIONS))

        assert document["jobs"]["summarize"]["needs"] == ["collect_logs"]

    def test_text_formats(self, workflow: WorkflowGraph) -> None:
        assert yaml.safe_load(export_to_yaml(workflow))["id"] == "wf-export"
        assert '"wf-export"' in export_to_json(workflow)
        assert "graph TD" in export_to_mermaid(workflow)
        assert "digraph" in WorkflowExporter(workflow).export(ExportFormat.DOT)

    @pytest.mark.parametrize(
        ("name", "marker"),
        [
            ("o.yaml", "goal_description:"),
            ("o.json", '"nodes"'),
            ("o.mmd", "graph TD"),
            ("o.dot", "digraph"),
        ],
    )
    def test_save_detects_the_format(
        self, workflow: WorkflowGraph, tmp_path: Path, name: str, marker: str
    ) -> None:
        path = tmp_path / name

        WorkflowExporter(workflow).save(path)

        assert marker in path.read_text()


class TestTracing:
    def test_disabled_tracer_records_nothing(self) -> None:
        tracer = Tracer()

        with tracer.span("work") as span:
            span.set_attribute("a", 1)

        assert tracer._completed_spans == []

    def test_error_is_recorded_and_raised(self) -> None:
        tracer = Tracer(TracingConfig(enabled=True))

        with pytest.raises(RuntimeError), tracer.span("work"):
            raise RuntimeError("boom")

        assert tracer._completed_spans[0].status == "error"
        assert tracer._completed_spans[0].attributes["status.message"] == "boom"

    def test_span_export_shape(self) -> None:
        tracer = Tracer(TracingConfig(enabled=True))

        with tracer.span("work", attributes={"a": 1}) as span:
            span.add_event("step", {"b": 2})

        exported = tracer._completed_spans[0].to_dict()
        assert exported["name"] == "work"
        assert exported["attributes"] == [{"key": "a", "value": {"stringValue": "1"}}]
        assert exported["events"][0]["name"] == "step"

    def test_helpers_use_the_global_tracer(self) -> None:
        tracer = setup_tracing(TracingConfig(enabled=True))

        with trace_workflow_execution("wf", "Workflow"), trace_node_execution("n", "N", "analysis"):
            pass

        assert [s.name for s in tracer._completed_spans] == [
            "node.execute.analysis",
            "workflow.execute",
        ]
