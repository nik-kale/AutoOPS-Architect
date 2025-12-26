# AutoOps Architect

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/tests-passing-brightgreen.svg)]()

**Zero/low-code meta-agent that designs and runs autonomous SRE & ops workflows from natural language goals.**

AutoOps Architect takes your operations goals (like "investigate elevated 5xx errors") and automatically generates executable workflow graphs that collect data, analyze issues, and recommend actions - all without writing code.

## Why AutoOps Architect?

- **Natural Language to Action**: Describe what you want to investigate, and the system creates a structured workflow
- **Composable Workflows**: Generated workflows are DAGs (directed acyclic graphs) with clear dependencies
- **Pluggable Tools**: Integrate with your existing monitoring, ticketing, and automation systems
- **Institutional Memory**: Learn from past investigations to improve future workflows
- **Human-in-the-Loop**: Dangerous operations require explicit approval

## Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/nik-kale/AutoOPS-Architect.git
cd AutoOPS-Architect

# Install with pip
pip install -e .

# Or with development dependencies
pip install -e ".[dev]"
```

### Basic Usage

```bash
# Generate a workflow plan from a goal
autoops plan "Investigate elevated 5xx errors for the checkout service in prod"

# Execute a workflow file
autoops run workflow.json

# Plan and execute in one step
autoops plan-and-run "Check why login API is slow" --service auth-api --env production
```

### Example Output

```
AutoOps Architect
Planning workflow for:
Investigate elevated 5xx errors for the checkout service in prod

Generated workflow: Investigate 5xx Errors Workflow
ID: wf-5xx-investigation-001
Nodes: 6, Edges: 5

Workflow Steps
├── 🔧 [log_collection] Collect service logs
├── 🔧 [metric_query] Query error rate metrics
├── 🔧 [analysis] Analyze collected data
├── 🔧 [rca_call] Run root cause analysis
├── 🔧 [summary] Generate investigation summary
└── 🔧 [ticket_create] Create tracking ticket
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         User Goal                                │
│        "Investigate elevated 5xx errors for checkout"           │
└─────────────────────────────────┬───────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Architect (Planner)                       │
│                                                                  │
│  • Parses goal                                                   │
│  • Retrieves similar past workflows from memory                  │
│  • Uses LLM to generate workflow graph                           │
└─────────────────────────────────┬───────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                        WorkflowGraph (DAG)                       │
│                                                                  │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐     │
│  │ Collect  │──▶│ Analyze  │──▶│   RCA    │──▶│ Summary  │     │
│  │  Logs    │   │  Data    │   │  Call    │   │          │     │
│  └──────────┘   └──────────┘   └──────────┘   └──────────┘     │
└─────────────────────────────────┬───────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                         Executor                                 │
│                                                                  │
│  • Topologically sorts nodes                                     │
│  • Executes nodes via Tools                                      │
│  • Handles failures and approvals                                │
│  • Collects results                                              │
└─────────────────────────────────┬───────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Memory Backend                               │
│                                                                  │
│  • Stores workflow history                                       │
│  • User preferences                                              │
│  • Successful playbooks for reuse                                │
└─────────────────────────────────────────────────────────────────┘
```

## Ecosystem Integration

AutoOps Architect is designed to work with the broader AutoOps ecosystem:

| Component | Description | Status |
|-----------|-------------|--------|
| **AutoRCA-Core** | AI-powered root cause analysis | 🔜 Integration ready |
| **Secure-MCP-Gateway** | Secure tool execution (Jira, Slack, etc.) | 🔜 Integration ready |
| **Ops-Agent-Desktop** | Browser-based mission automation | 🔜 Integration ready |
| **Autonomous Ops Hub** | Central orchestration platform | 📋 Planned |

## Configuration

### Environment Variables

```bash
# LLM Provider (auto-detected if not set)
export OPENAI_API_KEY="sk-..."
# or
export ANTHROPIC_API_KEY="sk-..."

# Logging configuration
export AUTOOPS_LOG_LEVEL="INFO"      # DEBUG, INFO, WARNING, ERROR, CRITICAL
export AUTOOPS_DEV_MODE="1"          # Enable colorful console logs (default: auto-detect TTY)

# Optional integrations
export AUTORCA_URL="http://localhost:8080"
export MCP_GATEWAY_URL="http://localhost:3000"
export OPS_AGENT_DESKTOP_URL="http://localhost:9090"
```

### Using Different LLM Providers

```python
from autoops_architect.llm import LLMConfig, LLMProvider
from autoops_architect.planner import Architect, PlannerConfig

# Use OpenAI
config = PlannerConfig(
    llm_config=LLMConfig(
        provider=LLMProvider.OPENAI,
        model="gpt-4",
    )
)

# Use Anthropic
config = PlannerConfig(
    llm_config=LLMConfig(
        provider=LLMProvider.ANTHROPIC,
        model="claude-3-sonnet-20240229",
    )
)

# Use mock (for testing)
config = PlannerConfig(
    llm_config=LLMConfig(provider=LLMProvider.MOCK)
)

architect = Architect(config=config)
```

### Structured Logging

AutoOps Architect uses structured JSON logging with automatic correlation IDs for debugging and observability in production.

**Features:**
- JSON-structured logs for easy parsing and aggregation
- Automatic correlation IDs: `workflow_id`, `execution_id`, `node_id`
- Sensitive data redaction (API keys, passwords, tokens)
- Configurable log levels via environment variable
- Development-friendly colored console output

```python
from autoops_architect.logging import get_logger, LogContext, configure_logging

# Configure logging (usually done automatically)
configure_logging(log_level="INFO", json_logs=True)

# Get a logger
logger = get_logger(__name__)

# Log structured events
logger.info(
    "workflow_started",
    workflow_id="wf-123",
    node_count=5,
    environment="production"
)

# Use LogContext for automatic correlation IDs
with LogContext(workflow_id="wf-123", execution_id="exec-456"):
    logger.info("processing_node", node_id="collect-logs")
    # All logs within this context automatically include workflow_id and execution_id
```

**Example log output (JSON format):**

```json
{
  "timestamp": "2025-12-26T10:30:00.123456Z",
  "level": "info",
  "event": "node_execution_started",
  "workflow_id": "wf-abc123",
  "execution_id": "exec-xyz789",
  "node_id": "collect-logs",
  "node_name": "Collect service logs",
  "tool": "log_collector"
}
```

**Example log output (dev mode):**

```
2025-12-26 10:30:00 [info     ] node_execution_started  workflow_id=wf-abc123 node_id=collect-logs tool=log_collector
```

**Querying logs with jq:**

```bash
# Filter logs for a specific workflow
cat logs.json | jq 'select(.workflow_id == "wf-abc123")'

# Get all node execution failures
cat logs.json | jq 'select(.event == "node_execution_failed")'

# Calculate average node execution time
cat logs.json | jq -s '[.[] | select(.event == "node_execution_completed") | .duration_seconds] | add / length'
```

**Integration with log aggregation tools:**

- **Datadog**: Logs are automatically parsed as JSON with correlation IDs as indexed fields
- **ELK Stack**: Use the JSON codec in Filebeat/Logstash
- **CloudWatch Logs**: Use JSON log format and CloudWatch Insights for querying

## CLI Reference

```bash
# Plan a workflow
autoops plan "Your goal here" [OPTIONS]
  --service, -s    Target service(s)
  --env, -e        Environment (prod/staging/dev)
  --priority, -p   Priority level
  --output, -o     Output file path
  --yaml           Output as YAML
  --mock           Use mock LLM
  --mermaid        Show Mermaid diagram

# Run a workflow
autoops run <workflow.json> [OPTIONS]
  --dry-run, -n    Simulate execution
  --auto-approve   Auto-approve all requests

# Plan and run
autoops plan-and-run "Your goal" [OPTIONS]

# View history
autoops history [OPTIONS]
  --limit, -n      Number of entries
  --search, -q     Search keywords

# List available tools
autoops tools [OPTIONS]
  --all, -a        Show disabled tools

# Validate a workflow
autoops validate <workflow.json>

# Version info
autoops version
```

## Project Structure

```
autoops-architect/
├── src/autoops_architect/
│   ├── models/          # Data models (Goal, Workflow, etc.)
│   ├── planner/         # Architect/meta-agent logic
│   ├── executor/        # Workflow execution engine
│   ├── tools/           # Tool interface and implementations
│   ├── memory/          # Memory backends
│   ├── llm/             # LLM client abstraction
│   └── cli.py           # CLI application
├── tests/               # Test suite
├── examples/            # Example goals and workflows
├── docs/                # Documentation
└── pyproject.toml       # Project configuration
```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run tests with coverage
pytest --cov=autoops_architect

# Type checking
mypy src/autoops_architect

# Linting
ruff check src/

# Format code
ruff format src/
```

## Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Good First Issues

- Add a new tool integration
- Create example workflows for common scenarios
- Improve documentation
- Add more test cases

## Roadmap

See [docs/roadmap.md](docs/roadmap.md) for the detailed roadmap including:

- **Phase 2**: UI, templates, and real integrations
- **Phase 3**: Code quality, performance, and CI/CD
- **Phase 4**: Security, safety, and QA
- **Phase 5**: Ecosystem and community features

## License

MIT License - see [LICENSE](LICENSE) for details.

## Acknowledgments

Built with:
- [Pydantic](https://pydantic.dev/) for data validation
- [Typer](https://typer.tiangolo.com/) for CLI
- [Rich](https://rich.readthedocs.io/) for terminal output
- [NetworkX](https://networkx.org/) for graph operations
