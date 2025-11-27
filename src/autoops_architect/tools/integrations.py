"""Integration tools for connecting to external systems.

These tools provide integration with:
- AutoRCA-Core: Root cause analysis
- Secure-MCP-Gateway: Secure tool execution via MCP
- Ops-Agent-Desktop: Browser-based mission execution
"""

import asyncio
import json
import os
from typing import Any, Optional

import httpx

from autoops_architect.tools.base import Tool, ToolConfig, ToolResult


class AutoRCATool(Tool):
    """
    Integration with AutoRCA-Core for root cause analysis.

    AutoRCA-Core is a separate repository that provides AI-powered
    root cause analysis for incidents. This tool wraps its API.

    Configuration:
        Set AUTORCA_URL environment variable to the AutoRCA-Core endpoint.
        Set AUTORCA_API_KEY for authentication (optional).

    Example:
        >>> tool = AutoRCATool()
        >>> result = await tool.execute({
        ...     "symptoms": ["High 5xx error rate", "Database connection errors"],
        ...     "context": {"service": "checkout-api", "timeframe": "1h"}
        ... })
    """

    def __init__(self, config: Optional[ToolConfig] = None) -> None:
        super().__init__(config)
        self.base_url = os.getenv("AUTORCA_URL", "http://localhost:8080")
        self.api_key = os.getenv("AUTORCA_API_KEY", "")
        self.timeout = float(os.getenv("AUTORCA_TIMEOUT", "60"))

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
                "mode": {
                    "type": "string",
                    "enum": ["quick", "thorough", "interactive"],
                    "description": "Analysis mode (default: quick)"
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
                if isinstance(outputs, dict) and "findings" in outputs:
                    for finding in outputs["findings"]:
                        if isinstance(finding, dict):
                            symptoms.append(finding.get("description", ""))

        # Build request payload
        payload = {
            "incident_id": params.get("incident_id"),
            "symptoms": symptoms,
            "context": params.get("context", {}),
            "mode": params.get("mode", "quick"),
        }

        # Add any relevant context from previous nodes
        if context:
            payload["workflow_context"] = self._extract_relevant_context(context)

        # Try to call real AutoRCA-Core API
        try:
            result = await self._call_autorca_api(payload)
            return ToolResult.success(
                outputs=result,
                raw_output=self._format_rca_result(result),
            )
        except httpx.ConnectError:
            # Fall back to mock if AutoRCA is not available
            mock_result = self._generate_mock_rca(symptoms)
            mock_result["_mock"] = True
            mock_result["_message"] = f"AutoRCA-Core not reachable at {self.base_url}"
            return ToolResult.success(
                outputs=mock_result,
                raw_output=self._format_rca_result(mock_result),
            )
        except Exception as e:
            return ToolResult.error(
                error_message=f"AutoRCA API error: {str(e)}",
                raw_output=str(e),
            )

    async def _call_autorca_api(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Call the AutoRCA-Core API."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/analyze",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            return response.json()

    def _extract_relevant_context(self, context: dict[str, Any]) -> dict[str, Any]:
        """Extract relevant information from workflow context."""
        relevant = {}
        for node_id, outputs in context.items():
            if isinstance(outputs, dict):
                # Include log findings
                if "findings" in outputs:
                    relevant[f"{node_id}_findings"] = outputs["findings"]
                # Include metrics
                if "metrics" in outputs:
                    relevant[f"{node_id}_metrics"] = outputs["metrics"]
                # Include errors
                if "errors" in outputs:
                    relevant[f"{node_id}_errors"] = outputs["errors"]
        return relevant

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
        ]

        if result.get("_mock"):
            lines.append(f"[MOCK MODE] {result.get('_message', '')}")

        lines.extend([
            "",
            "Root Cause:",
            f"  Category: {result['root_cause']['category']}",
            f"  Description: {result['root_cause']['description']}",
            f"  Confidence: {result['root_cause']['confidence']:.0%}",
            "",
            "Contributing Factors:",
        ])

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
        The tool parameter in workflow nodes should specify:
        - server: The MCP server name (e.g., "jira", "slack")
        - action: The action to execute (e.g., "create_issue")
        - arguments: Action-specific parameters

    Example:
        >>> tool = MCPTool()
        >>> result = await tool.execute({
        ...     "server": "jira",
        ...     "action": "create_issue",
        ...     "arguments": {"summary": "Critical incident", "priority": "High"}
        ... })
    """

    def __init__(self, config: Optional[ToolConfig] = None) -> None:
        super().__init__(config)
        self.gateway_url = os.getenv("MCP_GATEWAY_URL", "http://localhost:3000")
        self.api_key = os.getenv("MCP_API_KEY", "")
        self.timeout = float(os.getenv("MCP_TIMEOUT", "30"))

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
                    "description": "MCP server name (e.g., 'jira', 'slack', 'pagerduty')"
                },
                "action": {
                    "type": "string",
                    "description": "Action to execute (e.g., 'create_issue', 'send_message')"
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

        # Enrich arguments with context if available
        if context:
            arguments = self._enrich_arguments(action, arguments, context)

        # Try to call real MCP Gateway
        try:
            result = await self._call_mcp_gateway(server, action, arguments)
            return ToolResult.success(
                outputs=result,
                raw_output=f"Executed {server}:{action} via MCP Gateway",
            )
        except httpx.ConnectError:
            # Fall back to mock if gateway is not available
            result = self._generate_mock_response(server, action, arguments)
            result["_mock"] = True
            result["_message"] = f"MCP Gateway not reachable at {self.gateway_url}"
            return ToolResult.success(
                outputs=result,
                raw_output=f"[MOCK] Executed {server}:{action}",
            )
        except Exception as e:
            return ToolResult.error(
                error_message=f"MCP Gateway error: {str(e)}",
                raw_output=str(e),
            )

    async def _call_mcp_gateway(
        self,
        server: str,
        action: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Call the MCP Gateway API."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        # MCP protocol format
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": f"{server}_{action}",
                "arguments": arguments,
            },
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.gateway_url}/servers/{server}/call",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()

            # Handle MCP protocol response
            if "error" in result:
                raise Exception(result["error"].get("message", "Unknown MCP error"))

            return result.get("result", result)

    def _enrich_arguments(
        self,
        action: str,
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Enrich arguments with relevant context."""
        enriched = dict(arguments)

        # If creating a ticket/issue, add summary from context
        if action in ("create_issue", "create_ticket") and "summary" not in enriched:
            # Look for RCA results or findings
            for node_id, outputs in context.items():
                if isinstance(outputs, dict):
                    if "root_cause" in outputs:
                        enriched["summary"] = outputs["root_cause"].get(
                            "description", "Incident from AutoOps"
                        )
                        break
                    if "findings" in outputs and outputs["findings"]:
                        enriched["summary"] = f"Investigation: {outputs['findings'][0]}"
                        break

        # If sending a message, format context as message
        if action == "send_message" and "message" not in enriched:
            enriched["message"] = self._format_context_message(context)

        return enriched

    def _format_context_message(self, context: dict[str, Any]) -> str:
        """Format workflow context as a notification message."""
        lines = ["AutoOps Workflow Update", ""]

        for node_id, outputs in context.items():
            if isinstance(outputs, dict):
                if "summary" in outputs:
                    lines.append(f"- {outputs['summary']}")
                elif "root_cause" in outputs:
                    lines.append(
                        f"- RCA: {outputs['root_cause'].get('description', 'N/A')}"
                    )

        return "\n".join(lines) if len(lines) > 2 else "Workflow completed"

    def _generate_mock_response(
        self,
        server: str,
        action: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Generate a mock response based on server and action."""
        if server == "jira":
            return self._mock_jira_action(action, arguments)
        elif server == "slack":
            return self._mock_slack_action(action, arguments)
        elif server == "pagerduty":
            return self._mock_pagerduty_action(action, arguments)
        elif server == "github":
            return self._mock_github_action(action, arguments)
        elif server == "opsgenie":
            return self._mock_opsgenie_action(action, arguments)
        else:
            return {
                "status": "mock",
                "server": server,
                "action": action,
                "message": f"Mock execution of {server}:{action}",
            }

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
        elif action == "add_comment":
            return {
                "status": "success",
                "issue_key": arguments.get("issue_key", "INC-12345"),
                "comment_id": "10001",
            }
        elif action == "transition":
            return {
                "status": "success",
                "issue_key": arguments.get("issue_key", "INC-12345"),
                "new_status": arguments.get("status", "In Progress"),
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
        elif action == "create_channel":
            return {
                "status": "success",
                "channel_id": "C12345",
                "channel_name": arguments.get("name", "incident-12345"),
            }
        elif action == "invite_users":
            return {
                "status": "success",
                "channel": arguments.get("channel"),
                "users_invited": arguments.get("users", []),
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
                "incident_url": "https://pagerduty.com/incidents/PD-67890",
            }
        elif action == "acknowledge":
            return {
                "status": "success",
                "incident_id": arguments.get("incident_id"),
                "acknowledged": True,
            }
        elif action == "resolve":
            return {
                "status": "success",
                "incident_id": arguments.get("incident_id"),
                "resolved": True,
            }
        elif action == "escalate":
            return {
                "status": "success",
                "incident_id": arguments.get("incident_id"),
                "escalation_policy": arguments.get("policy", "default"),
            }
        return {"status": "mock", "action": action}

    def _mock_github_action(
        self,
        action: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Generate mock GitHub action result."""
        if action == "create_issue":
            return {
                "status": "success",
                "issue_number": 42,
                "issue_url": "https://github.com/org/repo/issues/42",
            }
        elif action == "create_pr":
            return {
                "status": "success",
                "pr_number": 123,
                "pr_url": "https://github.com/org/repo/pull/123",
            }
        elif action == "get_workflow_runs":
            return {
                "status": "success",
                "runs": [
                    {"id": 1, "status": "completed", "conclusion": "success"},
                ],
            }
        return {"status": "mock", "action": action}

    def _mock_opsgenie_action(
        self,
        action: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Generate mock OpsGenie action result."""
        if action == "create_alert":
            return {
                "status": "success",
                "alert_id": "og-alert-12345",
                "alias": arguments.get("alias"),
            }
        elif action == "acknowledge_alert":
            return {
                "status": "success",
                "alert_id": arguments.get("alert_id"),
                "acknowledged": True,
            }
        elif action == "close_alert":
            return {
                "status": "success",
                "alert_id": arguments.get("alert_id"),
                "closed": True,
            }
        return {"status": "mock", "action": action}


class BrowserMissionTool(Tool):
    """
    Integration with Ops-Agent-Desktop for browser-based missions.

    Ops-Agent-Desktop is a separate application that can execute
    browser automation "missions" - scripted interactions with web UIs.

    Configuration:
        Set OPS_AGENT_DESKTOP_URL environment variable.
        Set OPS_AGENT_API_KEY for authentication (optional).

    Example:
        >>> tool = BrowserMissionTool()
        >>> result = await tool.execute({
        ...     "mission_type": "health_check",
        ...     "target_url": "https://dashboard.example.com",
        ...     "parameters": {"check_elements": [".status-badge", "#health-panel"]}
        ... })
    """

    def __init__(self, config: Optional[ToolConfig] = None) -> None:
        super().__init__(config)
        self.agent_url = os.getenv("OPS_AGENT_DESKTOP_URL", "http://localhost:9090")
        self.api_key = os.getenv("OPS_AGENT_API_KEY", "")
        self.timeout = float(os.getenv("OPS_AGENT_TIMEOUT", "120"))

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
                    "enum": ["health_check", "ui_test", "data_extraction", "session_replay", "custom"],
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
                "timeout": {
                    "type": "integer",
                    "description": "Mission timeout in seconds"
                },
                "capture_screenshots": {
                    "type": "boolean",
                    "description": "Whether to capture screenshots during mission"
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
        mission_file = params.get("mission_file")
        mission_params = params.get("parameters", {})
        timeout = params.get("timeout", 60)
        capture_screenshots = params.get("capture_screenshots", True)

        # Try to call real Ops-Agent-Desktop API
        try:
            result = await self._execute_mission(
                mission_type=mission_type,
                target_url=target_url,
                mission_file=mission_file,
                parameters=mission_params,
                timeout=timeout,
                capture_screenshots=capture_screenshots,
            )
            return ToolResult.success(
                outputs=result,
                raw_output=self._format_mission_result(result),
            )
        except httpx.ConnectError:
            # Fall back to mock if agent is not available
            result = self._mock_mission_result(mission_type, target_url, mission_params)
            result["_mock"] = True
            result["_message"] = f"Ops-Agent-Desktop not reachable at {self.agent_url}"
            return ToolResult.success(
                outputs=result,
                raw_output=self._format_mission_result(result),
            )
        except Exception as e:
            return ToolResult.error(
                error_message=f"Browser mission error: {str(e)}",
                raw_output=str(e),
            )

    async def _execute_mission(
        self,
        mission_type: str,
        target_url: str,
        mission_file: Optional[str],
        parameters: dict[str, Any],
        timeout: int,
        capture_screenshots: bool,
    ) -> dict[str, Any]:
        """Execute a mission via Ops-Agent-Desktop API."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "mission_type": mission_type,
            "target_url": target_url,
            "parameters": parameters,
            "timeout": timeout,
            "capture_screenshots": capture_screenshots,
        }

        if mission_file:
            payload["mission_file"] = mission_file

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            # Start the mission
            response = await client.post(
                f"{self.agent_url}/api/v1/missions/execute",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            mission = response.json()
            mission_id = mission.get("mission_id")

            # Poll for completion
            while True:
                status_response = await client.get(
                    f"{self.agent_url}/api/v1/missions/{mission_id}/status",
                    headers=headers,
                )
                status_response.raise_for_status()
                status = status_response.json()

                if status.get("status") in ("completed", "failed", "timeout"):
                    return status

                await asyncio.sleep(1)

    def _mock_mission_result(
        self,
        mission_type: str,
        target_url: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Generate a mock mission result."""
        findings = []

        if mission_type == "health_check":
            findings = [
                {
                    "type": "observation",
                    "description": "Page loaded successfully",
                    "screenshot": None,
                },
                {
                    "type": "check",
                    "description": "All expected elements present",
                    "passed": True,
                },
                {
                    "type": "metric",
                    "description": "Page load time",
                    "value": 1.23,
                    "unit": "seconds",
                },
            ]
        elif mission_type == "data_extraction":
            findings = [
                {
                    "type": "extraction",
                    "description": "Extracted dashboard data",
                    "data": params.get("selectors", {}),
                },
            ]
        elif mission_type == "session_replay":
            findings = [
                {
                    "type": "replay",
                    "description": "Session replay completed",
                    "steps_replayed": 10,
                    "errors_found": 0,
                },
            ]

        return {
            "status": "completed",
            "mission_type": mission_type,
            "target_url": target_url or "https://example.com",
            "duration_ms": 2500,
            "steps_completed": len(findings),
            "steps_total": len(findings),
            "findings": findings,
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
        ]

        if result.get("_mock"):
            lines.append(f"[MOCK MODE] {result.get('_message', '')}")

        lines.append("")
        lines.append("Findings:")

        for finding in result.get("findings", []):
            passed = finding.get("passed", True)
            status = "PASS" if passed else "FAIL"
            lines.append(f"  [{status}] {finding['description']}")

            # Include metrics if present
            if "value" in finding:
                lines.append(f"         Value: {finding['value']} {finding.get('unit', '')}")

        if result.get("artifacts"):
            lines.append("")
            lines.append("Artifacts:")
            for artifact in result["artifacts"]:
                lines.append(f"  - {artifact}")

        return "\n".join(lines)


class DatadogTool(Tool):
    """
    Integration with Datadog for metrics and monitoring data.

    Configuration:
        Set DATADOG_API_KEY and DATADOG_APP_KEY environment variables.
        Set DATADOG_SITE for regional endpoints (default: datadoghq.com).

    Example:
        >>> tool = DatadogTool()
        >>> result = await tool.execute({
        ...     "action": "query_metrics",
        ...     "query": "avg:system.cpu.user{service:checkout-api}",
        ...     "timeframe": "1h"
        ... })
    """

    def __init__(self, config: Optional[ToolConfig] = None) -> None:
        super().__init__(config)
        self.api_key = os.getenv("DATADOG_API_KEY", "")
        self.app_key = os.getenv("DATADOG_APP_KEY", "")
        self.site = os.getenv("DATADOG_SITE", "datadoghq.com")
        self.timeout = float(os.getenv("DATADOG_TIMEOUT", "30"))

    @property
    def tool_id(self) -> str:
        return "datadog"

    @property
    def description(self) -> str:
        return "Query metrics and logs from Datadog"

    @property
    def param_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["query_metrics", "query_logs", "list_monitors", "get_events"],
                    "description": "Action to perform"
                },
                "query": {
                    "type": "string",
                    "description": "Query string (metric query or log query)"
                },
                "timeframe": {
                    "type": "string",
                    "description": "Time window (e.g., '1h', '6h', '1d')"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results"
                },
            },
            "required": ["action"],
        }

    async def execute(
        self,
        params: dict[str, Any],
        context: Optional[dict[str, Any]] = None,
    ) -> ToolResult:
        """Execute a Datadog query."""
        if not self.config.enabled:
            return ToolResult.success(
                outputs={"status": "disabled", "message": "Datadog integration is disabled"},
                raw_output="Datadog tool is disabled.",
            )

        action = params.get("action", "query_metrics")
        query = params.get("query", "")
        timeframe = params.get("timeframe", "1h")

        if not self.api_key or not self.app_key:
            # Return mock data
            result = self._generate_mock_result(action, query, timeframe)
            result["_mock"] = True
            result["_message"] = "DATADOG_API_KEY or DATADOG_APP_KEY not set"
            return ToolResult.success(
                outputs=result,
                raw_output=json.dumps(result, indent=2),
            )

        try:
            result = await self._call_datadog_api(action, query, timeframe, params)
            return ToolResult.success(
                outputs=result,
                raw_output=json.dumps(result, indent=2),
            )
        except Exception as e:
            return ToolResult.error(
                error_message=f"Datadog API error: {str(e)}",
                raw_output=str(e),
            )

    async def _call_datadog_api(
        self,
        action: str,
        query: str,
        timeframe: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Call Datadog API."""
        headers = {
            "DD-API-KEY": self.api_key,
            "DD-APPLICATION-KEY": self.app_key,
            "Content-Type": "application/json",
        }

        base_url = f"https://api.{self.site}"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            if action == "query_metrics":
                # Convert timeframe to timestamps
                now = int(asyncio.get_event_loop().time())
                hours = int(timeframe.rstrip("h"))
                from_ts = now - (hours * 3600)

                response = await client.get(
                    f"{base_url}/api/v1/query",
                    params={"query": query, "from": from_ts, "to": now},
                    headers=headers,
                )
            elif action == "query_logs":
                response = await client.post(
                    f"{base_url}/api/v2/logs/events/search",
                    json={
                        "filter": {"query": query, "from": f"now-{timeframe}", "to": "now"},
                        "page": {"limit": params.get("limit", 50)},
                    },
                    headers=headers,
                )
            elif action == "list_monitors":
                response = await client.get(
                    f"{base_url}/api/v1/monitor",
                    headers=headers,
                )
            else:
                response = await client.get(
                    f"{base_url}/api/v1/events",
                    params={"start": "now-1h", "end": "now"},
                    headers=headers,
                )

            response.raise_for_status()
            return response.json()

    def _generate_mock_result(
        self,
        action: str,
        query: str,
        timeframe: str,
    ) -> dict[str, Any]:
        """Generate mock Datadog results."""
        if action == "query_metrics":
            return {
                "status": "ok",
                "series": [
                    {
                        "metric": query.split("{")[0] if "{" in query else query,
                        "points": [[1700000000, 45.2], [1700000060, 47.8], [1700000120, 42.1]],
                        "tags": ["service:mock"],
                    }
                ],
            }
        elif action == "query_logs":
            return {
                "data": [
                    {"message": "Mock log entry 1", "timestamp": "2024-01-01T00:00:00Z"},
                    {"message": "Mock log entry 2", "timestamp": "2024-01-01T00:01:00Z"},
                ],
            }
        return {"status": "mock", "action": action}
