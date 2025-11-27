"""Tests for memory backends."""

import os
import tempfile

import pytest

from autoops_architect.memory.backend import (
    JSONMemoryBackend,
    SQLiteMemoryBackend,
    get_memory_backend,
)
from autoops_architect.models.execution import ExecutionStatus, WorkflowRunResult
from autoops_architect.models.goal import Environment, Goal
from autoops_architect.models.workflow import Node, NodeType, WorkflowGraph


@pytest.fixture
def temp_json_path():
    """Create a temporary JSON file path."""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def temp_db_path():
    """Create a temporary SQLite database path."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def sample_run_data():
    """Create sample data for testing."""
    goal = Goal(
        description="Investigate 5xx errors in checkout service",
        services=["checkout-api"],
        environment=Environment.PRODUCTION,
    )

    workflow = WorkflowGraph(
        id="wf-test-001",
        name="Test Workflow",
        goal_description=goal.description,
        nodes=[
            Node(id="n1", name="Node 1", type=NodeType.LOG_COLLECTION, tool="log_collector"),
        ],
        edges=[],
    )

    result = WorkflowRunResult(
        workflow_id=workflow.id,
        goal_description=goal.description,
        overall_status=ExecutionStatus.SUCCESS,
    )

    return goal, workflow, result


class TestJSONMemoryBackend:
    """Tests for JSONMemoryBackend."""

    def test_create_backend(self, temp_json_path):
        """Test creating a JSON backend."""
        backend = JSONMemoryBackend(temp_json_path)
        assert backend.file_path.exists() is False  # Created on first save

    def test_save_and_retrieve(self, temp_json_path, sample_run_data):
        """Test saving and retrieving a workflow run."""
        goal, workflow, result = sample_run_data
        backend = JSONMemoryBackend(temp_json_path)

        entry_id = backend.save_workflow_run(goal, workflow, result)
        assert entry_id is not None
        assert entry_id.startswith("mem-")

        # Retrieve the entry
        entry = backend.get_entry(entry_id)
        assert entry is not None
        assert entry.goal_description == goal.description
        assert entry.workflow_id == workflow.id

    def test_search(self, temp_json_path, sample_run_data):
        """Test searching memory."""
        goal, workflow, result = sample_run_data
        backend = JSONMemoryBackend(temp_json_path)

        backend.save_workflow_run(goal, workflow, result)

        # Search for matching keywords
        results = backend.search(keywords=["checkout", "5xx"])
        assert len(results) >= 1
        assert results[0].goal_description == goal.description

    def test_search_no_results(self, temp_json_path, sample_run_data):
        """Test search with no matching results."""
        goal, workflow, result = sample_run_data
        backend = JSONMemoryBackend(temp_json_path)

        backend.save_workflow_run(goal, workflow, result)

        results = backend.search(keywords=["nonexistent", "terms"])
        assert len(results) == 0

    def test_list_entries(self, temp_json_path, sample_run_data):
        """Test listing all entries."""
        goal, workflow, result = sample_run_data
        backend = JSONMemoryBackend(temp_json_path)

        backend.save_workflow_run(goal, workflow, result)

        entries = backend.list_entries()
        assert len(entries) == 1

    def test_delete_entry(self, temp_json_path, sample_run_data):
        """Test deleting an entry."""
        goal, workflow, result = sample_run_data
        backend = JSONMemoryBackend(temp_json_path)

        entry_id = backend.save_workflow_run(goal, workflow, result)

        # Delete it
        deleted = backend.delete_entry(entry_id)
        assert deleted is True

        # Verify it's gone
        entry = backend.get_entry(entry_id)
        assert entry is None

    def test_delete_nonexistent(self, temp_json_path):
        """Test deleting a non-existent entry."""
        backend = JSONMemoryBackend(temp_json_path)
        deleted = backend.delete_entry("nonexistent")
        assert deleted is False

    def test_preferences(self, temp_json_path):
        """Test preference storage."""
        backend = JSONMemoryBackend(temp_json_path)

        backend.set_preference("test.key", "value", "A test preference")
        assert backend.get_preference("test.key") == "value"

        # Update
        backend.set_preference("test.key", "new_value")
        assert backend.get_preference("test.key") == "new_value"

    def test_preference_default(self, temp_json_path):
        """Test getting preference with default."""
        backend = JSONMemoryBackend(temp_json_path)
        value = backend.get_preference("nonexistent", default="default")
        assert value == "default"

    def test_list_preferences(self, temp_json_path):
        """Test listing preferences."""
        backend = JSONMemoryBackend(temp_json_path)

        backend.set_preference("app.setting1", "value1")
        backend.set_preference("app.setting2", "value2")
        backend.set_preference("other.setting", "value3")

        all_keys = backend.list_preferences()
        assert len(all_keys) == 3

        app_keys = backend.list_preferences(prefix="app.")
        assert len(app_keys) == 2

    def test_persistence(self, temp_json_path, sample_run_data):
        """Test that data persists between instances."""
        goal, workflow, result = sample_run_data

        # Save with first instance
        backend1 = JSONMemoryBackend(temp_json_path)
        entry_id = backend1.save_workflow_run(goal, workflow, result)
        backend1.set_preference("test", "value")

        # Load with new instance
        backend2 = JSONMemoryBackend(temp_json_path)
        entry = backend2.get_entry(entry_id)
        assert entry is not None

        pref = backend2.get_preference("test")
        assert pref == "value"


class TestSQLiteMemoryBackend:
    """Tests for SQLiteMemoryBackend."""

    def test_create_backend(self, temp_db_path):
        """Test creating a SQLite backend."""
        backend = SQLiteMemoryBackend(temp_db_path)
        assert os.path.exists(temp_db_path)

    def test_save_and_retrieve(self, temp_db_path, sample_run_data):
        """Test saving and retrieving a workflow run."""
        goal, workflow, result = sample_run_data
        backend = SQLiteMemoryBackend(temp_db_path)

        entry_id = backend.save_workflow_run(goal, workflow, result)
        assert entry_id is not None

        entry = backend.get_entry(entry_id)
        assert entry is not None
        assert entry.goal_description == goal.description

    def test_search(self, temp_db_path, sample_run_data):
        """Test searching memory."""
        goal, workflow, result = sample_run_data
        backend = SQLiteMemoryBackend(temp_db_path)

        backend.save_workflow_run(goal, workflow, result)

        results = backend.search(keywords=["checkout", "5xx"])
        assert len(results) >= 1

    def test_list_entries_with_pagination(self, temp_db_path, sample_run_data):
        """Test listing entries with pagination."""
        goal, workflow, result = sample_run_data
        backend = SQLiteMemoryBackend(temp_db_path)

        # Save multiple entries
        for i in range(5):
            goal_copy = Goal(
                description=f"Test goal {i}",
                services=[f"service-{i}"],
            )
            backend.save_workflow_run(goal_copy, workflow, result)

        # Get all
        all_entries = backend.list_entries(limit=10)
        assert len(all_entries) == 5

        # Get with pagination
        page1 = backend.list_entries(limit=2, offset=0)
        page2 = backend.list_entries(limit=2, offset=2)

        assert len(page1) == 2
        assert len(page2) == 2

    def test_delete_entry(self, temp_db_path, sample_run_data):
        """Test deleting an entry."""
        goal, workflow, result = sample_run_data
        backend = SQLiteMemoryBackend(temp_db_path)

        entry_id = backend.save_workflow_run(goal, workflow, result)
        deleted = backend.delete_entry(entry_id)

        assert deleted is True
        assert backend.get_entry(entry_id) is None

    def test_preferences(self, temp_db_path):
        """Test preference storage."""
        backend = SQLiteMemoryBackend(temp_db_path)

        backend.set_preference("key", {"nested": "value"})
        value = backend.get_preference("key")

        assert value == {"nested": "value"}

    def test_persistence(self, temp_db_path, sample_run_data):
        """Test data persistence."""
        goal, workflow, result = sample_run_data

        backend1 = SQLiteMemoryBackend(temp_db_path)
        entry_id = backend1.save_workflow_run(goal, workflow, result)

        backend2 = SQLiteMemoryBackend(temp_db_path)
        entry = backend2.get_entry(entry_id)

        assert entry is not None


class TestGetMemoryBackend:
    """Tests for get_memory_backend factory."""

    def test_get_json_backend(self, temp_json_path):
        """Test getting a JSON backend."""
        backend = get_memory_backend("json", temp_json_path)
        assert isinstance(backend, JSONMemoryBackend)

    def test_get_sqlite_backend(self, temp_db_path):
        """Test getting a SQLite backend."""
        backend = get_memory_backend("sqlite", temp_db_path)
        assert isinstance(backend, SQLiteMemoryBackend)

    def test_unknown_backend(self):
        """Test getting an unknown backend type."""
        with pytest.raises(ValueError):
            get_memory_backend("unknown")
