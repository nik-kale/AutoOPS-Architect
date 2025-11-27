# Tools

## Overview

Tools are the execution units in AutoOps Architect. Each tool performs a specific action and returns structured results.

## Built-in Tools

### echo

**Purpose**: Testing and debugging

**Parameters**:
```json
{
  "message": "Message to echo"
}
```

**Output**:
```json
{
  "echoed_params": { ... },
  "timestamp": "2024-01-01T12:00:00"
}
```

### log_collector

**Purpose**: Collect logs from services

**Parameters**:
```json
{
  "service": "service-name",      // Required
  "duration": "1h",               // Default: 1h
  "level": "error",               // debug, info, warn, error
  "query": "search terms"         // Optional search
}
```

**Output**:
```json
{
  "service": "service-name",
  "log_count": 1523,
  "error_count": 47,
  "warn_count": 120,
  "logs": [ ... ]  // Sample logs
}
```

### metric_query

**Purpose**: Query metrics from monitoring systems

**Parameters**:
```json
{
  "service": "service-name",
  "metric_name": "http_requests_total",
  "duration": "1h"
}
```

**Output**:
```json
{
  "service": "service-name",
  "metric_name": "http_requests_total",
  "current_value": 1234.5,
  "avg_value": 1000.0,
  "max_value": 2000.0,
  "min_value": 500.0,
  "data_points": 60
}
```

### log_analyzer

**Purpose**: Analyze logs and data for patterns

**Parameters**:
```json
{
  "analysis_type": "error_patterns"  // error_patterns, latency, anomaly_detection
}
```

**Output**:
```json
{
  "analysis_type": "error_patterns",
  "findings": [
    {
      "type": "error_pattern",
      "description": "Found 47 error log entries",
      "severity": "high"
    }
  ],
  "severity": "high",
  "recommendation": "Immediate investigation recommended"
}
```

### summary

**Purpose**: Generate human-readable summaries

**Parameters**:
```json
{
  "format": "brief",              // brief, detailed, markdown
  "include_recommendations": true
}
```

**Output**:
```json
{
  "format": "brief",
  "summary": "Investigation Summary\n...",
  "data_sources": ["analysis", "logs"]
}
```

## Integration Tools

### autoRCA

**Purpose**: Root cause analysis via AutoRCA-Core

**Configuration**:
```bash
export AUTORCA_URL="http://localhost:8080"
```

**Parameters**:
```json
{
  "incident_id": "INC-12345",
  "symptoms": ["High error rate", "Slow responses"],
  "context": { ... }
}
```

**Output**:
```json
{
  "status": "completed",
  "root_cause": {
    "category": "resource_exhaustion",
    "description": "Database connection pool exhausted",
    "confidence": 0.85
  },
  "contributing_factors": [ ... ],
  "recommendations": [ ... ]
}
```

### secureMCP

**Purpose**: Execute tools via Secure-MCP-Gateway

**Configuration**:
```bash
export MCP_GATEWAY_URL="http://localhost:3000"
export MCP_API_KEY="your-api-key"
```

**Parameters**:
```json
{
  "server": "jira",               // jira, slack, pagerduty
  "action": "create_issue",
  "arguments": {
    "project": "OPS",
    "summary": "Issue title",
    "priority": "High"
  }
}
```

**Jira Actions**:
- `create_issue` - Create a new issue
- `update_issue` - Update existing issue
- `add_comment` - Add a comment

**Slack Actions**:
- `send_message` - Send to channel
- `send_dm` - Send direct message

**PagerDuty Actions**:
- `create_incident` - Create incident
- `acknowledge` - Acknowledge incident
- `resolve` - Resolve incident

### browser

**Purpose**: Browser automation via Ops-Agent-Desktop

**Configuration**:
```bash
export OPS_AGENT_DESKTOP_URL="http://localhost:9090"
```

**Parameters**:
```json
{
  "mission_type": "health_check",  // health_check, ui_test, data_extraction
  "target_url": "https://example.com",
  "parameters": { ... }
}
```

**Output**:
```json
{
  "status": "completed",
  "mission_type": "health_check",
  "duration_ms": 2500,
  "steps_completed": 5,
  "findings": [ ... ]
}
```

## Creating Custom Tools

### Basic Structure

```python
from autoops_architect.tools.base import Tool, ToolConfig, ToolResult

class MyTool(Tool):
    """My custom tool description."""

    @property
    def tool_id(self) -> str:
        return "my_tool"

    @property
    def description(self) -> str:
        return "Description of what my tool does"

    @property
    def param_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "required_param": {
                    "type": "string",
                    "description": "A required parameter"
                },
                "optional_param": {
                    "type": "integer",
                    "description": "An optional parameter"
                }
            },
            "required": ["required_param"]
        }

    async def execute(
        self,
        params: dict,
        context: dict = None
    ) -> ToolResult:
        # Get parameters
        required = params.get("required_param")
        optional = params.get("optional_param", 42)

        # Access context from previous nodes
        if context:
            previous_data = context.get("previous_node", {})

        try:
            # Do your work here
            result = await self._do_work(required, optional)

            return ToolResult.success(
                outputs={"result": result},
                raw_output="Human-readable output",
                artifacts=["path/to/artifact.json"]
            )
        except Exception as e:
            return ToolResult.failed(str(e))

    async def _do_work(self, required, optional):
        # Implementation
        pass
```

### Registering Your Tool

```python
from autoops_architect.tools.base import ToolRegistry

registry = ToolRegistry()
registry.register(MyTool())

# Or from the default registry
from autoops_architect.tools.base import create_default_registry

registry = create_default_registry()
registry.register(MyTool())
```

### Using with Executor

```python
from autoops_architect.executor import WorkflowExecutor

executor = WorkflowExecutor(tool_registry=registry)
result = await executor.execute(workflow)
```

## Tool Configuration

### Enabling/Disabling Tools

```python
from autoops_architect.tools.base import ToolConfig

# Create disabled tool
config = ToolConfig(enabled=False)
tool = MyTool(config=config)

# Or update existing
tool.config.enabled = False
```

### Timeouts

```python
config = ToolConfig(timeout_seconds=120)  # 2 minute timeout
```

### Retries

```python
config = ToolConfig(retry_count=3)  # Retry 3 times on failure
```

## Context Passing

Tools receive context from previous nodes:

```python
async def execute(self, params, context=None):
    # Context is a dict mapping node_id -> outputs
    if context:
        # Get outputs from 'collect-logs' node
        log_data = context.get("collect-logs", {})
        logs = log_data.get("logs", [])
```

## Best Practices

1. **Make tools atomic** - One tool, one responsibility
2. **Return structured data** - Use typed outputs
3. **Include raw output** - For debugging and display
4. **Handle errors gracefully** - Return `ToolResult.failed()` instead of raising
5. **Document parameters** - Use `param_schema` property
6. **Support context** - Use data from previous nodes when available
7. **Be stateless** - Don't store state between executions
