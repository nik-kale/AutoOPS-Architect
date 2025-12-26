"""Architect - the meta-agent that generates workflow plans from goals."""

import json
import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from autoops_architect.llm.base import LLMClient, LLMConfig, LLMMessage
from autoops_architect.llm.providers import get_llm_client
from autoops_architect.models.goal import Goal
from autoops_architect.models.memory import MemoryEntry
from autoops_architect.models.workflow import Edge, Node, NodeType, WorkflowGraph
from autoops_architect.planner.prompts import (
    SYSTEM_PROMPT,
    format_planning_prompt,
)
from autoops_architect.safety.sanitizer import sanitize_goal, PromptInjectionError


class PlannerConfig(BaseModel):
    """Configuration for the Architect planner."""

    llm_config: Optional[LLMConfig] = Field(
        default=None,
        description="LLM configuration. If None, auto-detects from environment."
    )

    available_tools: list[str] = Field(
        default_factory=lambda: [
            "log_collector",
            "metric_query",
            "trace_collector",
            "autoRCA",
            "summary",
            "echo",
            "secureMCP:jira",
            "secureMCP:slack",
        ],
        description="List of available tool identifiers"
    )

    default_constraints: list[str] = Field(
        default_factory=lambda: [
            "Prioritize investigation before remediation",
            "All remediation actions require human approval",
            "Keep workflows focused and actionable",
        ],
        description="Default constraints for all planning requests"
    )

    max_nodes: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of nodes in a workflow"
    )

    enable_remediation: bool = Field(
        default=False,
        description="Whether to allow remediation actions in generated workflows"
    )

    use_memory: bool = Field(
        default=True,
        description="Whether to retrieve similar past workflows from memory"
    )

    memory_limit: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum number of similar workflows to include as context"
    )

    sanitization_mode: str = Field(
        default="strict",
        description="Input sanitization mode: strict, moderate, or permissive"
    )

    block_on_injection: bool = Field(
        default=True,
        description="Whether to block requests when prompt injection is detected"
    )


class Architect:
    """
    The Architect is the core meta-agent that transforms natural language goals
    into executable workflow graphs.

    It uses an LLM to understand the goal, consider past similar workflows,
    and generate a structured plan that can be executed by the workflow engine.

    Example:
        >>> architect = Architect()
        >>> goal = Goal(
        ...     description="Investigate elevated 5xx errors for checkout service",
        ...     services=["checkout-api"],
        ...     environment=Environment.PRODUCTION
        ... )
        >>> workflow = await architect.plan(goal)
        >>> print(workflow.to_mermaid())
    """

    def __init__(
        self,
        config: Optional[PlannerConfig] = None,
        llm_client: Optional[LLMClient] = None,
        memory_backend: Optional[Any] = None,
        template_registry: Optional[Any] = None,
    ) -> None:
        """
        Initialize the Architect.

        Args:
            config: Planner configuration.
            llm_client: Optional pre-configured LLM client.
            memory_backend: Optional memory backend for retrieving past workflows.
            template_registry: Optional template registry for template-based planning.
        """
        self.config = config or PlannerConfig()
        self._llm_client = llm_client
        self._memory_backend = memory_backend
        self._template_registry = template_registry

    @property
    def llm_client(self) -> LLMClient:
        """Get or create the LLM client."""
        if self._llm_client is None:
            self._llm_client = get_llm_client(self.config.llm_config)
        return self._llm_client

    async def plan(
        self,
        goal: Goal,
        constraints: Optional[list[str]] = None,
        similar_workflows: Optional[list[MemoryEntry]] = None,
    ) -> WorkflowGraph:
        """
        Generate a workflow graph from a goal.

        Args:
            goal: The Goal to plan for.
            constraints: Optional additional constraints.
            similar_workflows: Optional similar past workflows.
                If None and memory is enabled, will retrieve from memory.

        Returns:
            A WorkflowGraph ready for execution.

        Raises:
            ValueError: If the generated workflow is invalid.
            LLMError: If the LLM request fails.
            PromptInjectionError: If prompt injection is detected in goal.
        """
        # Sanitize goal description to prevent prompt injection
        try:
            sanitized_description = sanitize_goal(
                goal.description,
                mode=self.config.sanitization_mode,
                raise_on_injection=self.config.block_on_injection,
            )
            # Update goal with sanitized description
            goal.description = sanitized_description
        except PromptInjectionError:
            # Re-raise with additional context
            raise
        except ValueError as e:
            raise ValueError(f"Goal validation failed: {e}")

        # Retrieve similar workflows from memory if enabled
        if similar_workflows is None and self.config.use_memory and self._memory_backend:
            keywords = goal.get_keywords()
            similar_workflows = self._memory_backend.search(
                keywords=keywords,
                limit=self.config.memory_limit,
            )

        # Build constraints list
        all_constraints = list(self.config.default_constraints)
        if constraints:
            all_constraints.extend(constraints)

        if not self.config.enable_remediation:
            all_constraints.append(
                "Do not include remediation actions (restarts, rollbacks, config changes)"
            )

        all_constraints.append(f"Maximum {self.config.max_nodes} nodes allowed")

        # Format the planning prompt
        user_prompt = format_planning_prompt(
            goal=goal,
            similar_workflows=similar_workflows,
            available_tools=self.config.available_tools,
            constraints=all_constraints,
        )

        # Call LLM to generate the workflow
        messages = [
            LLMMessage(role="system", content=SYSTEM_PROMPT),
            LLMMessage(role="user", content=user_prompt),
        ]

        workflow_data = await self.llm_client.complete_json(messages)

        # Parse and validate the workflow
        workflow = self._parse_workflow(workflow_data, goal)

        return workflow

    def plan_sync(
        self,
        goal: Goal,
        constraints: Optional[list[str]] = None,
        similar_workflows: Optional[list[MemoryEntry]] = None,
    ) -> WorkflowGraph:
        """
        Synchronous version of plan().

        Args:
            goal: The Goal to plan for.
            constraints: Optional additional constraints.
            similar_workflows: Optional similar past workflows.

        Returns:
            A WorkflowGraph ready for execution.
        """
        import asyncio

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        return loop.run_until_complete(
            self.plan(goal, constraints=constraints, similar_workflows=similar_workflows)
        )

    def _parse_workflow(self, data: dict[str, Any], goal: Goal) -> WorkflowGraph:
        """
        Parse and validate LLM output into a WorkflowGraph.

        Args:
            data: Raw JSON data from the LLM.
            goal: The original goal (for fallback values).

        Returns:
            A validated WorkflowGraph.

        Raises:
            ValueError: If the data is invalid.
        """
        # Ensure required fields
        if "id" not in data:
            data["id"] = f"wf-{uuid.uuid4().hex[:8]}"

        if "name" not in data:
            data["name"] = goal.description[:50]

        if "goal_description" not in data:
            data["goal_description"] = goal.description

        # Parse nodes
        nodes = []
        for node_data in data.get("nodes", []):
            try:
                # Handle node type - convert string to enum
                node_type_str = node_data.get("type", "analysis")
                try:
                    node_type = NodeType(node_type_str)
                except ValueError:
                    # Default to analysis if unknown type
                    node_type = NodeType.ANALYSIS

                node = Node(
                    id=node_data.get("id", f"node-{uuid.uuid4().hex[:6]}"),
                    name=node_data.get("name", "Unnamed step"),
                    description=node_data.get("description", ""),
                    type=node_type,
                    tool=node_data.get("tool", "echo"),
                    params=node_data.get("params", {}),
                    requires_human_approval=node_data.get("requires_human_approval", False),
                    timeout_seconds=node_data.get("timeout_seconds"),
                    retry_count=node_data.get("retry_count", 0),
                    continue_on_failure=node_data.get("continue_on_failure", False),
                )
                nodes.append(node)
            except Exception as e:
                raise ValueError(f"Invalid node data: {node_data}. Error: {e}")

        # Parse edges
        edges = []
        for edge_data in data.get("edges", []):
            try:
                edge = Edge(
                    from_node_id=edge_data["from_node_id"],
                    to_node_id=edge_data["to_node_id"],
                    condition=edge_data.get("condition"),
                )
                edges.append(edge)
            except Exception as e:
                raise ValueError(f"Invalid edge data: {edge_data}. Error: {e}")

        # Create the workflow
        workflow = WorkflowGraph(
            id=data["id"],
            name=data["name"],
            goal_description=data["goal_description"],
            nodes=nodes,
            edges=edges,
            created_at=datetime.utcnow(),
            version="1.0",
            metadata=data.get("metadata", {}),
        )

        return workflow

    async def refine(
        self,
        workflow: WorkflowGraph,
        feedback: str,
    ) -> WorkflowGraph:
        """
        Refine an existing workflow based on user feedback.

        Args:
            workflow: The workflow to refine.
            feedback: User feedback or requested changes.

        Returns:
            A refined WorkflowGraph.
        """
        refinement_prompt = f"""
## Current Workflow

```json
{workflow.model_dump_json(indent=2)}
```

## User Feedback

{feedback}

## Instructions

Based on the user's feedback, generate an updated workflow. Maintain the same goal
but incorporate the requested changes. Respond with the complete updated workflow JSON.
"""

        messages = [
            LLMMessage(role="system", content=SYSTEM_PROMPT),
            LLMMessage(role="user", content=refinement_prompt),
        ]

        workflow_data = await self.llm_client.complete_json(messages)

        # Create a Goal from the workflow for parsing
        goal = Goal(description=workflow.goal_description)
        return self._parse_workflow(workflow_data, goal)

    def validate_workflow(self, workflow: WorkflowGraph) -> list[str]:
        """
        Validate a workflow and return any issues.

        Args:
            workflow: The workflow to validate.

        Returns:
            List of validation issues (empty if valid).
        """
        issues = []

        # Check node count
        if len(workflow.nodes) > self.config.max_nodes:
            issues.append(
                f"Workflow has {len(workflow.nodes)} nodes, "
                f"exceeds maximum of {self.config.max_nodes}"
            )

        # Check for unknown tools
        known_tools = set(self.config.available_tools)
        for node in workflow.nodes:
            if node.tool not in known_tools:
                # Only warn, don't fail - could be a custom tool
                issues.append(
                    f"Node '{node.id}' uses unknown tool '{node.tool}'"
                )

        # Check for remediation actions if disabled
        if not self.config.enable_remediation:
            remediation_types = {
                NodeType.SERVICE_RESTART,
                NodeType.CONFIG_UPDATE,
                NodeType.ROLLBACK,
                NodeType.SCALE_ACTION,
            }
            for node in workflow.nodes:
                if node.type in remediation_types:
                    issues.append(
                        f"Node '{node.id}' is a remediation action but remediation is disabled"
                    )

        # Check that all approval-required nodes are marked correctly
        for node in workflow.nodes:
            if node.type in {
                NodeType.SERVICE_RESTART,
                NodeType.CONFIG_UPDATE,
                NodeType.ROLLBACK,
                NodeType.SCALE_ACTION,
                NodeType.CUSTOM_SCRIPT,
            }:
                if not node.requires_human_approval:
                    issues.append(
                        f"Node '{node.id}' ({node.type.value}) should require human approval"
                    )

        return issues

    def plan_from_template(
        self,
        template_id: str,
        goal: Goal,
        **kwargs: Any,
    ) -> WorkflowGraph:
        """
        Create a workflow from a template.

        Args:
            template_id: ID of the template to use.
            goal: The Goal this workflow addresses.
            **kwargs: Additional parameters to pass to the template.

        Returns:
            A WorkflowGraph instantiated from the template.

        Raises:
            ValueError: If the template is not found.
        """
        if self._template_registry is None:
            from autoops_architect.templates.registry import create_default_template_registry
            self._template_registry = create_default_template_registry()

        template = self._template_registry.get(template_id)
        if template is None:
            raise ValueError(f"Template not found: {template_id}")

        # Get service from goal if not provided
        service = kwargs.pop("service", None)
        if service is None and goal.services:
            service = goal.services[0]

        return template.instantiate(
            goal_description=goal.description,
            service=service,
            **kwargs,
        )

    def list_templates(self) -> list[dict[str, Any]]:
        """
        List available templates.

        Returns:
            List of template info dictionaries.
        """
        if self._template_registry is None:
            from autoops_architect.templates.registry import create_default_template_registry
            self._template_registry = create_default_template_registry()

        return [
            {
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "category": t.category,
                "tags": t.tags,
            }
            for t in self._template_registry.list()
        ]

    def find_matching_template(self, goal: Goal) -> Optional[str]:
        """
        Find a template that matches the given goal.

        Uses keyword matching to find the best template.

        Args:
            goal: The Goal to match.

        Returns:
            Template ID if a match is found, None otherwise.
        """
        if self._template_registry is None:
            from autoops_architect.templates.registry import create_default_template_registry
            self._template_registry = create_default_template_registry()

        keywords = goal.get_keywords()
        goal_lower = goal.description.lower()

        best_match = None
        best_score = 0

        for template in self._template_registry.list():
            score = 0

            # Check tag matches
            for tag in template.tags:
                if tag.lower() in keywords or tag.lower() in goal_lower:
                    score += 2

            # Check name/description matches
            for keyword in keywords:
                if keyword.lower() in template.name.lower():
                    score += 1
                if keyword.lower() in template.description.lower():
                    score += 1

            # Check for specific keywords
            if "5xx" in goal_lower or "error" in goal_lower:
                if "error" in template.category or "error" in str(template.tags):
                    score += 3

            if "latency" in goal_lower or "slow" in goal_lower:
                if "performance" in template.category or "latency" in str(template.tags):
                    score += 3

            if "auth" in goal_lower or "login" in goal_lower:
                if "security" in template.category or "auth" in str(template.tags):
                    score += 3

            if score > best_score:
                best_score = score
                best_match = template.id

        # Only return if we have a reasonable match
        return best_match if best_score >= 3 else None
