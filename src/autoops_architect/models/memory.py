"""Memory models for storing institutional knowledge and preferences."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class MemoryEntry(BaseModel):
    """
    A single memory entry storing workflow history and outcomes.

    Memory entries allow AutoOps Architect to learn from past executions
    and provide better plans for similar future goals.

    Example:
        >>> entry = MemoryEntry(
        ...     goal_description="Investigate 5xx errors for checkout",
        ...     workflow_id="wf-20241127-001",
        ...     outcome_status="success",
        ...     keywords=["5xx", "checkout", "error-rate"]
        ... )
    """

    id: str = Field(
        ...,
        description="Unique identifier for this memory entry"
    )

    goal_description: str = Field(
        ...,
        description="The original goal that was addressed"
    )

    workflow_id: str = Field(
        ...,
        description="ID of the workflow that was executed"
    )

    workflow_summary: Optional[str] = Field(
        default=None,
        description="Brief summary of what the workflow did"
    )

    outcome_status: str = Field(
        ...,
        description="Final status: success, failed, partial"
    )

    outcome_summary: Optional[str] = Field(
        default=None,
        description="Summary of the outcome and lessons learned"
    )

    keywords: list[str] = Field(
        default_factory=list,
        description="Keywords for retrieval and matching"
    )

    services: list[str] = Field(
        default_factory=list,
        description="Services that were involved"
    )

    environment: Optional[str] = Field(
        default=None,
        description="Environment where this was executed"
    )

    node_count: int = Field(
        default=0,
        ge=0,
        description="Number of nodes in the workflow"
    )

    success_count: int = Field(
        default=0,
        ge=0,
        description="Number of nodes that succeeded"
    )

    failed_count: int = Field(
        default=0,
        ge=0,
        description="Number of nodes that failed"
    )

    duration_seconds: Optional[float] = Field(
        default=None,
        description="Total execution duration in seconds"
    )

    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When this memory was created"
    )

    workflow_json: Optional[str] = Field(
        default=None,
        description="Full workflow JSON for reference"
    )

    user_feedback: Optional[str] = Field(
        default=None,
        description="Optional user feedback about this execution"
    )

    relevance_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Computed relevance score when retrieved"
    )

    def to_prompt_context(self) -> str:
        """
        Generate a context string for including in LLM prompts.

        Returns:
            Formatted string for LLM context.
        """
        lines = [
            f"Previous similar goal: {self.goal_description}",
            f"Outcome: {self.outcome_status}",
        ]

        if self.outcome_summary:
            lines.append(f"Lesson learned: {self.outcome_summary}")

        if self.workflow_summary:
            lines.append(f"Workflow approach: {self.workflow_summary}")

        if self.services:
            lines.append(f"Services involved: {', '.join(self.services)}")

        return "\n".join(lines)


class WorkflowMemory(BaseModel):
    """
    Collection of memory entries with metadata.

    This is the top-level structure for memory storage and retrieval.
    """

    entries: list[MemoryEntry] = Field(
        default_factory=list,
        description="List of memory entries"
    )

    last_updated: datetime = Field(
        default_factory=datetime.utcnow,
        description="When this memory was last updated"
    )

    version: str = Field(
        default="1.0",
        description="Schema version"
    )

    def add_entry(self, entry: MemoryEntry) -> None:
        """Add a new memory entry."""
        self.entries.append(entry)
        self.last_updated = datetime.utcnow()

    def search(
        self,
        keywords: list[str],
        limit: int = 5,
        min_score: float = 0.1
    ) -> list[MemoryEntry]:
        """
        Search for relevant memory entries by keywords.

        Args:
            keywords: Keywords to search for.
            limit: Maximum number of results.
            min_score: Minimum relevance score.

        Returns:
            List of matching entries sorted by relevance.
        """
        results: list[tuple[float, MemoryEntry]] = []
        keyword_set = set(k.lower() for k in keywords)

        for entry in self.entries:
            entry_keywords = set(k.lower() for k in entry.keywords)
            entry_keywords.update(s.lower() for s in entry.services)

            # Simple keyword overlap scoring
            if not keyword_set:
                score = 0.0
            else:
                overlap = len(keyword_set & entry_keywords)
                score = overlap / len(keyword_set)

            # Boost successful outcomes
            if entry.outcome_status == "success":
                score *= 1.2

            if score >= min_score:
                # Create a copy with the score
                entry_copy = entry.model_copy()
                entry_copy.relevance_score = min(score, 1.0)
                results.append((score, entry_copy))

        # Sort by score descending
        results.sort(key=lambda x: x[0], reverse=True)

        return [entry for _, entry in results[:limit]]


class UserPreference(BaseModel):
    """
    User preference or override for workflow planning and execution.

    Preferences allow users to customize how AutoOps Architect behaves
    for their specific environment and needs.

    Example:
        >>> pref = UserPreference(
        ...     key="remediation.allowed",
        ...     value=False,
        ...     description="Disable all remediation actions"
        ... )
    """

    key: str = Field(
        ...,
        description="Preference key (dot-notation for namespacing)"
    )

    value: Any = Field(
        ...,
        description="Preference value"
    )

    description: Optional[str] = Field(
        default=None,
        description="Human-readable description"
    )

    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When this preference was set"
    )

    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When this preference was last updated"
    )


class PreferenceStore(BaseModel):
    """Collection of user preferences."""

    preferences: dict[str, UserPreference] = Field(
        default_factory=dict,
        description="Preferences keyed by their key field"
    )

    def set(self, key: str, value: Any, description: Optional[str] = None) -> None:
        """Set a preference value."""
        if key in self.preferences:
            pref = self.preferences[key]
            pref.value = value
            pref.updated_at = datetime.utcnow()
            if description:
                pref.description = description
        else:
            self.preferences[key] = UserPreference(
                key=key,
                value=value,
                description=description,
            )

    def get(self, key: str, default: Any = None) -> Any:
        """Get a preference value."""
        if key in self.preferences:
            return self.preferences[key].value
        return default

    def delete(self, key: str) -> bool:
        """Delete a preference. Returns True if it existed."""
        if key in self.preferences:
            del self.preferences[key]
            return True
        return False

    def list_keys(self, prefix: Optional[str] = None) -> list[str]:
        """List all preference keys, optionally filtered by prefix."""
        keys = list(self.preferences.keys())
        if prefix:
            keys = [k for k in keys if k.startswith(prefix)]
        return sorted(keys)
