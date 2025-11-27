"""
AutoOps Architect - Zero/low-code meta-agent for autonomous SRE & ops workflows.

This package provides tools to:
- Parse natural language operations goals
- Generate executable workflow graphs
- Execute workflows using pluggable tools
- Learn from past executions to improve future planning
"""

__version__ = "1.0.0"

from autoops_architect.models.goal import Goal
from autoops_architect.models.workflow import Edge, Node, WorkflowGraph
from autoops_architect.models.execution import ExecutionResult, NodeResult, ExecutionStatus

__all__ = [
    "Goal",
    "Node",
    "Edge",
    "WorkflowGraph",
    "ExecutionResult",
    "NodeResult",
    "ExecutionStatus",
]
