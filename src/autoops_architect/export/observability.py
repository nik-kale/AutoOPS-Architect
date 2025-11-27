"""Observability integrations for tracing and metrics."""

import json
import logging
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, Generator, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class TracingConfig(BaseModel):
    """Configuration for distributed tracing."""

    enabled: bool = Field(
        default=False,
        description="Whether tracing is enabled"
    )

    service_name: str = Field(
        default="autoops-architect",
        description="Service name for traces"
    )

    exporter: str = Field(
        default="console",
        description="Trace exporter: console, jaeger, otlp, zipkin"
    )

    endpoint: Optional[str] = Field(
        default=None,
        description="Exporter endpoint URL"
    )

    sample_rate: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Sampling rate (0.0-1.0)"
    )

    headers: Dict[str, str] = Field(
        default_factory=dict,
        description="Additional headers for exporter"
    )


@dataclass
class SpanData:
    """Data for a trace span."""
    name: str
    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    status: str = "ok"
    attributes: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)

    def add_event(self, name: str, attributes: Optional[Dict[str, Any]] = None) -> None:
        """Add an event to the span."""
        self.events.append({
            "name": name,
            "timestamp": time.time(),
            "attributes": attributes or {},
        })

    def set_attribute(self, key: str, value: Any) -> None:
        """Set a span attribute."""
        self.attributes[key] = value

    def set_status(self, status: str, message: Optional[str] = None) -> None:
        """Set span status."""
        self.status = status
        if message:
            self.attributes["status.message"] = message

    def end(self) -> None:
        """End the span."""
        self.end_time = time.time()

    @property
    def duration_ms(self) -> float:
        """Get span duration in milliseconds."""
        if self.end_time is None:
            return (time.time() - self.start_time) * 1000
        return (self.end_time - self.start_time) * 1000

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for export."""
        return {
            "name": self.name,
            "traceId": self.trace_id,
            "spanId": self.span_id,
            "parentSpanId": self.parent_span_id,
            "startTimeUnixNano": int(self.start_time * 1e9),
            "endTimeUnixNano": int((self.end_time or time.time()) * 1e9),
            "status": {"code": self.status},
            "attributes": [
                {"key": k, "value": {"stringValue": str(v)}}
                for k, v in self.attributes.items()
            ],
            "events": [
                {
                    "name": e["name"],
                    "timeUnixNano": int(e["timestamp"] * 1e9),
                    "attributes": [
                        {"key": k, "value": {"stringValue": str(v)}}
                        for k, v in e.get("attributes", {}).items()
                    ],
                }
                for e in self.events
            ],
        }


class Tracer:
    """Simple tracer for workflow execution."""

    def __init__(self, config: Optional[TracingConfig] = None) -> None:
        """Initialize tracer."""
        self.config = config or TracingConfig()
        self._active_spans: Dict[str, SpanData] = {}
        self._completed_spans: List[SpanData] = []

    def _generate_id(self) -> str:
        """Generate a unique ID."""
        import uuid
        return uuid.uuid4().hex[:16]

    @contextmanager
    def span(
        self,
        name: str,
        parent_span_id: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> Generator[SpanData, None, None]:
        """
        Create a new span.

        Args:
            name: Span name.
            parent_span_id: Optional parent span ID.
            attributes: Initial attributes.

        Yields:
            SpanData instance.
        """
        if not self.config.enabled:
            # Return dummy span
            span = SpanData(
                name=name,
                trace_id="",
                span_id="",
            )
            yield span
            return

        trace_id = self._generate_id() + self._generate_id()
        span_id = self._generate_id()

        span = SpanData(
            name=name,
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            attributes=attributes or {},
        )

        self._active_spans[span_id] = span

        try:
            yield span
            span.set_status("ok")
        except Exception as e:
            span.set_status("error", str(e))
            raise
        finally:
            span.end()
            del self._active_spans[span_id]
            self._completed_spans.append(span)
            self._export_span(span)

    def _export_span(self, span: SpanData) -> None:
        """Export a completed span."""
        if self.config.exporter == "console":
            logger.info(
                f"[TRACE] {span.name} | "
                f"trace_id={span.trace_id[:8]}... | "
                f"duration={span.duration_ms:.2f}ms | "
                f"status={span.status}"
            )
        elif self.config.exporter == "otlp":
            self._export_otlp(span)
        # Add other exporters as needed

    def _export_otlp(self, span: SpanData) -> None:
        """Export span via OTLP."""
        if not self.config.endpoint:
            return

        try:
            import httpx

            data = {
                "resourceSpans": [{
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": self.config.service_name}},
                        ],
                    },
                    "scopeSpans": [{
                        "spans": [span.to_dict()],
                    }],
                }],
            }

            httpx.post(
                f"{self.config.endpoint}/v1/traces",
                json=data,
                headers={
                    "Content-Type": "application/json",
                    **self.config.headers,
                },
                timeout=5.0,
            )
        except Exception as e:
            logger.warning(f"Failed to export span: {e}")


# Global tracer instance
_tracer: Optional[Tracer] = None


def setup_tracing(config: Optional[TracingConfig] = None) -> Tracer:
    """
    Setup tracing with the given configuration.

    Args:
        config: Tracing configuration.

    Returns:
        Configured Tracer instance.
    """
    global _tracer

    if config is None:
        # Load from environment
        config = TracingConfig(
            enabled=os.environ.get("AUTOOPS_TRACING_ENABLED", "false").lower() == "true",
            service_name=os.environ.get("AUTOOPS_SERVICE_NAME", "autoops-architect"),
            exporter=os.environ.get("AUTOOPS_TRACE_EXPORTER", "console"),
            endpoint=os.environ.get("AUTOOPS_TRACE_ENDPOINT"),
        )

    _tracer = Tracer(config)
    return _tracer


def get_tracer() -> Tracer:
    """Get the global tracer instance."""
    global _tracer
    if _tracer is None:
        _tracer = Tracer()
    return _tracer


@contextmanager
def trace_workflow_execution(
    workflow_id: str,
    workflow_name: str,
) -> Generator[SpanData, None, None]:
    """
    Context manager for tracing workflow execution.

    Args:
        workflow_id: Workflow ID.
        workflow_name: Workflow name.

    Yields:
        Root span for the workflow.
    """
    tracer = get_tracer()

    with tracer.span(
        f"workflow.execute",
        attributes={
            "workflow.id": workflow_id,
            "workflow.name": workflow_name,
        },
    ) as span:
        yield span


@contextmanager
def trace_node_execution(
    node_id: str,
    node_name: str,
    node_type: str,
    tool: Optional[str] = None,
    parent_span_id: Optional[str] = None,
) -> Generator[SpanData, None, None]:
    """
    Context manager for tracing node execution.

    Args:
        node_id: Node ID.
        node_name: Node name.
        node_type: Node type.
        tool: Tool being used.
        parent_span_id: Parent span ID.

    Yields:
        Span for the node.
    """
    tracer = get_tracer()

    with tracer.span(
        f"node.execute.{node_type}",
        parent_span_id=parent_span_id,
        attributes={
            "node.id": node_id,
            "node.name": node_name,
            "node.type": node_type,
            "node.tool": tool or "none",
        },
    ) as span:
        yield span


class MetricsExporter:
    """
    Exports metrics for workflows and executions.

    Supports Prometheus-style metrics export.
    """

    def __init__(self) -> None:
        """Initialize metrics exporter."""
        self._counters: Dict[str, int] = {}
        self._histograms: Dict[str, List[float]] = {}
        self._gauges: Dict[str, float] = {}

    def increment(self, name: str, value: int = 1, labels: Optional[Dict[str, str]] = None) -> None:
        """Increment a counter."""
        key = self._make_key(name, labels)
        self._counters[key] = self._counters.get(key, 0) + value

    def observe(self, name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        """Record a histogram observation."""
        key = self._make_key(name, labels)
        if key not in self._histograms:
            self._histograms[key] = []
        self._histograms[key].append(value)

    def set(self, name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        """Set a gauge value."""
        key = self._make_key(name, labels)
        self._gauges[key] = value

    def _make_key(self, name: str, labels: Optional[Dict[str, str]]) -> str:
        """Create a metric key from name and labels."""
        if not labels:
            return name
        label_str = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"

    def to_prometheus(self) -> str:
        """Export metrics in Prometheus format."""
        lines = []

        # Counters
        for key, value in self._counters.items():
            lines.append(f"# TYPE {key.split('{')[0]} counter")
            lines.append(f"{key} {value}")

        # Histograms
        for key, values in self._histograms.items():
            base_name = key.split('{')[0]
            lines.append(f"# TYPE {base_name} histogram")
            if values:
                lines.append(f"{key}_count {len(values)}")
                lines.append(f"{key}_sum {sum(values)}")

        # Gauges
        for key, value in self._gauges.items():
            lines.append(f"# TYPE {key.split('{')[0]} gauge")
            lines.append(f"{key} {value}")

        return "\n".join(lines)

    def to_json(self) -> str:
        """Export metrics as JSON."""
        return json.dumps({
            "counters": self._counters,
            "histograms": {k: {"count": len(v), "sum": sum(v), "values": v[:100]}
                          for k, v in self._histograms.items()},
            "gauges": self._gauges,
        }, indent=2)

    def clear(self) -> None:
        """Clear all metrics."""
        self._counters.clear()
        self._histograms.clear()
        self._gauges.clear()


# Global metrics instance
_metrics: Optional[MetricsExporter] = None


def get_metrics() -> MetricsExporter:
    """Get the global metrics exporter."""
    global _metrics
    if _metrics is None:
        _metrics = MetricsExporter()
    return _metrics


# Convenience functions for common metrics

def record_workflow_execution(
    workflow_id: str,
    status: str,
    duration_seconds: float,
    node_count: int,
) -> None:
    """Record metrics for a workflow execution."""
    metrics = get_metrics()

    metrics.increment(
        "autoops_workflow_executions_total",
        labels={"status": status},
    )

    metrics.observe(
        "autoops_workflow_duration_seconds",
        duration_seconds,
        labels={"status": status},
    )

    metrics.observe(
        "autoops_workflow_nodes",
        float(node_count),
    )


def record_node_execution(
    node_type: str,
    tool: str,
    status: str,
    duration_seconds: float,
) -> None:
    """Record metrics for a node execution."""
    metrics = get_metrics()

    metrics.increment(
        "autoops_node_executions_total",
        labels={
            "type": node_type,
            "tool": tool,
            "status": status,
        },
    )

    metrics.observe(
        "autoops_node_duration_seconds",
        duration_seconds,
        labels={
            "type": node_type,
            "tool": tool,
        },
    )


def record_tool_call(
    tool: str,
    status: str,
    duration_seconds: float,
) -> None:
    """Record metrics for a tool call."""
    metrics = get_metrics()

    metrics.increment(
        "autoops_tool_calls_total",
        labels={"tool": tool, "status": status},
    )

    metrics.observe(
        "autoops_tool_duration_seconds",
        duration_seconds,
        labels={"tool": tool},
    )
