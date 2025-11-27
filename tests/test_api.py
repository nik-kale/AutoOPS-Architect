"""Tests for the FastAPI application."""

import pytest

# Skip all tests if FastAPI is not installed
pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from autoops_architect.api.app import create_app


@pytest.fixture
def client():
    """Create a test client."""
    app = create_app(debug=True)
    return TestClient(app)


class TestHealthEndpoint:
    """Tests for the health check endpoint."""

    def test_health_check(self, client):
        """Test that health check returns healthy status."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data


class TestRootEndpoint:
    """Tests for the root UI endpoint."""

    def test_root_returns_html(self, client):
        """Test that root returns HTML page."""
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "AutoOps Architect" in response.text


class TestTemplatesAPI:
    """Tests for the templates API."""

    def test_list_templates(self, client):
        """Test listing templates."""
        response = client.get("/api/v1/templates")
        assert response.status_code == 200
        templates = response.json()
        assert isinstance(templates, list)
        assert len(templates) > 0

    def test_get_template(self, client):
        """Test getting a specific template."""
        # First get list of templates
        response = client.get("/api/v1/templates")
        templates = response.json()
        template_id = templates[0]["id"]

        # Get specific template
        response = client.get(f"/api/v1/templates/{template_id}")
        assert response.status_code == 200
        template = response.json()
        assert template["id"] == template_id
        assert "name" in template
        assert "description" in template

    def test_get_nonexistent_template(self, client):
        """Test getting a non-existent template."""
        response = client.get("/api/v1/templates/nonexistent-template")
        assert response.status_code == 404

    def test_search_templates(self, client):
        """Test searching templates."""
        response = client.get("/api/v1/templates/search?q=error")
        assert response.status_code == 200
        results = response.json()
        assert isinstance(results, list)

    def test_instantiate_template(self, client):
        """Test instantiating a template."""
        # Get a template first
        response = client.get("/api/v1/templates")
        templates = response.json()
        template_id = templates[0]["id"]

        # Instantiate it
        response = client.post(
            f"/api/v1/templates/{template_id}/instantiate",
            params={
                "goal_description": "Test goal",
                "service": "test-service",
            }
        )
        assert response.status_code == 200
        workflow = response.json()
        assert "id" in workflow
        assert "nodes" in workflow
        assert "edges" in workflow


class TestWorkflowsAPI:
    """Tests for the workflows API."""

    def test_list_workflows_empty(self, client):
        """Test listing workflows when empty."""
        response = client.get("/api/v1/workflows")
        assert response.status_code == 200
        workflows = response.json()
        assert isinstance(workflows, list)

    def test_create_workflow_from_template(self, client):
        """Test creating a workflow from a template."""
        # Get a template first
        response = client.get("/api/v1/templates")
        templates = response.json()
        template_id = templates[0]["id"]

        # Create workflow using template
        response = client.post(
            "/api/v1/workflows",
            json={
                "description": "Test investigating errors in checkout service",
                "services": ["checkout-api"],
                "environment": "production",
                "use_template": template_id,
            }
        )
        assert response.status_code == 200
        workflow = response.json()
        assert "id" in workflow
        assert "name" in workflow
        assert "nodes" in workflow
        assert "mermaid_diagram" in workflow
        assert "dot_diagram" in workflow

    def test_get_workflow(self, client):
        """Test getting a specific workflow."""
        # Create a workflow first
        response = client.get("/api/v1/templates")
        templates = response.json()
        template_id = templates[0]["id"]

        response = client.post(
            "/api/v1/workflows",
            json={
                "description": "Test goal for getting workflow",
                "use_template": template_id,
            }
        )
        workflow_id = response.json()["id"]

        # Get the workflow
        response = client.get(f"/api/v1/workflows/{workflow_id}")
        assert response.status_code == 200
        workflow = response.json()
        assert workflow["id"] == workflow_id

    def test_get_nonexistent_workflow(self, client):
        """Test getting a non-existent workflow."""
        response = client.get("/api/v1/workflows/nonexistent-workflow")
        assert response.status_code == 404

    def test_update_workflow(self, client):
        """Test updating a workflow."""
        # Create a workflow first
        response = client.get("/api/v1/templates")
        templates = response.json()
        template_id = templates[0]["id"]

        response = client.post(
            "/api/v1/workflows",
            json={
                "description": "Test goal for update",
                "use_template": template_id,
            }
        )
        workflow_id = response.json()["id"]

        # Update the workflow
        response = client.patch(
            f"/api/v1/workflows/{workflow_id}",
            json={
                "disabled_node_ids": ["some-node-id"],
            }
        )
        assert response.status_code == 200

    def test_delete_workflow(self, client):
        """Test deleting a workflow."""
        # Create a workflow first
        response = client.get("/api/v1/templates")
        templates = response.json()
        template_id = templates[0]["id"]

        response = client.post(
            "/api/v1/workflows",
            json={
                "description": "Test goal for deletion",
                "use_template": template_id,
            }
        )
        workflow_id = response.json()["id"]

        # Delete the workflow
        response = client.delete(f"/api/v1/workflows/{workflow_id}")
        assert response.status_code == 200

        # Verify it's gone
        response = client.get(f"/api/v1/workflows/{workflow_id}")
        assert response.status_code == 404


class TestMemoryAPI:
    """Tests for the memory API."""

    def test_list_memory_entries(self, client):
        """Test listing memory entries."""
        response = client.get("/api/v1/memory")
        assert response.status_code == 200
        entries = response.json()
        assert isinstance(entries, list)

    def test_search_memory(self, client):
        """Test searching memory."""
        response = client.get("/api/v1/memory/search?keywords=test,error")
        assert response.status_code == 200
        results = response.json()
        assert isinstance(results, list)

    def test_search_memory_requires_keywords(self, client):
        """Test that search requires keywords."""
        response = client.get("/api/v1/memory/search?keywords=")
        assert response.status_code == 400

    def test_get_memory_stats(self, client):
        """Test getting memory statistics."""
        response = client.get("/api/v1/memory/stats")
        assert response.status_code == 200
        stats = response.json()
        assert "total_entries" in stats
        assert "services" in stats

    def test_get_nonexistent_memory_entry(self, client):
        """Test getting a non-existent memory entry."""
        response = client.get("/api/v1/memory/nonexistent-entry")
        assert response.status_code == 404

    def test_delete_nonexistent_memory_entry(self, client):
        """Test deleting a non-existent memory entry."""
        response = client.delete("/api/v1/memory/nonexistent-entry")
        assert response.status_code == 404


class TestWorkflowExecution:
    """Tests for workflow execution."""

    def test_execute_workflow(self, client):
        """Test executing a workflow."""
        # Create a workflow first
        response = client.get("/api/v1/templates")
        templates = response.json()
        template_id = templates[0]["id"]

        response = client.post(
            "/api/v1/workflows",
            json={
                "description": "Test goal for execution",
                "use_template": template_id,
            }
        )
        workflow_id = response.json()["id"]

        # Execute the workflow (dry run)
        response = client.post(
            f"/api/v1/workflows/{workflow_id}/execute?dry_run=true"
        )
        assert response.status_code == 200
        execution = response.json()
        assert "execution_id" in execution
        assert execution["workflow_id"] == workflow_id

    def test_get_execution_status(self, client):
        """Test getting execution status."""
        # Create and execute a workflow first
        response = client.get("/api/v1/templates")
        templates = response.json()
        template_id = templates[0]["id"]

        response = client.post(
            "/api/v1/workflows",
            json={
                "description": "Test goal for status check",
                "use_template": template_id,
            }
        )
        workflow_id = response.json()["id"]

        response = client.post(
            f"/api/v1/workflows/{workflow_id}/execute?dry_run=true"
        )
        execution_id = response.json()["execution_id"]

        # Get execution status
        response = client.get(
            f"/api/v1/workflows/{workflow_id}/execute/{execution_id}"
        )
        assert response.status_code == 200
        status = response.json()
        assert status["execution_id"] == execution_id

    def test_get_nonexistent_execution(self, client):
        """Test getting a non-existent execution."""
        response = client.get(
            "/api/v1/workflows/some-workflow/execute/nonexistent-execution"
        )
        assert response.status_code == 404
