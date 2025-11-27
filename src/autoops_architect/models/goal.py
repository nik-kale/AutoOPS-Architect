"""Goal model representing a user's natural language operations request."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Environment(str, Enum):
    """Target environment for the operations goal."""

    PRODUCTION = "production"
    STAGING = "staging"
    DEVELOPMENT = "development"
    UNKNOWN = "unknown"


class Priority(str, Enum):
    """Priority/severity level of the goal."""

    CRITICAL = "critical"  # P0 - Immediate attention required
    HIGH = "high"          # P1 - Urgent, needs resolution soon
    MEDIUM = "medium"      # P2 - Important but not urgent
    LOW = "low"            # P3 - Can be addressed when convenient
    UNKNOWN = "unknown"


class Goal(BaseModel):
    """
    Represents a user's natural language operations/SRE goal.

    This is the primary input to AutoOps Architect. Users describe what they
    want to investigate or accomplish, and the system generates a workflow
    to achieve it.

    Example:
        >>> goal = Goal(
        ...     description="Investigate elevated 5xx errors for the checkout service in prod",
        ...     services=["checkout-api", "payments"],
        ...     environment=Environment.PRODUCTION,
        ...     priority=Priority.HIGH
        ... )
    """

    description: str = Field(
        ...,
        min_length=10,
        max_length=2000,
        description="Natural language description of the operations goal"
    )

    services: list[str] = Field(
        default_factory=list,
        description="List of service names relevant to this goal"
    )

    environment: Environment = Field(
        default=Environment.UNKNOWN,
        description="Target environment (production, staging, development)"
    )

    priority: Priority = Field(
        default=Priority.UNKNOWN,
        description="Priority/severity level of this goal"
    )

    tags: list[str] = Field(
        default_factory=list,
        description="Optional tags for categorization and memory retrieval"
    )

    context: Optional[str] = Field(
        default=None,
        max_length=5000,
        description="Additional context or background information"
    )

    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Timestamp when the goal was created"
    )

    requester: Optional[str] = Field(
        default=None,
        description="Identifier for who requested this goal (e.g., username, team)"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "description": "Investigate elevated 5xx errors for the checkout service in prod and recommend mitigation",
                    "services": ["checkout-api", "payments"],
                    "environment": "production",
                    "priority": "high",
                    "tags": ["error-rate", "checkout"],
                    "context": "Started seeing increased errors around 2pm UTC after deployment v2.3.1"
                },
                {
                    "description": "Debug slow response times on the login API endpoint",
                    "services": ["auth-service"],
                    "environment": "production",
                    "priority": "medium",
                    "tags": ["latency", "authentication"]
                }
            ]
        }
    }

    def to_prompt_context(self) -> str:
        """
        Generate a formatted context string for LLM prompts.

        Returns:
            A structured string representation suitable for LLM context.
        """
        parts = [f"Goal: {self.description}"]

        if self.services:
            parts.append(f"Services: {', '.join(self.services)}")

        if self.environment != Environment.UNKNOWN:
            parts.append(f"Environment: {self.environment.value}")

        if self.priority != Priority.UNKNOWN:
            parts.append(f"Priority: {self.priority.value}")

        if self.tags:
            parts.append(f"Tags: {', '.join(self.tags)}")

        if self.context:
            parts.append(f"Additional Context: {self.context}")

        return "\n".join(parts)

    def get_keywords(self) -> list[str]:
        """
        Extract keywords for memory retrieval and matching.

        Returns:
            List of relevant keywords from the goal.
        """
        keywords = list(self.services) + list(self.tags)

        # Add environment and priority if known
        if self.environment != Environment.UNKNOWN:
            keywords.append(self.environment.value)

        if self.priority != Priority.UNKNOWN:
            keywords.append(self.priority.value)

        # Extract simple keywords from description (basic tokenization)
        # In a real implementation, this could use NLP for better extraction
        common_words = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "must", "shall",
            "can", "need", "dare", "ought", "used", "to", "for", "in",
            "on", "at", "by", "with", "from", "of", "and", "or", "but"
        }

        words = self.description.lower().split()
        for word in words:
            cleaned = "".join(c for c in word if c.isalnum())
            if cleaned and len(cleaned) > 2 and cleaned not in common_words:
                keywords.append(cleaned)

        return list(set(keywords))
