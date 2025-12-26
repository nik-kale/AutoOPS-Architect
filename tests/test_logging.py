"""Tests for structured logging."""

import contextvars
import logging
from typing import Any

import pytest
import structlog

from autoops_architect.logging import (
    LogContext,
    add_correlation_ids,
    configure_logging,
    execution_id_var,
    get_logger,
    node_id_var,
    redact_sensitive_data,
    workflow_id_var,
)


class TestConfigureLogging:
    """Test logging configuration."""

    def test_configure_logging_json(self) -> None:
        """Test JSON logging configuration."""
        configure_logging(log_level="INFO", json_logs=True)
        logger = get_logger("test")
        assert logger is not None

    def test_configure_logging_dev(self) -> None:
        """Test development logging configuration."""
        configure_logging(log_level="DEBUG", dev_mode=True)
        logger = get_logger("test")
        assert logger is not None

    def test_get_logger_with_name(self) -> None:
        """Test getting a logger with a specific name."""
        logger = get_logger("my.module")
        assert logger is not None


class TestLogContext:
    """Test LogContext for correlation IDs."""

    def test_log_context_workflow_id(self) -> None:
        """Test setting workflow_id in context."""
        assert workflow_id_var.get() is None

        with LogContext(workflow_id="wf-123"):
            assert workflow_id_var.get() == "wf-123"

        # Should be reset after context
        assert workflow_id_var.get() is None

    def test_log_context_all_ids(self) -> None:
        """Test setting all correlation IDs."""
        with LogContext(
            workflow_id="wf-123",
            execution_id="exec-456",
            node_id="node-789"
        ):
            assert workflow_id_var.get() == "wf-123"
            assert execution_id_var.get() == "exec-456"
            assert node_id_var.get() == "node-789"

        # All should be reset
        assert workflow_id_var.get() is None
        assert execution_id_var.get() is None
        assert node_id_var.get() is None

    def test_nested_log_contexts(self) -> None:
        """Test nested log contexts."""
        with LogContext(workflow_id="wf-outer"):
            assert workflow_id_var.get() == "wf-outer"

            with LogContext(node_id="node-inner"):
                # workflow_id persists, node_id is set
                assert workflow_id_var.get() == "wf-outer"
                assert node_id_var.get() == "node-inner"

            # node_id cleared, workflow_id persists
            assert workflow_id_var.get() == "wf-outer"
            assert node_id_var.get() is None

        # All cleared
        assert workflow_id_var.get() is None


class TestAddCorrelationIds:
    """Test correlation ID processor."""

    def test_add_correlation_ids_empty(self) -> None:
        """Test with no correlation IDs set."""
        event_dict: dict[str, Any] = {"event": "test_event"}
        result = add_correlation_ids(logging.getLogger(), "info", event_dict)

        assert "workflow_id" not in result
        assert "execution_id" not in result
        assert "node_id" not in result

    def test_add_correlation_ids_workflow(self) -> None:
        """Test adding workflow_id."""
        workflow_id_var.set("wf-123")
        try:
            event_dict: dict[str, Any] = {"event": "test_event"}
            result = add_correlation_ids(logging.getLogger(), "info", event_dict)

            assert result["workflow_id"] == "wf-123"
        finally:
            # Clean up
            workflow_id_var.set(None)

    def test_add_correlation_ids_all(self) -> None:
        """Test adding all correlation IDs."""
        workflow_id_var.set("wf-123")
        execution_id_var.set("exec-456")
        node_id_var.set("node-789")

        try:
            event_dict: dict[str, Any] = {"event": "test_event"}
            result = add_correlation_ids(logging.getLogger(), "info", event_dict)

            assert result["workflow_id"] == "wf-123"
            assert result["execution_id"] == "exec-456"
            assert result["node_id"] == "node-789"
        finally:
            # Clean up
            workflow_id_var.set(None)
            execution_id_var.set(None)
            node_id_var.set(None)


class TestRedactSensitiveData:
    """Test sensitive data redaction."""

    def test_redact_api_key(self) -> None:
        """Test redacting API keys."""
        event_dict: dict[str, Any] = {
            "event": "Using api_key=sk-1234567890abcdefghij for request"
        }
        result = redact_sensitive_data(logging.getLogger(), "info", event_dict)

        assert "sk-1234567890abcdefghij" not in result["event"]
        assert "***REDACTED***" in result["event"]

    def test_redact_password(self) -> None:
        """Test redacting passwords."""
        event_dict: dict[str, Any] = {
            "event": "Authenticating with password=supersecret123"
        }
        result = redact_sensitive_data(logging.getLogger(), "info", event_dict)

        assert "supersecret123" not in result["event"]
        assert "***REDACTED***" in result["event"]

    def test_redact_token(self) -> None:
        """Test redacting tokens."""
        event_dict: dict[str, Any] = {
            "event": "Authorization token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        }
        result = redact_sensitive_data(logging.getLogger(), "info", event_dict)

        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in result["event"]
        assert "***REDACTED***" in result["event"]

    def test_redact_bearer_token(self) -> None:
        """Test redacting Bearer tokens."""
        event_dict: dict[str, Any] = {
            "event": "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz"
        }
        result = redact_sensitive_data(logging.getLogger(), "info", event_dict)

        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz" not in result["event"]
        assert "***REDACTED***" in result["event"]

    def test_redact_in_field_values(self) -> None:
        """Test redacting sensitive data in field values."""
        event_dict: dict[str, Any] = {
            "event": "api_call",
            "api_key": "sk-1234567890abcdefghij",
            "count": 42,
        }
        result = redact_sensitive_data(logging.getLogger(), "info", event_dict)

        # API key should be redacted
        assert result["api_key"] == "sk-***REDACTED***"
        # Non-string fields should be unchanged
        assert result["count"] == 42

    def test_no_false_positives(self) -> None:
        """Test that normal text is not redacted."""
        event_dict: dict[str, Any] = {
            "event": "Processing request for user token_holder with password_protected data"
        }
        result = redact_sensitive_data(logging.getLogger(), "info", event_dict)

        # Should not be redacted (no actual secrets)
        assert "token_holder" in result["event"]
        assert "password_protected" in result["event"]


class TestLoggingIntegration:
    """Test logging integration with executor and planner."""

    async def test_logger_in_workflow_execution(self) -> None:
        """Test that logger can be used in workflow execution."""
        from autoops_architect.models.workflow import Node, NodeType, WorkflowGraph

        logger = get_logger("test")

        workflow = WorkflowGraph(
            id="wf-test",
            name="Test Workflow",
            goal_description="Test goal",
            nodes=[
                Node(
                    id="test-node",
                    name="Test Node",
                    description="A test node",
                    type=NodeType.ANALYSIS,
                    tool="echo",
                    params={},
                )
            ],
            edges=[],
        )

        with LogContext(workflow_id=workflow.id):
            logger.info("test_event", workflow_name=workflow.name)
            # This should not raise an exception

    async def test_logger_in_planner(self) -> None:
        """Test that logger can be used in planner."""
        from autoops_architect.models.goal import Environment, Goal, Priority

        logger = get_logger("test")

        goal = Goal(
            description="Test goal",
            services=["test-service"],
            environment=Environment.PRODUCTION,
            priority=Priority.HIGH,
        )

        logger.info(
            "planning_test",
            goal=goal.description,
            environment=goal.environment.value,
        )
        # This should not raise an exception

