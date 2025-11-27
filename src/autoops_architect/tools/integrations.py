"""Integration tools for connecting to external systems.

These tools provide integration with:
- AutoRCA-Core: Root cause analysis
- Secure-MCP-Gateway: Secure tool execution via MCP
- Ops-Agent-Desktop: Browser-based mission execution

In Phase 1, these are stub implementations. Real integrations
will be added in Phase 2+.
"""

import os
from typing import Any, Optional

from autoops_architect.tools.base import Tool, ToolConfig, ToolResult


class AutoRCATool(Tool):
    """
    Integration with AutoRCA-Core for root cause analysis.

    AutoRCA-Core is a separate repository that provides AI-powered
    root cause analysis for incidents. This tool wraps its API.

    Configuration:
        Set AUTORCA_URL environment variable to the AutoRCA-Core endpoint.

    TODO (Phase 2):
        - Implement real HTTP client calls to AutoRCA-Core
        - Add authentication support
        - Support streaming results
    """

    def __init__(self, config: Optional[ToolConfig] = None) -> None:
        super().__init__(config)
        self.base_url = os.getenv("AUTORCA_URL", "http://localhost:8080")

    @property
    def tool_id(self) -> str:
        return "autoRCA"

    @property
    def description(self) -> str:
        return "Run root cause analysis using AutoRCA-Core"

    @property
    def param_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "incident_id": {
                    "type": "string",
                    "description": "Incident identifier"
                },
                "symptoms": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of observed symptoms"
                },
                "context": {
                    "type": "object",
                    "description": "Additional context for RCA"
                },
            },
        }

    async def execute(
        self,
        params: dict[str, Any],
        context: Optional[dict[str, Any]] = None,
    ) -> ToolResult:
        """Run root cause analysis."""
        if not self.config.enabled:
            return ToolResult.success(
                outputs={
                    "status": "disabled",
                    "message": "AutoRCA integration is disabled. "
                              "Set AUTORCA_URL and enable the tool to use.",
                },
                raw_output="AutoRCA tool is disabled.",
            )

        # Extract symptoms from context if not provided
        symptoms = params.get("symptoms", [])
        if not symptoms and context:
            for node_id, outputs in context.items():
                if "findings" in outputs:
                    for finding in outputs["findings"]:
                        symptoms.append(finding.get("description", ""))

        # TODO: Implement real AutoRCA-Core API call
        # For now, return a mock response

        mock_result = self._generate_mock_rca(symptoms)

        return ToolResult.success(
            outputs=mock_result,
            raw_output=self._format_rca_result(mock_result),
        )

    def _generate_mock_rca(self, symptoms: list[str]) -> dict[str, Any]:
        """Generate a mock RCA result for testing."""
        return {
            "status": "completed",
            "root_cause": {
                "category": "resource_exhaustion",
                "description": "Database connection pool exhausted due to connection leak",
                "confidence": 0.85,
            },
            "contributing_factors": [
                {
                    "factor": "Recent deployment",
                    "description": "New code may have introduced connection leak",
                    "confidence": 0.7,
                },
                {
                    "factor": "Increased traffic",
                    "description": "Traffic spike increased connection demand",
                    "confidence": 0.6,
                },
            ],
            "symptoms_analyzed": symptoms[:5] if symptoms else ["No symptoms provided"],
            "recommendations": [
                "Restart the affected service to clear stale connections",
                "Review recent code changes for connection handling",
                "Increase connection pool size as temporary mitigation",
                "Add connection timeout configuration",
            ],
        }

    def _format_rca_result(self, result: dict[str, Any]) -> str:
        """Format RCA result for human reading."""
        lines = [
            "Root Cause Analysis Results",
            "=" * 40,
            "",
            f"Status: {result['status']}",
            "",
            "Root Cause:",
            f"  Category: {result['root_cause']['category']}",
            f"  Description: {result['root_cause']['description']}",
            f"  Confidence: {result['root_cause']['confidence']:.0%}",
            "",
            "Contributing Factors:",
        ]

        for factor in result.get("contributing_factors", []):
            lines.append(f"  - {factor['factor']} ({factor['confidence']:.0%})")
            lines.append(f"    {factor['description']}")

        lines.append("")
        lines.append("Recommendations:")
        for rec in result.get("recommendations", []):
            lines.append(f"  - {rec}")

        return "\n".join(lines)


class MCPTool(Tool):
    """
    Integration with Secure-MCP-Gateway for secure tool execution.

    Secure-MCP-Gateway provides a secure way to execute tools like
    Jira, Slack, PagerDuty, etc. through the Model Context Protocol.

    Configuration:
        Set MCP_GATEWAY_URL environment variable to the gateway endpoint.
        Set MCP_API_KEY for authentication.

    Usage:
        The tool parameter in workflow nodes should be in format:
        "secureMCP:<server>:<action>" e.g., "secureMCP:jira:create_issue"

    TODO (Phase 2):
        - Implement real MCP protocol client
        - Add server discovery
        - Support tool schemas from MCP
    """

    def __init__(self, config: Optional[ToolConfig] = None) -> None:
        super().__init__(config)
        self.gateway_url = os.getenv("MCP_GATEWAY_URL", "http://localhost:3000")
        self.api_key = os.getenv("MCP_API_KEY", "")

    @property
    def tool_id(self) -> str:
        return "secureMCP"

    @property
    def description(self) -> str:
        return "Execute tools via Secure-MCP-Gateway (Jira, Slack, PagerDuty, etc.)"

    @property
    def param_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "server": {
                    "type": "string",
                    "description": "MCP server name (e.g., 'jira', 'slack')"
                },
                "action": {
                    "type": "string",
                    "description": "Action to execute (e.g., 'create_issue')"
                },
                "arguments": {
                    "type": "object",
                    "description": "Action-specific arguments"
                },
            },
            "required": ["server", "action"],
        }

    async def execute(
        self,
        params: dict[str, Any],
        context: Optional[dict[str, Any]] = None,
    ) -> ToolResult:
        """Execute an action via MCP Gateway."""
        if not self.config.enabled:
            return ToolResult.success(
                outputs={
                    "status": "disabled",
                    "message": "MCP Gateway integration is disabled. "
                              "Set MCP_GATEWAY_URL and enable the tool to use.",
                },
                raw_output="MCP tool is disabled.",
            )

        server = params.get("server", "unknown")
        action = params.get("action", "unknown")
        arguments = params.get("arguments", {})

        # TODO: Implement real MCP Gateway API call
        # For now, return a mock response based on the server type

        if server == "jira":
            result = self._mock_jira_action(action, arguments)
        elif server == "slack":
            result = self._mock_slack_action(action, arguments)
        elif server == "pagerduty":
            result = self._mock_pagerduty_action(action, arguments)
        else:
            result = {
                "status": "mock",
                "server": server,
                "action": action,
                "message": f"Mock execution of {server}:{action}",
            }

        return ToolResult.success(
            outputs=result,
            raw_output=f"Executed {server}:{action} via MCP Gateway",
        )

    def _mock_jira_action(
        self,
        action: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Generate mock Jira action result."""
        if action == "create_issue":
            return {
                "status": "success",
                "issue_key": "INC-12345",
                "issue_url": "https://jira.example.com/browse/INC-12345",
                "summary": arguments.get("summary", "Issue created via AutoOps"),
            }
        elif action == "update_issue":
            return {
                "status": "success",
                "issue_key": arguments.get("issue_key", "INC-12345"),
                "updated_fields": list(arguments.keys()),
            }
        return {"status": "mock", "action": action}

    def _mock_slack_action(
        self,
        action: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Generate mock Slack action result."""
        if action == "send_message":
            return {
                "status": "success",
                "channel": arguments.get("channel", "#alerts"),
                "message_ts": "1234567890.123456",
            }
        return {"status": "mock", "action": action}

    def _mock_pagerduty_action(
        self,
        action: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Generate mock PagerDuty action result."""
        if action == "create_incident":
            return {
                "status": "success",
                "incident_id": "PD-67890",
                "urgency": arguments.get("urgency", "high"),
            }
        elif action == "acknowledge":
            return {
                "status": "success",
                "incident_id": arguments.get("incident_id"),
                "acknowledged": True,
            }
        return {"status": "mock", "action": action}


class BrowserMissionTool(Tool):
    """
    Integration with Ops-Agent-Desktop for browser-based missions.

    Ops-Agent-Desktop is a separate application that can execute
    browser automation "missions" - scripted interactions with web UIs.

    Configuration:
        Set OPS_AGENT_DESKTOP_URL environment variable.

    TODO (Phase 2):
        - Implement mission file format
        - Add screenshot capture
        - Support mission templates
    """

    def __init__(self, config: Optional[ToolConfig] = None) -> None:
        super().__init__(config)
        self.agent_url = os.getenv("OPS_AGENT_DESKTOP_URL", "http://localhost:9090")

    @property
    def tool_id(self) -> str:
        return "browser"

    @property
    def description(self) -> str:
        return "Execute browser-based missions via Ops-Agent-Desktop"

    @property
    def param_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "mission_file": {
                    "type": "string",
                    "description": "Path to mission definition file"
                },
                "mission_type": {
                    "type": "string",
                    "enum": ["health_check", "ui_test", "data_extraction", "custom"],
                    "description": "Type of browser mission"
                },
                "target_url": {
                    "type": "string",
                    "description": "Target URL for the mission"
                },
                "parameters": {
                    "type": "object",
                    "description": "Mission-specific parameters"
                },
            },
        }

    async def execute(
        self,
        params: dict[str, Any],
        context: Optional[dict[str, Any]] = None,
    ) -> ToolResult:
        """Execute a browser mission."""
        if not self.config.enabled:
            return ToolResult.success(
                outputs={
                    "status": "disabled",
                    "message": "Ops-Agent-Desktop integration is disabled. "
                              "Set OPS_AGENT_DESKTOP_URL and enable the tool to use.",
                },
                raw_output="Browser mission tool is disabled.",
            )

        mission_type = params.get("mission_type", "health_check")
        target_url = params.get("target_url", "")
        mission_params = params.get("parameters", {})

        # TODO: Implement real Ops-Agent-Desktop API call
        # For now, return a mock response

        result = self._mock_mission_result(mission_type, target_url, mission_params)

        return ToolResult.success(
            outputs=result,
            raw_output=self._format_mission_result(result),
        )

    def _mock_mission_result(
        self,
        mission_type: str,
        target_url: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Generate a mock mission result."""
        return {
            "status": "completed",
            "mission_type": mission_type,
            "target_url": target_url or "https://example.com",
            "duration_ms": 2500,
            "steps_completed": 5,
            "steps_total": 5,
            "findings": [
                {
                    "type": "observation",
                    "description": "Page loaded successfully",
                    "screenshot": None,  # Would be path in real implementation
                },
                {
                    "type": "check",
                    "description": "All expected elements present",
                    "passed": True,
                },
            ],
            "artifacts": [],
        }

    def _format_mission_result(self, result: dict[str, Any]) -> str:
        """Format mission result for human reading."""
        lines = [
            "Browser Mission Result",
            "=" * 40,
            f"Type: {result['mission_type']}",
            f"URL: {result['target_url']}",
            f"Status: {result['status']}",
            f"Duration: {result['duration_ms']}ms",
            f"Steps: {result['steps_completed']}/{result['steps_total']}",
            "",
            "Findings:",
        ]

        for finding in result.get("findings", []):
            status = "PASS" if finding.get("passed", True) else "FAIL"
            lines.append(f"  [{status}] {finding['description']}")

        return "\n".join(lines)
