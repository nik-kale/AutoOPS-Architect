"""Tests for creating, running and inspecting workflows through the API."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from autoops_architect import scheduler
from autoops_architect.api.app import create_app
from autoops_architect.api.routes.schedules import execute_scheduled_workflow
from autoops_architect.api.routes.workflows import _active_workflows
from autoops_architect.executor.engine import WorkflowExecutor
from autoops_architect.memory.backend import get_memory_backend
from autoops_architect.models.execution import ExecutionStatus, WorkflowRunResult
from autoops_architect.models.goal import Goal
from autoops_architect.models.workflow import Node, NodeType, WorkflowGraph
from autoops_architect.scheduler import (
    Schedule,
    _schedules_db,
    get_schedule_executions,
)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


def create_from_template(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/api/v1/workflows",
        json={
            "description": "Investigate errors in the checkout service",
            "use_template": "error-rate-investigation",
            "services": ["checkout-api"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def run(client: TestClient, workflow_id: str, *, dry_run: bool = True) -> dict[str, Any]:
    started = client.post(f"/api/v1/workflows/{workflow_id}/execute", params={"dry_run": dry_run})
    assert started.status_code == 200, started.text
    execution_id = started.json()["execution_id"]
    status = client.get(f"/api/v1/workflows/{workflow_id}/execute/{execution_id}")
    assert status.status_code == 200, status.text
    return status.json()


class TestCreateWorkflow:
    def test_goal_without_environment_or_priority(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/workflows",
            json={"description": "Investigate slow responses on the login API"},
        )

        assert response.status_code == 200, response.text
        assert response.json()["goal_description"].startswith("Investigate slow")

    def test_unrecognised_environment_is_not_an_error(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/workflows",
            json={
                "description": "Investigate slow responses on the login API",
                "environment": "not-an-environment",
                "priority": "not-a-priority",
                "time_window": "last 1 hour",
            },
        )

        assert response.status_code == 200, response.text

    def test_oversized_service_list_is_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/workflows",
            json={
                "description": "Investigate slow responses on the login API",
                "services": [f"svc-{i}" for i in range(51)],
            },
        )

        assert response.status_code == 422


class TestExecution:
    @pytest.mark.parametrize("dry_run", [True, False])
    def test_execution_runs_every_node(self, client: TestClient, dry_run: bool) -> None:
        workflow = create_from_template(client)

        status = run(client, workflow["id"], dry_run=dry_run)

        assert status["status"] == "completed"
        assert status["success_count"] == len(workflow["nodes"])
        assert status["failed_count"] == 0

    def test_disabled_nodes_are_not_executed(self, client: TestClient) -> None:
        workflow = create_from_template(client)
        patched = client.patch(
            f"/api/v1/workflows/{workflow['id']}",
            json={"disabled_node_ids": ["generate-summary"]},
        )
        assert patched.status_code == 200

        status = run(client, workflow["id"])

        executed = {r["node_id"] for r in status["node_results"]}
        assert "generate-summary" not in executed
        assert status["success_count"] == len(workflow["nodes"]) - 1

    def test_stream_reports_node_events_and_ends(self, client: TestClient) -> None:
        workflow = create_from_template(client)
        started = client.post(
            f"/api/v1/workflows/{workflow['id']}/execute", params={"dry_run": True}
        )
        execution_id = started.json()["execution_id"]

        stream = client.get(f"/api/v1/workflows/{workflow['id']}/execute/{execution_id}/stream")

        assert '"event_type":"node_started"' in stream.text
        assert '"event_type":"node_completed"' in stream.text
        assert '"event_type":"workflow_completed"' in stream.text
        assert "stream_end" in stream.text

    def test_execution_is_not_visible_under_another_workflow(self, client: TestClient) -> None:
        workflow = create_from_template(client)
        started = client.post(
            f"/api/v1/workflows/{workflow['id']}/execute", params={"dry_run": True}
        )
        execution_id = started.json()["execution_id"]

        status = client.get(f"/api/v1/workflows/other-workflow/execute/{execution_id}")
        stream = client.get(f"/api/v1/workflows/other-workflow/execute/{execution_id}/stream")

        assert status.status_code == 404
        assert stream.status_code == 404

    def test_executor_crash_marks_execution_failed(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def crash(_self: WorkflowExecutor, _workflow: WorkflowGraph) -> None:
            raise RuntimeError("executor exploded")

        monkeypatch.setattr(WorkflowExecutor, "execute", crash)
        workflow = create_from_template(client)

        status = run(client, workflow["id"])

        assert status["status"] == "failed"
        assert status["completed_at"] is not None


class TestStaticRoutes:
    """Routes that used to be shadowed by a /{id} route declared before them."""

    def test_template_categories(self, client: TestClient) -> None:
        response = client.get("/api/v1/templates/categories")

        assert response.status_code == 200
        assert "error_investigation" in response.json()

    def test_template_search(self, client: TestClient) -> None:
        response = client.get("/api/v1/templates/search", params={"q": "latency"})

        assert response.status_code == 200
        assert any("latency" in t["id"] for t in response.json())

    def test_memory_stats_counts_failed_runs(self, client: TestClient) -> None:
        backend = get_memory_backend(backend_type="json")
        goal = Goal(description="Investigate errors in the checkout service")
        workflow = WorkflowGraph(
            id="wf-stats",
            name="Stats",
            goal_description=goal.description,
            nodes=[Node(id="n1", name="N1", type=NodeType.ANALYSIS, tool="echo")],
        )
        for status in (ExecutionStatus.SUCCESS, ExecutionStatus.FAILED):
            result = WorkflowRunResult(
                workflow_id=workflow.id,
                goal_description=goal.description,
                overall_status=status,
            )
            backend.save_workflow_run(goal, workflow, result)

        stats = client.get("/api/v1/memory/stats").json()

        assert stats["total_entries"] == 2
        assert stats["success_count"] == 1
        assert stats["failure_count"] == 1
        assert stats["success_rate"] == 0.5

    def test_metrics_endpoint_is_served(self, client: TestClient) -> None:
        response = client.get("/metrics")

        assert response.status_code == 200
        assert "autoops_workflow_executions_total" in response.text


class TestSchedules:
    @pytest.fixture(autouse=True)
    def clean_schedules(self) -> Iterator[None]:
        yield
        _schedules_db.clear()

    def test_scheduler_stops_with_the_app(self) -> None:
        with TestClient(create_app()) as test_client:
            created = test_client.post(
                "/api/v1/schedules",
                json={"name": "Nightly", "cron": "0 9 * * *"},
            )
            assert created.status_code == 201, created.text
            assert scheduler._scheduler is not None

        assert scheduler._scheduler is None

    def test_unknown_timezone_is_a_client_error(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/schedules",
            json={"name": "Nightly", "cron": "0 9 * * *", "timezone": "Mars/Olympus"},
        )

        assert response.status_code == 400

    async def test_scheduled_template_run_uses_the_template(self) -> None:
        schedule = Schedule(
            id="sched-template",
            name="Nightly check",
            cron="0 9 * * *",
            template_id="latency-investigation",
            goal_description="Check latency for the checkout service",
            parameters={"services": ["checkout-api"]},
        )
        _schedules_db[schedule.id] = schedule

        await execute_scheduled_workflow(schedule.id)

        execution = get_schedule_executions(schedule.id)[0]
        assert execution.status == "completed"
        workflow = _active_workflows[execution.workflow_id or ""]
        assert workflow.metadata["template_id"] == "latency-investigation"
