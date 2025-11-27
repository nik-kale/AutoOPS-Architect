# Architecture

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              CLI / API                                   │
│                                                                          │
│  autoops plan "..."    autoops run workflow.json    REST API (future)   │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                            Core Library                                  │
│                                                                          │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                  │
│  │   Models    │    │   Planner   │    │  Executor   │                  │
│  │             │    │ (Architect) │    │             │                  │
│  │ Goal        │◀───│             │───▶│ Engine      │                  │
│  │ Workflow    │    │ Prompts     │    │ Callbacks   │                  │
│  │ Results     │    │ Parsing     │    │ Scheduling  │                  │
│  └─────────────┘    └──────┬──────┘    └──────┬──────┘                  │
│                            │                  │                          │
│                            ▼                  ▼                          │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                  │
│  │   Memory    │    │    LLM      │    │   Tools     │                  │
│  │             │    │   Client    │    │             │                  │
│  │ JSON/SQLite │    │             │    │ Registry    │                  │
│  │ Preferences │    │ OpenAI     │    │ Built-in    │                  │
│  │ History     │    │ Anthropic   │    │ Integrations│                  │
│  └─────────────┘    │ Mock        │    └─────────────┘                  │
│                     └─────────────┘                                      │
└─────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         External Systems                                 │
│                                                                          │
│  AutoRCA-Core    Secure-MCP-Gateway    Ops-Agent-Desktop    Monitoring  │
└─────────────────────────────────────────────────────────────────────────┘
```

## Component Details

### Models (`autoops_architect.models`)

Data models using Pydantic for validation:

| Model | Description |
|-------|-------------|
| `Goal` | User's natural language request with metadata |
| `Node` | Single step in a workflow |
| `Edge` | Dependency between nodes |
| `WorkflowGraph` | Complete DAG of nodes and edges |
| `NodeResult` | Result of executing a single node |
| `WorkflowRunResult` | Complete execution result |
| `MemoryEntry` | Stored workflow history |

### Planner (`autoops_architect.planner`)

The Architect component that generates workflows:

```python
class Architect:
    def plan(self, goal: Goal) -> WorkflowGraph:
        """Generate a workflow from a goal."""

    def refine(self, workflow: WorkflowGraph, feedback: str) -> WorkflowGraph:
        """Refine a workflow based on feedback."""

    def validate_workflow(self, workflow: WorkflowGraph) -> list[str]:
        """Validate and return any issues."""
```

The planner uses:
- **System Prompt**: Defines the Architect's persona and capabilities
- **Planning Prompt Template**: Structures the goal and context
- **JSON Schema**: Validates the generated workflow

### Executor (`autoops_architect.executor`)

Executes workflow graphs:

```python
class WorkflowExecutor:
    def execute(self, workflow: WorkflowGraph) -> WorkflowRunResult:
        """Execute a workflow and return results."""

    def execute_single_node(self, node: Node) -> NodeResult:
        """Execute a single node independently."""
```

Features:
- Topological sorting for execution order
- Context passing between nodes
- Failure handling (stop or continue)
- Human approval gates
- Dry-run mode

### Tools (`autoops_architect.tools`)

Tool interface and implementations:

```python
class Tool(ABC):
    @property
    def tool_id(self) -> str: ...

    async def execute(
        self,
        params: dict,
        context: dict = None
    ) -> ToolResult: ...
```

**Built-in Tools:**
- `EchoTool` - Testing/debugging
- `LogCollectorTool` - Log collection
- `MetricQueryTool` - Metric queries
- `AnalysisTool` - Data analysis
- `SummaryTool` - Summary generation

**Integration Tools:**
- `AutoRCATool` - AutoRCA-Core
- `MCPTool` - Secure-MCP-Gateway
- `BrowserMissionTool` - Ops-Agent-Desktop

### Memory (`autoops_architect.memory`)

Persistent storage for institutional knowledge:

```python
class MemoryBackend(ABC):
    def save_workflow_run(self, goal, workflow, result) -> str: ...
    def search(self, keywords: list[str]) -> list[MemoryEntry]: ...
    def get_preference(self, key: str) -> Any: ...
    def set_preference(self, key: str, value: Any) -> None: ...
```

Implementations:
- `JSONMemoryBackend` - File-based (default)
- `SQLiteMemoryBackend` - Database-based

### LLM (`autoops_architect.llm`)

Abstraction layer for LLM providers:

```python
class LLMClient(ABC):
    async def complete(self, messages: list[LLMMessage]) -> LLMResponse: ...
    async def complete_json(self, messages: list[LLMMessage]) -> dict: ...
```

Providers:
- `OpenAIClient` - OpenAI API
- `AnthropicClient` - Anthropic API
- `MockLLMClient` - Testing

## Data Flow

### Planning Flow

```
User Goal
    │
    ▼
┌─────────────────┐
│ Goal Parsing    │ ─── Extract services, environment, priority
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Memory Search   │ ─── Find similar past workflows
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Prompt Building │ ─── Combine goal + context + constraints
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ LLM Generation  │ ─── Generate workflow JSON
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Validation      │ ─── Parse, validate DAG, check constraints
└────────┬────────┘
         │
         ▼
WorkflowGraph
```

### Execution Flow

```
WorkflowGraph
    │
    ▼
┌─────────────────┐
│ Topological     │ ─── Determine execution order
│ Sort            │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ For each node   │ ◀───────────────┐
└────────┬────────┘                 │
         │                          │
         ▼                          │
┌─────────────────┐                 │
│ Check           │ ─── Are dependencies met?
│ Dependencies    │                 │
└────────┬────────┘                 │
         │                          │
         ▼                          │
┌─────────────────┐                 │
│ Check Approval  │ ─── Does node need approval?
└────────┬────────┘                 │
         │                          │
         ▼                          │
┌─────────────────┐                 │
│ Execute Tool    │ ─── Run the tool
└────────┬────────┘                 │
         │                          │
         ▼                          │
┌─────────────────┐                 │
│ Collect Result  │ ─── Store outputs
└────────┬────────┘                 │
         │                          │
         ▼                          │
    More nodes? ────────────────────┘
         │
         ▼
WorkflowRunResult
```

## Extension Points

### Adding a New Tool

```python
from autoops_architect.tools.base import Tool, ToolResult

class MyCustomTool(Tool):
    @property
    def tool_id(self) -> str:
        return "my_custom_tool"

    @property
    def description(self) -> str:
        return "My custom tool description"

    async def execute(self, params, context=None) -> ToolResult:
        # Implement your logic
        return ToolResult.success({"result": "done"})

# Register it
registry.register(MyCustomTool())
```

### Adding a Memory Backend

```python
from autoops_architect.memory.backend import MemoryBackend

class RedisMemoryBackend(MemoryBackend):
    def save_workflow_run(self, goal, workflow, result) -> str:
        # Implement Redis storage
        pass

    def search(self, keywords, limit=5) -> list[MemoryEntry]:
        # Implement Redis search
        pass
```

### Adding an LLM Provider

```python
from autoops_architect.llm.base import LLMClient

class MyLLMClient(LLMClient):
    async def complete(self, messages) -> LLMResponse:
        # Call your LLM
        pass

    async def complete_json(self, messages, schema=None) -> dict:
        # Get JSON response
        pass
```
