# AutoOps Architect Overview

## What is AutoOps Architect?

AutoOps Architect is a **meta-agent** that transforms natural language operations goals into executable workflow graphs. It's designed for SRE, DevOps, SecOps, and support engineers who want AI-powered assistance for incident investigation and remediation.

## Key Concepts

### Goals

A **Goal** is a natural language description of what you want to accomplish:

```
"Investigate elevated 5xx errors for the checkout service in production"
```

Goals can include metadata like:
- Target services
- Environment (prod/staging/dev)
- Priority level
- Additional context

### Workflow Graphs

A **WorkflowGraph** is a directed acyclic graph (DAG) representing the execution plan:

- **Nodes** are individual steps or actions
- **Edges** define dependencies between nodes
- The graph is topologically sorted for execution

Example workflow structure:
```
Collect Logs ──┐
               ├──▶ Analyze Data ──▶ RCA ──▶ Summary
Query Metrics ─┘
```

### Nodes

Each **Node** represents a step in the workflow:

| Field | Description |
|-------|-------------|
| `id` | Unique identifier |
| `name` | Human-readable name |
| `type` | Operation type (log_collection, analysis, etc.) |
| `tool` | Tool identifier for execution |
| `params` | Tool-specific parameters |
| `requires_human_approval` | Whether human approval is needed |

### Node Types

| Type | Description |
|------|-------------|
| `log_collection` | Gather logs from services |
| `metric_query` | Query monitoring metrics |
| `trace_collection` | Collect distributed traces |
| `rca_call` | Root cause analysis |
| `analysis` | General data analysis |
| `summary` | Generate summaries |
| `ticket_create` | Create tickets (Jira, etc.) |
| `notification` | Send notifications |
| `service_restart` | Restart services (requires approval) |
| `rollback` | Rollback deployments (requires approval) |

### Tools

**Tools** are the execution units that perform actual work:

- `log_collector` - Collect logs
- `metric_query` - Query metrics
- `autoRCA` - Root cause analysis
- `summary` - Generate summaries
- `secureMCP:jira` - Jira integration
- `secureMCP:slack` - Slack integration

### Memory

**Memory** provides institutional knowledge:

- Stores past workflow executions
- Remembers what worked for similar goals
- Stores user preferences
- Helps the planner make better decisions

## How It Works

1. **Goal Parsing**: The Architect receives a natural language goal
2. **Memory Retrieval**: Similar past workflows are retrieved
3. **Workflow Generation**: LLM generates a workflow graph
4. **Validation**: The workflow is validated for correctness
5. **Execution**: Nodes are executed in topological order
6. **Results**: Outcomes are collected and summarized
7. **Learning**: The workflow is saved to memory

## Safety Features

- Dangerous operations require human approval
- Workflow validation prevents cycles and invalid references
- Tools can be enabled/disabled globally
- Dry-run mode for testing without side effects

## Integration Points

AutoOps Architect is designed to integrate with:

- **AutoRCA-Core**: AI-powered root cause analysis
- **Secure-MCP-Gateway**: Secure tool execution
- **Ops-Agent-Desktop**: Browser automation
- Standard monitoring tools (Prometheus, Datadog, etc.)
- Ticketing systems (Jira, ServiceNow)
- Communication tools (Slack, PagerDuty)
