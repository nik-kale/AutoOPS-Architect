"""Prometheus metrics for AutoOps Architect."""

from prometheus_client import Counter, Histogram, Gauge, Info, generate_latest, CONTENT_TYPE_LATEST

# Workflow metrics
workflow_executions_total = Counter(
    "autoops_workflow_executions_total",
    "Total number of workflow executions",
    ["status", "template"]
)

workflow_execution_duration_seconds = Histogram(
    "autoops_workflow_execution_duration_seconds",
    "Workflow execution duration in seconds",
    ["status", "template"]
)

workflow_nodes_total = Gauge(
    "autoops_workflow_nodes_total",
    "Total number of nodes in active workflows",
    ["workflow_id"]
)

# Node execution metrics
node_executions_total = Counter(
    "autoops_node_executions_total",
    "Total number of node executions",
    ["status", "tool", "node_type"]
)

node_execution_duration_seconds = Histogram(
    "autoops_node_execution_duration_seconds",
    "Node execution duration in seconds",
    ["tool", "node_type"]
)

# LLM metrics
llm_requests_total = Counter(
    "autoops_llm_requests_total",
    "Total number of LLM requests",
    ["provider", "model", "status"]
)

llm_request_duration_seconds = Histogram(
    "autoops_llm_request_duration_seconds",
    "LLM request duration in seconds",
    ["provider", "model"]
)

llm_tokens_total = Counter(
    "autoops_llm_tokens_total",
    "Total number of LLM tokens used",
    ["provider", "model", "type"]  # type: prompt, completion
)

# Tool execution metrics
tool_executions_total = Counter(
    "autoops_tool_executions_total",
    "Total number of tool executions",
    ["tool", "status"]
)

tool_execution_duration_seconds = Histogram(
    "autoops_tool_execution_duration_seconds",
    "Tool execution duration in seconds",
    ["tool"]
)

# Memory backend metrics
memory_operations_total = Counter(
    "autoops_memory_operations_total",
    "Total number of memory operations",
    ["operation", "backend"]  # operation: read, write, search
)

memory_search_results = Histogram(
    "autoops_memory_search_results",
    "Number of results returned from memory searches",
    ["backend"]
)

# API metrics
api_requests_total = Counter(
    "autoops_api_requests_total",
    "Total number of API requests",
    ["method", "endpoint", "status_code"]
)

api_request_duration_seconds = Histogram(
    "autoops_api_request_duration_seconds",
    "API request duration in seconds",
    ["method", "endpoint"]
)

# System info
system_info = Info(
    "autoops_system",
    "System information"
)

# Active resources
active_workflows = Gauge(
    "autoops_active_workflows",
    "Number of currently active workflows"
)

active_executions = Gauge(
    "autoops_active_executions",
    "Number of currently running workflow executions"
)


def get_metrics() -> tuple[bytes, str]:
    """
    Get Prometheus metrics in text format.

    Returns:
        Tuple of (metrics_content, content_type)
    """
    return generate_latest(), CONTENT_TYPE_LATEST

