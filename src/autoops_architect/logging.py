"""Structured logging configuration for AutoOps Architect."""

import contextvars
import logging
import os
import re
import sys
from typing import Any, Optional

import structlog
from structlog.types import EventDict, Processor

# Context variables for correlation IDs
workflow_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "workflow_id", default=None
)
execution_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "execution_id", default=None
)
node_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "node_id", default=None
)


# Patterns for sensitive data that should be redacted
SENSITIVE_PATTERNS = [
    (re.compile(r'(api[_-]?key["\s:=]+)[\w\-]{20,}', re.IGNORECASE), r'\1***REDACTED***'),
    (re.compile(r'(password["\s:=]+)[^\s"]+', re.IGNORECASE), r'\1***REDACTED***'),
    (re.compile(r'(token["\s:=]+)[\w\-\.]{20,}', re.IGNORECASE), r'\1***REDACTED***'),
    (re.compile(r'(secret["\s:=]+)[^\s"]+', re.IGNORECASE), r'\1***REDACTED***'),
    (re.compile(r'(authorization[:\s]+bearer\s+)[\w\-\.]+', re.IGNORECASE), r'\1***REDACTED***'),
    (re.compile(r'sk-[a-zA-Z0-9]{20,}'), 'sk-***REDACTED***'),  # OpenAI keys
]


def add_correlation_ids(
    logger: logging.Logger, method_name: str, event_dict: EventDict
) -> EventDict:
    """
    Add correlation IDs from context to log entries.

    This processor injects workflow_id, execution_id, and node_id into
    every log entry if they are set in the current context.
    """
    workflow_id = workflow_id_var.get()
    execution_id = execution_id_var.get()
    node_id = node_id_var.get()

    if workflow_id:
        event_dict["workflow_id"] = workflow_id
    if execution_id:
        event_dict["execution_id"] = execution_id
    if node_id:
        event_dict["node_id"] = node_id

    return event_dict


def redact_sensitive_data(
    logger: logging.Logger, method_name: str, event_dict: EventDict
) -> EventDict:
    """
    Redact sensitive information from log messages.

    Scans the 'event' field and any string values in the event dict
    for patterns matching API keys, passwords, tokens, etc.
    """
    # Redact the main event message
    if "event" in event_dict and isinstance(event_dict["event"], str):
        message = event_dict["event"]
        for pattern, replacement in SENSITIVE_PATTERNS:
            message = pattern.sub(replacement, message)
        event_dict["event"] = message

    # Redact string values in other fields
    for key, value in event_dict.items():
        if isinstance(value, str) and key != "event":
            for pattern, replacement in SENSITIVE_PATTERNS:
                value = pattern.sub(replacement, value)
            event_dict[key] = value

    return event_dict


def configure_logging(
    log_level: Optional[str] = None,
    json_logs: bool = True,
    dev_mode: bool = False,
) -> None:
    """
    Configure structured logging for the application.

    Args:
        log_level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
            Defaults to INFO, or reads from AUTOOPS_LOG_LEVEL env var.
        json_logs: If True, output JSON format. If False, use console format.
            Defaults to True in production, False in dev mode.
        dev_mode: If True, use human-friendly console output with colors.

    Example:
        >>> # Production setup (JSON logs)
        >>> configure_logging(log_level="INFO", json_logs=True)
        >>>
        >>> # Development setup (pretty console logs)
        >>> configure_logging(log_level="DEBUG", dev_mode=True)
    """
    # Determine log level
    if log_level is None:
        log_level = os.getenv("AUTOOPS_LOG_LEVEL", "INFO").upper()

    level = getattr(logging, log_level, logging.INFO)

    # Shared processors (used in all configurations)
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        add_correlation_ids,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        redact_sensitive_data,
    ]

    if dev_mode or not json_logs:
        # Development mode: colorful console output
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(
                colors=True,
                exception_formatter=structlog.dev.plain_traceback,
            )
        ]
    else:
        # Production mode: JSON output
        processors = shared_processors + [
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ]

    # Configure structlog
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        level=level,
        stream=sys.stdout,
    )

    # Silence noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def get_logger(name: Optional[str] = None) -> structlog.stdlib.BoundLogger:
    """
    Get a structured logger instance.

    Args:
        name: Logger name. If None, uses the calling module's name.

    Returns:
        Configured structlog logger.

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("workflow_started", workflow_id="wf-123", node_count=5)
    """
    return structlog.get_logger(name)


class LogContext:
    """
    Context manager for adding correlation IDs to logs.

    Use this to automatically inject workflow_id, execution_id, and node_id
    into all log entries within a code block.

    Example:
        >>> with LogContext(workflow_id="wf-123", execution_id="exec-456"):
        ...     logger.info("processing_node", node="collect-logs")
        ...     # This log will include workflow_id and execution_id
    """

    def __init__(
        self,
        workflow_id: Optional[str] = None,
        execution_id: Optional[str] = None,
        node_id: Optional[str] = None,
    ) -> None:
        """
        Initialize log context.

        Args:
            workflow_id: Workflow identifier.
            execution_id: Execution identifier.
            node_id: Node identifier.
        """
        self.workflow_id = workflow_id
        self.execution_id = execution_id
        self.node_id = node_id
        self._tokens: list[contextvars.Token[Any]] = []

    def __enter__(self) -> "LogContext":
        """Enter the context and set correlation IDs."""
        if self.workflow_id:
            token = workflow_id_var.set(self.workflow_id)
            self._tokens.append(token)
        if self.execution_id:
            token = execution_id_var.set(self.execution_id)
            self._tokens.append(token)
        if self.node_id:
            token = node_id_var.set(self.node_id)
            self._tokens.append(token)
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit the context and restore previous correlation IDs."""
        for token in reversed(self._tokens):
            try:
                # Reset to previous value
                if hasattr(token, "var") and hasattr(token, "old_value"):
                    token.var.set(token.old_value)
            except Exception:
                # If reset fails, just continue
                pass
        self._tokens.clear()


# Auto-configure logging on import if not already configured
if not structlog.is_configured():
    # Check if we're in dev mode (based on environment or if running in a TTY)
    dev_mode = os.getenv("AUTOOPS_DEV_MODE", "").lower() in ("1", "true", "yes")
    dev_mode = dev_mode or (hasattr(sys.stdout, "isatty") and sys.stdout.isatty())

    configure_logging(dev_mode=dev_mode)

