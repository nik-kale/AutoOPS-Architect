"""Prompt templates for the Architect planner."""

from typing import Optional

from jinja2 import Template

SYSTEM_PROMPT = """You are AutoOps Architect, an expert SRE and operations automation system.

Your job is to analyze operations goals and generate executable workflow graphs that investigate, diagnose, and remediate incidents.

You think in terms of:
1. Data Collection: Gathering logs, metrics, traces, and other observability data
2. Analysis: Identifying patterns, anomalies, and root causes
3. Communication: Creating tickets, sending notifications, updating stakeholders
4. Remediation: Taking safe corrective actions when appropriate

IMPORTANT RULES:
- Always prioritize investigation and understanding before any remediation
- Generate workflows as directed acyclic graphs (DAGs) - no cycles allowed
- Each node must have a unique ID (lowercase, alphanumeric with hyphens/underscores)
- Dangerous operations (restarts, rollbacks, config changes) must require human approval
- Keep workflows focused and actionable - avoid unnecessary complexity
- Prefer standard tools but allow custom scripts when needed

Available node types:
- log_collection: Gather logs from services or systems
- metric_query: Query metrics from monitoring systems
- trace_collection: Collect distributed traces
- rca_call: Invoke root cause analysis
- analysis: General analysis of collected data
- summary: Generate summaries or reports
- ticket_create: Create a new ticket/issue
- ticket_update: Update an existing ticket
- notification: Send notifications (Slack, email, PagerDuty, etc.)
- browser_replay: Run browser-based missions for testing
- service_restart: Restart a service (REQUIRES APPROVAL)
- config_update: Update configuration (REQUIRES APPROVAL)
- rollback: Rollback a deployment (REQUIRES APPROVAL)
- scale_action: Scale resources up/down (REQUIRES APPROVAL)
- custom_script: Run a custom script (REQUIRES APPROVAL)
- wait: Wait for a condition or time period
- decision: Conditional branching point
- human_review: Explicit human review step

Available tools (you can reference these in nodes):
- log_collector: Collect logs from services
- metric_query: Query Prometheus/Datadog/CloudWatch metrics
- trace_collector: Collect traces from Jaeger/Zipkin
- autoRCA: AutoRCA-Core root cause analysis
- summary: Generate text summaries
- echo: Simple echo for testing
- secureMCP:jira: Create/update Jira tickets via Secure-MCP-Gateway
- secureMCP:slack: Send Slack notifications via Secure-MCP-Gateway
- secureMCP:pagerduty: Manage PagerDuty incidents
- browser:ops-agent-desktop: Run browser missions
- shell: Execute shell commands (use with caution)

Output format: You must respond with valid JSON matching the WorkflowGraph schema."""


PLANNING_PROMPT_TEMPLATE = """
## Goal

{{ goal.description }}

{% if goal.services %}
## Target Services
{{ goal.services | join(', ') }}
{% endif %}

{% if goal.environment and goal.environment != 'unknown' %}
## Environment
{{ goal.environment }}
{% endif %}

{% if goal.priority and goal.priority != 'unknown' %}
## Priority
{{ goal.priority }}
{% endif %}

{% if goal.context %}
## Additional Context
{{ goal.context }}
{% endif %}

{% if similar_workflows %}
## Similar Past Workflows (for reference)
{% for wf in similar_workflows %}
### Previous: {{ wf.goal_description }}
Outcome: {{ wf.outcome_status }}
{% if wf.outcome_summary %}Lessons: {{ wf.outcome_summary }}{% endif %}
{% if wf.workflow_summary %}Approach: {{ wf.workflow_summary }}{% endif %}

{% endfor %}
{% endif %}

{% if available_tools %}
## Available Tools
{{ available_tools | join(', ') }}
{% endif %}

{% if constraints %}
## Constraints
{% for constraint in constraints %}
- {{ constraint }}
{% endfor %}
{% endif %}

## Instructions

Generate a workflow graph to address this goal. The workflow should:

1. Start with data collection (logs, metrics, traces as appropriate)
2. Analyze the collected data to understand the issue
3. Generate a summary of findings
4. Optionally create tickets or send notifications
5. Only include remediation steps if explicitly requested and mark them as requiring approval

Respond with a valid JSON object matching this schema:

```json
{
  "id": "wf-<unique-id>",
  "name": "<short descriptive name>",
  "goal_description": "<the original goal>",
  "nodes": [
    {
      "id": "<unique-node-id>",
      "name": "<short name>",
      "description": "<what this step does>",
      "type": "<node type from the list above>",
      "tool": "<tool identifier>",
      "params": { ... tool-specific parameters ... },
      "requires_human_approval": false
    }
  ],
  "edges": [
    {
      "from_node_id": "<source node id>",
      "to_node_id": "<target node id>"
    }
  ]
}
```

Generate the workflow now:
"""


def format_planning_prompt(
    goal: "Goal",  # type: ignore[name-defined]
    similar_workflows: Optional[list] = None,
    available_tools: Optional[list[str]] = None,
    constraints: Optional[list[str]] = None,
) -> str:
    """
    Format the planning prompt with the given goal and context.

    Args:
        goal: The Goal object to plan for.
        similar_workflows: Optional list of similar past workflows.
        available_tools: Optional list of available tool identifiers.
        constraints: Optional list of constraints for the planner.

    Returns:
        Formatted prompt string.
    """
    template = Template(PLANNING_PROMPT_TEMPLATE)

    return template.render(
        goal=goal,
        similar_workflows=similar_workflows or [],
        available_tools=available_tools,
        constraints=constraints or [],
    )


# JSON Schema for workflow validation
WORKFLOW_JSON_SCHEMA = {
    "type": "object",
    "required": ["id", "name", "goal_description", "nodes", "edges"],
    "properties": {
        "id": {"type": "string", "pattern": "^[a-zA-Z0-9_-]+$"},
        "name": {"type": "string", "minLength": 1, "maxLength": 200},
        "goal_description": {"type": "string"},
        "nodes": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "name", "type", "tool"],
                "properties": {
                    "id": {"type": "string", "pattern": "^[a-zA-Z0-9_-]+$"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": [
                            "log_collection",
                            "metric_query",
                            "trace_collection",
                            "rca_call",
                            "analysis",
                            "summary",
                            "ticket_create",
                            "ticket_update",
                            "notification",
                            "browser_replay",
                            "service_restart",
                            "config_update",
                            "rollback",
                            "scale_action",
                            "custom_script",
                            "wait",
                            "decision",
                            "human_review",
                        ],
                    },
                    "tool": {"type": "string"},
                    "params": {"type": "object"},
                    "requires_human_approval": {"type": "boolean"},
                    "timeout_seconds": {"type": "integer", "minimum": 1},
                    "retry_count": {"type": "integer", "minimum": 0},
                    "continue_on_failure": {"type": "boolean"},
                },
            },
        },
        "edges": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["from_node_id", "to_node_id"],
                "properties": {
                    "from_node_id": {"type": "string"},
                    "to_node_id": {"type": "string"},
                    "condition": {"type": "string"},
                },
            },
        },
        "metadata": {"type": "object"},
    },
}
