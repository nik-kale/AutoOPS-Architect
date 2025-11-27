"""Built-in tools for AutoOps Architect."""

import json
import random
from datetime import datetime, timedelta
from typing import Any, Optional

from autoops_architect.tools.base import Tool, ToolConfig, ToolResult


class EchoTool(Tool):
    """
    Simple echo tool for testing and debugging.

    Echoes back the input parameters as output. Useful for testing
    workflow execution without side effects.
    """

    @property
    def tool_id(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echo tool that returns input parameters as output (for testing)"

    @property
    def param_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Message to echo"
                },
            },
        }

    async def execute(
        self,
        params: dict[str, Any],
        context: Optional[dict[str, Any]] = None,
    ) -> ToolResult:
        """Echo the input parameters."""
        message = params.get("message", "No message provided")

        return ToolResult.success(
            outputs={
                "echoed_params": params,
                "context_received": bool(context),
                "timestamp": datetime.utcnow().isoformat(),
            },
            raw_output=f"Echo: {message}",
        )


class LogCollectorTool(Tool):
    """
    Log collector tool for gathering logs from services.

    In production, this would integrate with log aggregation systems
    like Elasticsearch, Loki, CloudWatch, etc. For now, it returns
    simulated log data.
    """

    @property
    def tool_id(self) -> str:
        return "log_collector"

    @property
    def description(self) -> str:
        return "Collect logs from services and systems"

    @property
    def param_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "Service name to collect logs from"
                },
                "duration": {
                    "type": "string",
                    "description": "Time duration (e.g., '1h', '30m', '24h')"
                },
                "level": {
                    "type": "string",
                    "enum": ["debug", "info", "warn", "error"],
                    "description": "Minimum log level to collect"
                },
                "query": {
                    "type": "string",
                    "description": "Optional search query"
                },
            },
            "required": ["service"],
        }

    async def execute(
        self,
        params: dict[str, Any],
        context: Optional[dict[str, Any]] = None,
    ) -> ToolResult:
        """Collect logs from the specified service."""
        service = params.get("service", "unknown")
        duration = params.get("duration", "1h")
        level = params.get("level", "info")
        query = params.get("query", "")

        # Simulate log collection
        # In production, this would query actual log systems
        log_entries = self._generate_sample_logs(service, level)

        return ToolResult.success(
            outputs={
                "service": service,
                "duration": duration,
                "level": level,
                "query": query,
                "log_count": len(log_entries),
                "error_count": sum(1 for l in log_entries if l["level"] == "error"),
                "warn_count": sum(1 for l in log_entries if l["level"] == "warn"),
                "logs": log_entries[:10],  # Return first 10 for display
            },
            raw_output=self._format_logs(log_entries),
        )

    def _generate_sample_logs(
        self,
        service: str,
        min_level: str,
    ) -> list[dict[str, Any]]:
        """Generate sample log entries for testing."""
        levels = ["debug", "info", "warn", "error"]
        level_idx = levels.index(min_level) if min_level in levels else 1

        messages = [
            ("info", f"Request processed successfully for {service}"),
            ("info", "Health check passed"),
            ("warn", "Slow database query detected (>500ms)"),
            ("error", "Connection refused to downstream service"),
            ("error", "HTTP 503 Service Unavailable"),
            ("warn", "Memory usage above 80% threshold"),
            ("info", "Cache miss for key user_preferences"),
            ("error", "Failed to parse JSON request body"),
            ("info", "Successfully connected to database pool"),
            ("warn", "Rate limit approaching for API endpoint"),
        ]

        entries = []
        base_time = datetime.utcnow()

        for i in range(50):
            level, msg = random.choice(messages)
            if levels.index(level) >= level_idx:
                entries.append({
                    "timestamp": (base_time - timedelta(minutes=i)).isoformat(),
                    "level": level,
                    "service": service,
                    "message": msg,
                    "trace_id": f"trace-{random.randint(1000, 9999)}",
                })

        return entries

    def _format_logs(self, logs: list[dict[str, Any]]) -> str:
        """Format logs for raw output."""
        lines = []
        for log in logs[:20]:  # Limit output
            lines.append(
                f"[{log['timestamp']}] [{log['level'].upper()}] "
                f"{log['service']}: {log['message']}"
            )
        return "\n".join(lines)


class MetricQueryTool(Tool):
    """
    Metric query tool for retrieving metrics from monitoring systems.

    In production, this would integrate with Prometheus, Datadog,
    CloudWatch, etc. For now, it returns simulated metric data.
    """

    @property
    def tool_id(self) -> str:
        return "metric_query"

    @property
    def description(self) -> str:
        return "Query metrics from monitoring systems"

    @property
    def param_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Metric query (e.g., PromQL)"
                },
                "service": {
                    "type": "string",
                    "description": "Service to query metrics for"
                },
                "metric_name": {
                    "type": "string",
                    "description": "Metric name (e.g., 'http_requests_total')"
                },
                "duration": {
                    "type": "string",
                    "description": "Time range (e.g., '1h', '6h', '24h')"
                },
            },
        }

    async def execute(
        self,
        params: dict[str, Any],
        context: Optional[dict[str, Any]] = None,
    ) -> ToolResult:
        """Query metrics from monitoring system."""
        service = params.get("service", "unknown")
        metric_name = params.get("metric_name", "http_requests_total")
        duration = params.get("duration", "1h")

        # Simulate metric data
        metrics = self._generate_sample_metrics(service, metric_name)

        return ToolResult.success(
            outputs={
                "service": service,
                "metric_name": metric_name,
                "duration": duration,
                "data_points": len(metrics["values"]),
                "current_value": metrics["values"][-1] if metrics["values"] else 0,
                "avg_value": sum(metrics["values"]) / len(metrics["values"]) if metrics["values"] else 0,
                "max_value": max(metrics["values"]) if metrics["values"] else 0,
                "min_value": min(metrics["values"]) if metrics["values"] else 0,
                "metrics": metrics,
            },
            raw_output=f"Metric: {metric_name} for {service}\n"
                      f"Current: {metrics['values'][-1] if metrics['values'] else 'N/A'}\n"
                      f"Points: {len(metrics['values'])}",
        )

    def _generate_sample_metrics(
        self,
        service: str,
        metric_name: str,
    ) -> dict[str, Any]:
        """Generate sample metric data."""
        base_value = random.uniform(50, 200)
        timestamps = []
        values = []

        base_time = datetime.utcnow()

        for i in range(60):  # 60 data points
            timestamps.append((base_time - timedelta(minutes=i)).isoformat())
            # Add some variation
            value = base_value + random.uniform(-20, 20)
            # Occasionally add a spike
            if random.random() < 0.1:
                value *= 2
            values.append(round(value, 2))

        return {
            "metric": metric_name,
            "service": service,
            "timestamps": timestamps,
            "values": values,
        }


class TraceCollectorTool(Tool):
    """
    Trace collector tool for gathering distributed traces.

    Collects distributed traces from tracing systems like Jaeger,
    Zipkin, AWS X-Ray, or Datadog APM. Useful for understanding
    request flow and identifying latency issues.

    In production, this would integrate with actual tracing backends.
    For now, it returns simulated trace data.
    """

    @property
    def tool_id(self) -> str:
        return "trace_collector"

    @property
    def description(self) -> str:
        return "Collect distributed traces from services"

    @property
    def param_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "Service name to collect traces from"
                },
                "trace_id": {
                    "type": "string",
                    "description": "Specific trace ID to retrieve"
                },
                "duration": {
                    "type": "string",
                    "description": "Time duration (e.g., '1h', '30m', '24h')"
                },
                "operation": {
                    "type": "string",
                    "description": "Filter by operation name"
                },
                "min_duration_ms": {
                    "type": "integer",
                    "description": "Minimum span duration to include (ms)"
                },
                "error_only": {
                    "type": "boolean",
                    "description": "Only return traces with errors"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of traces to return"
                },
            },
            "required": ["service"],
        }

    async def execute(
        self,
        params: dict[str, Any],
        context: Optional[dict[str, Any]] = None,
    ) -> ToolResult:
        """Collect traces from the specified service."""
        service = params.get("service", "unknown")
        duration = params.get("duration", "1h")
        operation = params.get("operation")
        min_duration_ms = params.get("min_duration_ms", 0)
        error_only = params.get("error_only", False)
        limit = params.get("limit", 20)
        trace_id = params.get("trace_id")

        # If a specific trace ID is requested, return detailed trace
        if trace_id:
            trace = self._generate_detailed_trace(trace_id, service)
            return ToolResult.success(
                outputs={
                    "trace_id": trace_id,
                    "service": service,
                    "trace": trace,
                    "span_count": len(trace["spans"]),
                    "total_duration_ms": trace["duration_ms"],
                },
                raw_output=self._format_trace(trace),
            )

        # Otherwise, return a list of traces
        traces = self._generate_sample_traces(
            service=service,
            operation=operation,
            min_duration_ms=min_duration_ms,
            error_only=error_only,
            limit=limit,
        )

        # Compute statistics
        durations = [t["duration_ms"] for t in traces]
        error_traces = [t for t in traces if t.get("error")]

        return ToolResult.success(
            outputs={
                "service": service,
                "duration": duration,
                "trace_count": len(traces),
                "error_trace_count": len(error_traces),
                "avg_duration_ms": sum(durations) / len(durations) if durations else 0,
                "max_duration_ms": max(durations) if durations else 0,
                "min_duration_ms": min(durations) if durations else 0,
                "p95_duration_ms": self._percentile(durations, 95),
                "p99_duration_ms": self._percentile(durations, 99),
                "traces": traces[:10],  # Return first 10 for display
            },
            raw_output=self._format_traces_summary(traces, error_traces),
        )

    def _generate_sample_traces(
        self,
        service: str,
        operation: str | None,
        min_duration_ms: int,
        error_only: bool,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Generate sample trace data for testing."""
        operations = [
            "GET /api/v1/checkout",
            "POST /api/v1/orders",
            "GET /api/v1/products",
            "POST /api/v1/payment",
            "GET /api/v1/users/{id}",
            "PUT /api/v1/cart",
        ]

        traces = []
        base_time = datetime.utcnow()

        for i in range(min(limit * 2, 100)):  # Generate more than limit to filter
            op = operation if operation else random.choice(operations)
            duration_ms = random.uniform(50, 2000)
            has_error = random.random() < 0.1  # 10% error rate

            if min_duration_ms and duration_ms < min_duration_ms:
                continue
            if error_only and not has_error:
                continue

            trace = {
                "trace_id": f"trace-{random.randint(100000, 999999)}",
                "start_time": (base_time - timedelta(minutes=i)).isoformat(),
                "operation": op,
                "duration_ms": round(duration_ms, 2),
                "service": service,
                "span_count": random.randint(3, 15),
                "error": has_error,
                "status_code": 500 if has_error else 200,
                "tags": {
                    "http.method": op.split()[0] if " " in op else "GET",
                    "http.url": op.split()[1] if " " in op else op,
                },
            }

            if has_error:
                trace["error_message"] = random.choice([
                    "Connection timeout to downstream service",
                    "Database query failed",
                    "Service unavailable",
                    "Request validation failed",
                    "Circuit breaker open",
                ])

            traces.append(trace)

            if len(traces) >= limit:
                break

        return traces

    def _generate_detailed_trace(
        self,
        trace_id: str,
        service: str,
    ) -> dict[str, Any]:
        """Generate a detailed trace with spans."""
        base_time = datetime.utcnow()
        total_duration = random.uniform(200, 1500)

        spans = []
        current_offset = 0

        span_templates = [
            ("http.request", service, 0),
            ("db.query", f"{service}-db", 0.1),
            ("cache.get", f"{service}-cache", 0.05),
            ("http.client", "payment-service", 0.3),
            ("db.query", "payment-db", 0.1),
            ("http.response", service, 0.05),
        ]

        for span_name, span_service, duration_fraction in span_templates:
            span_duration = total_duration * duration_fraction
            spans.append({
                "span_id": f"span-{random.randint(10000, 99999)}",
                "operation_name": span_name,
                "service": span_service,
                "start_offset_ms": round(current_offset, 2),
                "duration_ms": round(span_duration, 2),
                "tags": {},
                "logs": [],
            })
            current_offset += span_duration * random.uniform(0.8, 1.2)

        return {
            "trace_id": trace_id,
            "start_time": base_time.isoformat(),
            "duration_ms": round(total_duration, 2),
            "root_service": service,
            "spans": spans,
            "services_involved": list(set(s["service"] for s in spans)),
        }

    def _percentile(self, values: list[float], percentile: int) -> float:
        """Calculate percentile of a list of values."""
        if not values:
            return 0.0
        sorted_values = sorted(values)
        idx = int(len(sorted_values) * percentile / 100)
        return round(sorted_values[min(idx, len(sorted_values) - 1)], 2)

    def _format_trace(self, trace: dict[str, Any]) -> str:
        """Format a detailed trace for display."""
        lines = [
            f"Trace: {trace['trace_id']}",
            "=" * 50,
            f"Root Service: {trace['root_service']}",
            f"Total Duration: {trace['duration_ms']}ms",
            f"Services Involved: {', '.join(trace['services_involved'])}",
            "",
            "Spans:",
        ]

        for span in trace["spans"]:
            lines.append(
                f"  [{span['start_offset_ms']:>7.2f}ms] "
                f"{span['service']:20s} {span['operation_name']:20s} "
                f"({span['duration_ms']:.2f}ms)"
            )

        return "\n".join(lines)

    def _format_traces_summary(
        self,
        traces: list[dict[str, Any]],
        error_traces: list[dict[str, Any]],
    ) -> str:
        """Format trace summary for display."""
        lines = [
            "Trace Collection Summary",
            "=" * 50,
            f"Total Traces: {len(traces)}",
            f"Error Traces: {len(error_traces)}",
            "",
        ]

        if traces:
            durations = [t["duration_ms"] for t in traces]
            lines.extend([
                f"Duration Stats:",
                f"  Avg: {sum(durations)/len(durations):.2f}ms",
                f"  Min: {min(durations):.2f}ms",
                f"  Max: {max(durations):.2f}ms",
                f"  P95: {self._percentile(durations, 95):.2f}ms",
                f"  P99: {self._percentile(durations, 99):.2f}ms",
            ])

        if error_traces:
            lines.extend([
                "",
                "Error Traces:",
            ])
            for trace in error_traces[:5]:
                lines.append(
                    f"  - {trace['trace_id']}: {trace.get('error_message', 'Unknown error')}"
                )

        return "\n".join(lines)


class AnalysisTool(Tool):
    """
    Analysis tool for examining collected data.

    Performs pattern analysis on logs and metrics. In production,
    this could use ML models or rule-based analysis.
    """

    @property
    def tool_id(self) -> str:
        return "log_analyzer"

    @property
    def description(self) -> str:
        return "Analyze logs and data for patterns and anomalies"

    @property
    def param_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "analysis_type": {
                    "type": "string",
                    "enum": ["error_patterns", "latency", "anomaly_detection"],
                    "description": "Type of analysis to perform"
                },
            },
        }

    async def execute(
        self,
        params: dict[str, Any],
        context: Optional[dict[str, Any]] = None,
    ) -> ToolResult:
        """Analyze data from previous steps."""
        analysis_type = params.get("analysis_type", "error_patterns")

        # Get data from context (previous node outputs)
        log_data = None
        metric_data = None

        if context:
            for node_id, outputs in context.items():
                if "logs" in outputs:
                    log_data = outputs.get("logs", [])
                if "metrics" in outputs:
                    metric_data = outputs.get("metrics")

        findings = self._analyze(log_data, metric_data, analysis_type)

        return ToolResult.success(
            outputs={
                "analysis_type": analysis_type,
                "findings": findings,
                "severity": self._compute_severity(findings),
                "recommendation": self._generate_recommendation(findings),
            },
            raw_output=self._format_findings(findings),
        )

    def _analyze(
        self,
        log_data: Optional[list],
        metric_data: Optional[dict],
        analysis_type: str,
    ) -> list[dict[str, Any]]:
        """Perform analysis on the data."""
        findings = []

        if log_data:
            error_logs = [l for l in log_data if l.get("level") == "error"]
            if error_logs:
                findings.append({
                    "type": "error_pattern",
                    "description": f"Found {len(error_logs)} error log entries",
                    "severity": "high" if len(error_logs) > 5 else "medium",
                    "samples": error_logs[:3],
                })

            warn_logs = [l for l in log_data if l.get("level") == "warn"]
            if warn_logs:
                findings.append({
                    "type": "warning_pattern",
                    "description": f"Found {len(warn_logs)} warning entries",
                    "severity": "low",
                })

        if metric_data:
            values = metric_data.get("values", [])
            if values:
                avg = sum(values) / len(values)
                max_val = max(values)

                if max_val > avg * 2:
                    findings.append({
                        "type": "metric_spike",
                        "description": f"Detected metric spike: max {max_val:.2f} vs avg {avg:.2f}",
                        "severity": "medium",
                    })

        if not findings:
            findings.append({
                "type": "no_issues",
                "description": "No significant issues detected in the analyzed data",
                "severity": "info",
            })

        return findings

    def _compute_severity(self, findings: list[dict[str, Any]]) -> str:
        """Compute overall severity from findings."""
        severities = [f.get("severity", "info") for f in findings]

        if "high" in severities:
            return "high"
        if "medium" in severities:
            return "medium"
        if "low" in severities:
            return "low"
        return "info"

    def _generate_recommendation(self, findings: list[dict[str, Any]]) -> str:
        """Generate a recommendation based on findings."""
        severity = self._compute_severity(findings)

        if severity == "high":
            return "Immediate investigation recommended. Consider escalating to on-call."
        if severity == "medium":
            return "Review findings and monitor closely. May require action."
        if severity == "low":
            return "Minor issues detected. Continue monitoring."
        return "No action required at this time."

    def _format_findings(self, findings: list[dict[str, Any]]) -> str:
        """Format findings for raw output."""
        lines = ["Analysis Findings:", "=" * 40]

        for i, finding in enumerate(findings, 1):
            lines.append(f"\n{i}. [{finding['severity'].upper()}] {finding['type']}")
            lines.append(f"   {finding['description']}")

        return "\n".join(lines)


class SummaryTool(Tool):
    """
    Summary tool for generating human-readable summaries.

    Uses LLM to create concise summaries of investigation findings.
    Falls back to template-based summary if LLM is not available.
    """

    def __init__(
        self,
        config: Optional[ToolConfig] = None,
        llm_client: Optional[Any] = None,
    ) -> None:
        super().__init__(config)
        self._llm_client = llm_client

    @property
    def tool_id(self) -> str:
        return "summary"

    @property
    def description(self) -> str:
        return "Generate human-readable summaries of investigation findings"

    @property
    def param_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "enum": ["brief", "detailed", "markdown"],
                    "description": "Summary format"
                },
                "include_recommendations": {
                    "type": "boolean",
                    "description": "Whether to include recommendations"
                },
            },
        }

    async def execute(
        self,
        params: dict[str, Any],
        context: Optional[dict[str, Any]] = None,
    ) -> ToolResult:
        """Generate a summary of the workflow execution."""
        summary_format = params.get("format", "brief")
        include_recommendations = params.get("include_recommendations", True)

        # Gather data from context
        summary_data = self._gather_context(context)

        # Generate summary
        if self._llm_client:
            summary_text = await self._generate_llm_summary(
                summary_data, summary_format
            )
        else:
            summary_text = self._generate_template_summary(
                summary_data, summary_format, include_recommendations
            )

        return ToolResult.success(
            outputs={
                "format": summary_format,
                "summary": summary_text,
                "data_sources": list(summary_data.keys()),
            },
            raw_output=summary_text,
        )

    def _gather_context(
        self,
        context: Optional[dict[str, Any]],
    ) -> dict[str, Any]:
        """Gather relevant data from execution context."""
        data: dict[str, Any] = {
            "findings": [],
            "metrics": {},
            "log_stats": {},
            "recommendations": [],
        }

        if not context:
            return data

        for node_id, outputs in context.items():
            if "findings" in outputs:
                data["findings"].extend(outputs["findings"])

            if "recommendation" in outputs:
                data["recommendations"].append(outputs["recommendation"])

            if "log_count" in outputs:
                data["log_stats"][node_id] = {
                    "count": outputs.get("log_count", 0),
                    "errors": outputs.get("error_count", 0),
                    "warnings": outputs.get("warn_count", 0),
                }

            if "current_value" in outputs:
                data["metrics"][node_id] = {
                    "current": outputs.get("current_value"),
                    "avg": outputs.get("avg_value"),
                    "max": outputs.get("max_value"),
                }

        return data

    def _generate_template_summary(
        self,
        data: dict[str, Any],
        format_type: str,
        include_recommendations: bool,
    ) -> str:
        """Generate a template-based summary."""
        lines = []

        if format_type == "markdown":
            lines.append("# Investigation Summary\n")
            lines.append(f"*Generated: {datetime.utcnow().isoformat()}*\n")
        else:
            lines.append("Investigation Summary")
            lines.append("=" * 40)

        # Findings section
        if data["findings"]:
            if format_type == "markdown":
                lines.append("\n## Findings\n")
            else:
                lines.append("\nFindings:")

            for finding in data["findings"]:
                severity = finding.get("severity", "info")
                desc = finding.get("description", "No description")

                if format_type == "markdown":
                    icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(severity, "ℹ️")
                    lines.append(f"- {icon} **{severity.upper()}**: {desc}")
                else:
                    lines.append(f"  [{severity.upper()}] {desc}")

        # Log stats
        if data["log_stats"]:
            if format_type == "markdown":
                lines.append("\n## Log Analysis\n")
            else:
                lines.append("\nLog Analysis:")

            for source, stats in data["log_stats"].items():
                lines.append(
                    f"  - {source}: {stats['count']} logs, "
                    f"{stats['errors']} errors, {stats['warnings']} warnings"
                )

        # Recommendations
        if include_recommendations and data["recommendations"]:
            if format_type == "markdown":
                lines.append("\n## Recommendations\n")
            else:
                lines.append("\nRecommendations:")

            for rec in data["recommendations"]:
                if format_type == "markdown":
                    lines.append(f"- {rec}")
                else:
                    lines.append(f"  - {rec}")

        if not data["findings"] and not data["log_stats"]:
            lines.append("\nNo significant findings from this investigation.")

        return "\n".join(lines)

    async def _generate_llm_summary(
        self,
        data: dict[str, Any],
        format_type: str,
    ) -> str:
        """Generate an LLM-based summary."""
        # This would use the LLM client to generate a more natural summary
        # For now, fall back to template
        return self._generate_template_summary(data, format_type, True)
