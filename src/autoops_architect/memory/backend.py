"""Memory backend implementations for storing workflow history."""

import json
import logging
import os
import sqlite3
import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from autoops_architect.models.execution import WorkflowRunResult
from autoops_architect.models.goal import Goal
from autoops_architect.models.memory import MemoryEntry, PreferenceStore, UserPreference
from autoops_architect.models.workflow import WorkflowGraph

logger = logging.getLogger(__name__)


class MemoryBackend(ABC):
    """
    Abstract base class for memory backends.

    Memory backends store:
    - Workflow execution history (for learning from past runs)
    - User preferences and overrides
    - Successful playbooks for reuse
    """

    @abstractmethod
    def save_workflow_run(
        self,
        goal: Goal,
        workflow: WorkflowGraph,
        result: WorkflowRunResult,
    ) -> str:
        """
        Save a completed workflow run to memory.

        Args:
            goal: The original goal.
            workflow: The workflow that was executed.
            result: The execution result.

        Returns:
            ID of the saved memory entry.
        """
        pass

    @abstractmethod
    def search(
        self,
        keywords: list[str],
        limit: int = 5,
        min_score: float = 0.1,
    ) -> list[MemoryEntry]:
        """
        Search for relevant past workflows.

        Args:
            keywords: Keywords to search for.
            limit: Maximum number of results.
            min_score: Minimum relevance score.

        Returns:
            List of matching memory entries.
        """
        pass

    def semantic_search(
        self,
        query: str,
        limit: int = 5,
        min_score: float = 0.3,
        use_hybrid: bool = True,
    ) -> list[MemoryEntry]:
        """
        Search using semantic similarity.

        This is an optional enhanced search that uses embeddings.
        Default implementation falls back to keyword search.

        Args:
            query: Natural language search query.
            limit: Maximum number of results.
            min_score: Minimum similarity score.
            use_hybrid: Combine with keyword search.

        Returns:
            List of matching memory entries.
        """
        # Default implementation: extract keywords and use regular search
        keywords = [w for w in query.lower().split() if len(w) > 2]
        return self.search(keywords, limit=limit, min_score=min_score)

    @abstractmethod
    def get_entry(self, entry_id: str) -> Optional[MemoryEntry]:
        """Get a specific memory entry by ID."""
        pass

    @abstractmethod
    def list_entries(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryEntry]:
        """List all memory entries."""
        pass

    @abstractmethod
    def delete_entry(self, entry_id: str) -> bool:
        """Delete a memory entry. Returns True if deleted."""
        pass

    # Preference methods

    @abstractmethod
    def set_preference(
        self,
        key: str,
        value: Any,
        description: Optional[str] = None,
    ) -> None:
        """Set a user preference."""
        pass

    @abstractmethod
    def get_preference(self, key: str, default: Any = None) -> Any:
        """Get a user preference."""
        pass

    @abstractmethod
    def list_preferences(self, prefix: Optional[str] = None) -> list[str]:
        """List all preference keys."""
        pass


class JSONMemoryBackend(MemoryBackend):
    """
    JSON file-based memory backend.

    Stores all data in a single JSON file. Simple and portable,
    suitable for development and small-scale usage.

    Data is loaded into memory on initialization and saved after
    each modification.

    Example:
        >>> backend = JSONMemoryBackend("~/.autoops/memory.json")
        >>> backend.save_workflow_run(goal, workflow, result)
    """

    def __init__(self, file_path: str = "~/.autoops/memory.json") -> None:
        """
        Initialize the JSON memory backend.

        Args:
            file_path: Path to the JSON file. Supports ~ for home directory.
        """
        self.file_path = Path(file_path).expanduser()
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

        self._entries: dict[str, MemoryEntry] = {}
        self._preferences: PreferenceStore = PreferenceStore()

        self._load()

    def _load(self) -> None:
        """Load data from the JSON file."""
        if self.file_path.exists():
            try:
                with open(self.file_path, "r") as f:
                    data = json.load(f)

                # Load entries
                for entry_data in data.get("entries", []):
                    entry = MemoryEntry.model_validate(entry_data)
                    self._entries[entry.id] = entry

                # Load preferences
                for pref_data in data.get("preferences", []):
                    pref = UserPreference.model_validate(pref_data)
                    self._preferences.preferences[pref.key] = pref

            except (json.JSONDecodeError, Exception):
                # Start fresh if file is corrupted
                self._entries = {}
                self._preferences = PreferenceStore()

    def _save(self) -> None:
        """Save data to the JSON file."""
        data = {
            "version": "1.0",
            "last_updated": datetime.utcnow().isoformat(),
            "entries": [
                entry.model_dump(mode="json")
                for entry in self._entries.values()
            ],
            "preferences": [
                pref.model_dump(mode="json")
                for pref in self._preferences.preferences.values()
            ],
        }

        with open(self.file_path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def save_workflow_run(
        self,
        goal: Goal,
        workflow: WorkflowGraph,
        result: WorkflowRunResult,
    ) -> str:
        """Save a completed workflow run."""
        entry_id = f"mem-{uuid.uuid4().hex[:12]}"

        entry = MemoryEntry(
            id=entry_id,
            goal_description=goal.description,
            workflow_id=workflow.id,
            workflow_summary=workflow.name,
            outcome_status=result.overall_status.value,
            outcome_summary=result.summary,
            keywords=goal.get_keywords(),
            services=list(goal.services),
            environment=goal.environment.value if goal.environment else None,
            node_count=len(workflow.nodes),
            success_count=result.success_count,
            failed_count=result.failed_count,
            duration_seconds=result.duration_seconds,
            workflow_json=workflow.model_dump_json(),
        )

        self._entries[entry_id] = entry
        self._save()

        return entry_id

    def search(
        self,
        keywords: list[str],
        limit: int = 5,
        min_score: float = 0.1,
    ) -> list[MemoryEntry]:
        """Search for relevant past workflows."""
        results: list[tuple[float, MemoryEntry]] = []
        keyword_set = set(k.lower() for k in keywords)

        for entry in self._entries.values():
            entry_keywords = set(k.lower() for k in entry.keywords)
            entry_keywords.update(s.lower() for s in entry.services)

            # Add words from goal description
            for word in entry.goal_description.lower().split():
                if len(word) > 3:
                    entry_keywords.add(word)

            # Calculate overlap score
            if not keyword_set:
                score = 0.0
            else:
                overlap = len(keyword_set & entry_keywords)
                score = overlap / len(keyword_set)

            # Boost successful outcomes
            if entry.outcome_status == "success":
                score *= 1.2

            # Slight recency boost
            days_old = (datetime.utcnow() - entry.created_at).days
            if days_old < 7:
                score *= 1.1
            elif days_old > 30:
                score *= 0.9

            if score >= min_score:
                entry_copy = entry.model_copy()
                entry_copy.relevance_score = min(score, 1.0)
                results.append((score, entry_copy))

        # Sort by score descending
        results.sort(key=lambda x: x[0], reverse=True)

        return [entry for _, entry in results[:limit]]

    def semantic_search(
        self,
        query: str,
        limit: int = 5,
        min_score: float = 0.3,
        use_hybrid: bool = True,
    ) -> list[MemoryEntry]:
        """
        Search using semantic similarity with embeddings.

        Args:
            query: Natural language search query.
            limit: Maximum number of results.
            min_score: Minimum similarity score.
            use_hybrid: Combine semantic with keyword search.

        Returns:
            List of matching memory entries.
        """
        try:
            from autoops_architect.memory.semantic import SemanticSearcher
        except ImportError:
            logger.debug("Semantic search not available, using keyword search")
            keywords = [w for w in query.lower().split() if len(w) > 2]
            return self.search(keywords, limit=limit, min_score=min_score)

        searcher = SemanticSearcher()
        results: list[tuple[float, MemoryEntry]] = []

        for entry in self._entries.values():
            if use_hybrid:
                # Combine semantic and keyword similarity
                query_keywords = [w for w in query.lower().split() if len(w) > 2]
                score = searcher.hybrid_score(
                    query=query,
                    text=entry.goal_description,
                    keywords=query_keywords,
                    text_keywords=entry.keywords + entry.services,
                    semantic_weight=0.6,
                )
            else:
                # Pure semantic similarity
                score = searcher.semantic_similarity(query, entry.goal_description)

            # Boost successful outcomes
            if entry.outcome_status == "success":
                score *= 1.2

            # Recency boost
            days_old = (datetime.utcnow() - entry.created_at).days
            if days_old < 7:
                score *= 1.1
            elif days_old > 30:
                score *= 0.9

            if score >= min_score:
                entry_copy = entry.model_copy()
                entry_copy.relevance_score = min(score, 1.0)
                results.append((score, entry_copy))

        results.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in results[:limit]]

    def get_entry(self, entry_id: str) -> Optional[MemoryEntry]:
        """Get a specific memory entry by ID."""
        return self._entries.get(entry_id)

    def list_entries(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryEntry]:
        """List all memory entries."""
        entries = sorted(
            self._entries.values(),
            key=lambda e: e.created_at,
            reverse=True,
        )
        return entries[offset:offset + limit]

    def delete_entry(self, entry_id: str) -> bool:
        """Delete a memory entry."""
        if entry_id in self._entries:
            del self._entries[entry_id]
            self._save()
            return True
        return False

    def set_preference(
        self,
        key: str,
        value: Any,
        description: Optional[str] = None,
    ) -> None:
        """Set a user preference."""
        self._preferences.set(key, value, description)
        self._save()

    def get_preference(self, key: str, default: Any = None) -> Any:
        """Get a user preference."""
        return self._preferences.get(key, default)

    def list_preferences(self, prefix: Optional[str] = None) -> list[str]:
        """List all preference keys."""
        return self._preferences.list_keys(prefix)


class SQLiteMemoryBackend(MemoryBackend):
    """
    SQLite-based memory backend.

    More robust than JSON for larger datasets and concurrent access.
    Creates a SQLite database file with proper indexing.

    Example:
        >>> backend = SQLiteMemoryBackend("~/.autoops/memory.db")
        >>> backend.save_workflow_run(goal, workflow, result)
    """

    def __init__(self, db_path: str = "~/.autoops/memory.db") -> None:
        """
        Initialize the SQLite memory backend.

        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._init_db()

    def _init_db(self) -> None:
        """Initialize the database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_entries (
                    id TEXT PRIMARY KEY,
                    goal_description TEXT NOT NULL,
                    workflow_id TEXT NOT NULL,
                    workflow_summary TEXT,
                    outcome_status TEXT NOT NULL,
                    outcome_summary TEXT,
                    keywords TEXT,
                    services TEXT,
                    environment TEXT,
                    node_count INTEGER,
                    success_count INTEGER,
                    failed_count INTEGER,
                    duration_seconds REAL,
                    workflow_json TEXT,
                    user_feedback TEXT,
                    created_at TEXT NOT NULL
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS preferences (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    description TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # Create index for faster searching
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_keywords ON memory_entries(keywords)
            """)

            conn.commit()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def save_workflow_run(
        self,
        goal: Goal,
        workflow: WorkflowGraph,
        result: WorkflowRunResult,
    ) -> str:
        """Save a completed workflow run."""
        entry_id = f"mem-{uuid.uuid4().hex[:12]}"

        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO memory_entries (
                    id, goal_description, workflow_id, workflow_summary,
                    outcome_status, outcome_summary, keywords, services,
                    environment, node_count, success_count, failed_count,
                    duration_seconds, workflow_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entry_id,
                goal.description,
                workflow.id,
                workflow.name,
                result.overall_status.value,
                result.summary,
                json.dumps(goal.get_keywords()),
                json.dumps(list(goal.services)),
                goal.environment.value if goal.environment else None,
                len(workflow.nodes),
                result.success_count,
                result.failed_count,
                result.duration_seconds,
                workflow.model_dump_json(),
                datetime.utcnow().isoformat(),
            ))
            conn.commit()

        return entry_id

    def _row_to_entry(self, row: sqlite3.Row) -> MemoryEntry:
        """Convert a database row to a MemoryEntry."""
        return MemoryEntry(
            id=row["id"],
            goal_description=row["goal_description"],
            workflow_id=row["workflow_id"],
            workflow_summary=row["workflow_summary"],
            outcome_status=row["outcome_status"],
            outcome_summary=row["outcome_summary"],
            keywords=json.loads(row["keywords"]) if row["keywords"] else [],
            services=json.loads(row["services"]) if row["services"] else [],
            environment=row["environment"],
            node_count=row["node_count"] or 0,
            success_count=row["success_count"] or 0,
            failed_count=row["failed_count"] or 0,
            duration_seconds=row["duration_seconds"],
            workflow_json=row["workflow_json"],
            user_feedback=row["user_feedback"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def search(
        self,
        keywords: list[str],
        limit: int = 5,
        min_score: float = 0.1,
    ) -> list[MemoryEntry]:
        """Search for relevant past workflows."""
        # For SQLite, we do a simple keyword search
        # A more sophisticated implementation would use FTS5
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT * FROM memory_entries
                ORDER BY created_at DESC
                LIMIT 100
            """).fetchall()

        # Score entries in Python
        keyword_set = set(k.lower() for k in keywords)
        results: list[tuple[float, MemoryEntry]] = []

        for row in rows:
            entry = self._row_to_entry(row)
            entry_keywords = set(k.lower() for k in entry.keywords)
            entry_keywords.update(s.lower() for s in entry.services)

            if not keyword_set:
                score = 0.0
            else:
                overlap = len(keyword_set & entry_keywords)
                score = overlap / len(keyword_set)

            if entry.outcome_status == "success":
                score *= 1.2

            if score >= min_score:
                entry.relevance_score = min(score, 1.0)
                results.append((score, entry))

        results.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in results[:limit]]

    def get_entry(self, entry_id: str) -> Optional[MemoryEntry]:
        """Get a specific memory entry by ID."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM memory_entries WHERE id = ?",
                (entry_id,)
            ).fetchone()

        if row:
            return self._row_to_entry(row)
        return None

    def list_entries(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryEntry]:
        """List all memory entries."""
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT * FROM memory_entries
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """, (limit, offset)).fetchall()

        return [self._row_to_entry(row) for row in rows]

    def delete_entry(self, entry_id: str) -> bool:
        """Delete a memory entry."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM memory_entries WHERE id = ?",
                (entry_id,)
            )
            conn.commit()
            return cursor.rowcount > 0

    def set_preference(
        self,
        key: str,
        value: Any,
        description: Optional[str] = None,
    ) -> None:
        """Set a user preference."""
        now = datetime.utcnow().isoformat()
        value_json = json.dumps(value)

        with self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO preferences (key, value, description, created_at, updated_at)
                VALUES (?, ?, ?, COALESCE(
                    (SELECT created_at FROM preferences WHERE key = ?), ?
                ), ?)
            """, (key, value_json, description, key, now, now))
            conn.commit()

    def get_preference(self, key: str, default: Any = None) -> Any:
        """Get a user preference."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT value FROM preferences WHERE key = ?",
                (key,)
            ).fetchone()

        if row:
            return json.loads(row["value"])
        return default

    def list_preferences(self, prefix: Optional[str] = None) -> list[str]:
        """List all preference keys."""
        with self._get_connection() as conn:
            if prefix:
                rows = conn.execute(
                    "SELECT key FROM preferences WHERE key LIKE ? ORDER BY key",
                    (f"{prefix}%",)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT key FROM preferences ORDER BY key"
                ).fetchall()

        return [row["key"] for row in rows]


def get_memory_backend(
    backend_type: str = "json",
    path: Optional[str] = None,
) -> MemoryBackend:
    """
    Factory function to get a memory backend.

    Args:
        backend_type: Type of backend ("json" or "sqlite").
        path: Optional custom path for the data file.

    Returns:
        A MemoryBackend instance.
    """
    default_dir = os.path.expanduser("~/.autoops")

    if backend_type == "json":
        file_path = path or os.path.join(default_dir, "memory.json")
        return JSONMemoryBackend(file_path)

    elif backend_type == "sqlite":
        db_path = path or os.path.join(default_dir, "memory.db")
        return SQLiteMemoryBackend(db_path)

    else:
        raise ValueError(f"Unknown backend type: {backend_type}")
