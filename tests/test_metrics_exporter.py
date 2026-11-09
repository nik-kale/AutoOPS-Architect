"""Tests for the in-process metrics exporter."""

from autoops_architect.export.observability import (
    MetricsExporter,
    get_metrics,
    record_node_execution,
    record_workflow_execution,
)


class TestMetricsExporter:
    def test_prometheus_output_is_valid_exposition_format(self) -> None:
        metrics = MetricsExporter()
        metrics.increment("requests", labels={"status": "ok"})
        metrics.observe("duration", 1.5, labels={"status": "ok"})
        metrics.set("active", 2)

        lines = metrics.to_prometheus().splitlines()

        assert 'requests{status="ok"} 1' in lines
        assert 'duration_count{status="ok"} 1' in lines
        assert 'duration_sum{status="ok"} 1.5' in lines
        assert "active 2" in lines

    def test_recording_helpers(self) -> None:
        get_metrics().clear()

        record_workflow_execution("wf", "success", 1.0, 3)
        record_node_execution("analysis", "echo", "failed", 0.5)

        output = get_metrics().to_prometheus()
        assert 'autoops_workflow_executions_total{status="success"} 1' in output
        assert (
            'autoops_node_executions_total{status="failed",tool="echo",type="analysis"} 1' in output
        )
