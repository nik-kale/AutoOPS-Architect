"""Tests that stored history survives bad files and is kept private."""

import json
import os
import sqlite3
import stat
from pathlib import Path
from typing import Any

import pytest

from autoops_architect.llm.cache import CacheConfig, FilesystemCacheBackend
from autoops_architect.memory.backend import JSONMemoryBackend, SQLiteMemoryBackend
from autoops_architect.models.execution import ExecutionStatus, WorkflowRunResult
from autoops_architect.models.goal import Goal
from autoops_architect.models.workflow import Node, NodeType, WorkflowGraph


def run_data() -> tuple[Goal, WorkflowGraph, WorkflowRunResult]:
    goal = Goal(description="Investigate errors in the checkout service")
    workflow = WorkflowGraph(
        id="wf-1",
        name="Workflow",
        goal_description=goal.description,
        nodes=[Node(id="n", name="N", type=NodeType.ANALYSIS, tool="echo")],
    )
    result = WorkflowRunResult(
        workflow_id=workflow.id,
        goal_description=goal.description,
        overall_status=ExecutionStatus.SUCCESS,
    )
    return goal, workflow, result


class TestJsonBackend:
    @pytest.mark.parametrize(
        "content",
        ["{not json", '["a", "list"]', '{"entries": [{"id": "missing-fields"}]}'],
    )
    def test_unreadable_file_is_kept_not_overwritten(self, tmp_path: Path, content: str) -> None:
        path = tmp_path / "memory.json"
        path.write_text(content)

        backend = JSONMemoryBackend(str(path))
        backend.save_workflow_run(*run_data())

        assert (tmp_path / "memory.json.corrupt").read_text() == content
        assert len(JSONMemoryBackend(str(path)).list_entries()) == 1

    def test_failed_save_leaves_previous_data_intact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "memory.json"
        backend = JSONMemoryBackend(str(path))
        backend.save_workflow_run(*run_data())
        before = path.read_text()

        def fail(*_args: Any, **_kwargs: Any) -> None:
            raise OSError("disk full")

        monkeypatch.setattr("autoops_architect.memory.backend.json.dump", fail)

        with pytest.raises(OSError, match="disk full"):
            backend.save_workflow_run(*run_data())

        assert path.read_text() == before
        assert [p.name for p in tmp_path.iterdir()] == ["memory.json"]

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
    def test_save_replaces_the_mode_of_an_existing_file(self, tmp_path: Path) -> None:
        path = tmp_path / "memory.json"
        path.write_text('{"entries": [], "preferences": []}')
        path.chmod(stat.S_IRWXU)

        JSONMemoryBackend(str(path)).save_workflow_run(*run_data())

        assert stat.S_IMODE(path.stat().st_mode) == stat.S_IRUSR | stat.S_IWUSR


class TestSqliteBackend:
    @pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
    def test_database_file_is_private(self, tmp_path: Path) -> None:
        path = tmp_path / "memory.db"

        SQLiteMemoryBackend(str(path))

        assert stat.S_IMODE(path.stat().st_mode) == stat.S_IRUSR | stat.S_IWUSR

    def test_connections_are_closed_after_use(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        opened: list[sqlite3.Connection] = []
        real_connect = sqlite3.connect

        def tracking_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
            conn = real_connect(*args, **kwargs)
            opened.append(conn)
            return conn

        monkeypatch.setattr("autoops_architect.memory.backend.sqlite3.connect", tracking_connect)

        backend = SQLiteMemoryBackend(str(tmp_path / "memory.db"))
        entry_id = backend.save_workflow_run(*run_data())

        assert backend.get_entry(entry_id) is not None
        assert opened
        for conn in opened:
            with pytest.raises(sqlite3.ProgrammingError):
                conn.execute("SELECT 1")


class TestFilesystemCache:
    @pytest.mark.parametrize("content", ["{not json", json.dumps({"key": "only"}), "[1]"])
    async def test_malformed_entry_is_a_cache_miss(self, tmp_path: Path, content: str) -> None:
        cache = FilesystemCacheBackend(
            CacheConfig(enabled=True, backend="filesystem", cache_dir=str(tmp_path))
        )
        cache._get_file_path("bad").write_text(content)

        assert await cache.get("bad") is None
        assert not cache._get_file_path("bad").exists()
