"""Tests for API authentication coverage, approval integrity and CORS."""

import re
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from autoops_architect.api.app import create_app
from autoops_architect.api.auth import (
    Role,
    bootstrap_admin_from_env,
    create_access_token,
    create_api_key,
    fake_api_keys_db,
    fake_users_db,
    get_password_hash,
    verify_password,
)
from autoops_architect.api.routes.workflows import _active_workflows
from autoops_architect.models.workflow import Node, NodeType, WorkflowGraph

PUBLIC_ROUTES = {
    ("POST", "/api/v1/auth/login"),
    ("GET", "/api/v1/auth/permissions"),
}


def protected_routes() -> list[tuple[str, str]]:
    routes: list[tuple[str, str]] = []
    for path, operations in create_app().openapi()["paths"].items():
        if path.startswith("/api/v1"):
            for method in operations:
                if (method.upper(), path) not in PUBLIC_ROUTES:
                    routes.append((method.upper(), path))
    assert routes, "expected the API to declare routes"
    return sorted(routes)


@pytest.fixture
def auth_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("AUTOOPS_AUTH_ENABLED", "true")
    yield
    fake_api_keys_db.clear()
    fake_users_db.clear()


@pytest.fixture
def restart_workflow() -> Iterator[str]:
    workflow = WorkflowGraph(
        id="wf-restart",
        name="Restart",
        goal_description="Restart the service",
        nodes=[Node(id="restart", name="Restart", type=NodeType.SERVICE_RESTART, tool="shell")],
    )
    _active_workflows[workflow.id] = workflow
    yield workflow.id
    _active_workflows.pop(workflow.id, None)


class TestEveryRouteRequiresAuth:
    @pytest.mark.usefixtures("auth_on")
    @pytest.mark.parametrize(("method", "path"), protected_routes())
    def test_rejected_without_credentials(self, method: str, path: str) -> None:
        client = TestClient(create_app())
        url = re.sub(r"\{[^}]+\}", "x", path)

        response = client.request(method, url, json={})

        assert response.status_code == 401, f"{method} {path} -> {response.status_code}"

    @pytest.mark.usefixtures("auth_on")
    def test_metrics_requires_credentials(self) -> None:
        assert TestClient(create_app()).get("/metrics").status_code == 401

    @pytest.mark.usefixtures("auth_on")
    def test_viewer_cannot_delete_memory(self) -> None:
        key, _ = create_api_key("viewer-key", [Role.VIEWER])

        response = TestClient(create_app()).delete(
            "/api/v1/memory/some-entry", headers={"X-API-Key": key}
        )

        assert response.status_code == 403

    @pytest.mark.usefixtures("auth_on")
    def test_viewer_can_read_memory(self) -> None:
        key, _ = create_api_key("viewer-key", [Role.VIEWER])

        response = TestClient(create_app()).get("/api/v1/memory", headers={"X-API-Key": key})

        assert response.status_code == 200

    def test_routes_stay_open_when_auth_is_off(self) -> None:
        assert TestClient(create_app()).get("/api/v1/memory").status_code == 200

    @pytest.mark.usefixtures("auth_on")
    def test_garbage_token_is_rejected(self) -> None:
        response = TestClient(create_app()).get(
            "/api/v1/memory", headers={"Authorization": "Bearer not-a-token"}
        )

        assert response.status_code == 401

    @pytest.mark.usefixtures("auth_on")
    def test_token_for_deleted_user_is_rejected(self) -> None:
        token = create_access_token({"sub": "ghost", "roles": ["admin"]})

        response = TestClient(create_app()).get(
            "/api/v1/memory", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 401


class TestApprovalIntegrity:
    def test_patch_cannot_remove_approval_from_dangerous_node(self, restart_workflow: str) -> None:
        client = TestClient(create_app())

        response = client.patch(
            f"/api/v1/workflows/{restart_workflow}",
            json={"nodes": [{"id": "restart", "requires_human_approval": False}]},
        )

        assert response.status_code == 400
        node = _active_workflows[restart_workflow].nodes[0]
        assert node.requires_human_approval is True

    def test_patch_can_add_approval_to_safe_node(self) -> None:
        workflow = WorkflowGraph(
            id="wf-safe",
            name="Safe",
            goal_description="Collect logs",
            nodes=[Node(id="logs", name="Logs", type=NodeType.LOG_COLLECTION, tool="echo")],
        )
        _active_workflows[workflow.id] = workflow
        client = TestClient(create_app())

        response = client.patch(
            f"/api/v1/workflows/{workflow.id}",
            json={"nodes": [{"id": "logs", "requires_human_approval": True}]},
        )

        assert response.status_code == 200
        assert response.json()["nodes"][0]["requires_human_approval"] is True
        del _active_workflows[workflow.id]


class TestCors:
    PREFLIGHT = {
        "Origin": "https://evil.example",
        "Access-Control-Request-Method": "POST",
    }

    def test_cross_origin_requests_are_not_allowed_by_default(self) -> None:
        response = TestClient(create_app()).options("/api/v1/workflows", headers=self.PREFLIGHT)

        assert "access-control-allow-origin" not in response.headers

    def test_configured_origin_is_allowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AUTOOPS_CORS_ORIGINS", "https://ops.example, https://b.example")
        headers = {**self.PREFLIGHT, "Origin": "https://ops.example"}

        response = TestClient(create_app()).options("/api/v1/workflows", headers=headers)

        assert response.headers["access-control-allow-origin"] == "https://ops.example"

    def test_wildcard_never_allows_credentials(self) -> None:
        app = create_app(cors_origins=["*"])

        response = TestClient(app).options("/api/v1/workflows", headers=self.PREFLIGHT)

        assert "access-control-allow-credentials" not in response.headers


class TestAdminBootstrap:
    @pytest.fixture(autouse=True)
    def clean_users(self) -> Iterator[None]:
        fake_users_db.clear()
        yield
        fake_users_db.clear()

    def test_no_account_without_an_explicit_password(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AUTOOPS_CREATE_ADMIN", "true")
        monkeypatch.delenv("AUTOOPS_ADMIN_PASSWORD", raising=False)

        assert bootstrap_admin_from_env() is None
        assert fake_users_db == {}

    def test_account_uses_the_configured_password(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AUTOOPS_CREATE_ADMIN", "true")
        monkeypatch.setenv("AUTOOPS_ADMIN_PASSWORD", "a-long-operator-chosen-password")

        admin = bootstrap_admin_from_env()

        assert admin is not None
        assert verify_password("a-long-operator-chosen-password", admin.hashed_password)
        assert not verify_password("admin", admin.hashed_password)


class TestPasswordHashing:
    def test_password_longer_than_bcrypt_limit(self) -> None:
        long_password = "x" * 200

        assert verify_password(long_password, get_password_hash(long_password))

    def test_malformed_hash_is_a_failed_check(self) -> None:
        assert verify_password("anything", "not-a-bcrypt-hash") is False
