"""Webhook trigger system for automated workflow execution."""

import hashlib
import hmac
import json
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class WebhookSource(str, Enum):
    """Supported webhook sources."""

    PAGERDUTY = "pagerduty"
    DATADOG = "datadog"
    OPSGENIE = "opsgenie"
    GITHUB = "github"
    GENERIC = "generic"


class WebhookConfig(BaseModel):
    """Configuration for a webhook trigger."""

    id: str = Field(..., description="Unique webhook ID")
    name: str = Field(..., min_length=3, max_length=100)
    source: WebhookSource = Field(default=WebhookSource.GENERIC)
    template_id: Optional[str] = Field(None, description="Workflow template to trigger")
    goal_template: Optional[str] = Field(None, description="Goal template with placeholders")
    field_mapping: dict[str, str] = Field(
        default_factory=dict,
        description="Map webhook fields to goal parameters using JSONPath"
    )
    secret: Optional[str] = Field(None, description="Secret for signature verification")
    enabled: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WebhookEvent(BaseModel):
    """Recorded webhook event."""

    id: str
    webhook_id: str
    source: WebhookSource
    payload: dict[str, Any]
    signature: Optional[str] = None
    verified: bool = False
    workflow_id: Optional[str] = None
    status: str = "received"  # received, processing, completed, failed
    error: Optional[str] = None
    received_at: datetime = Field(default_factory=datetime.utcnow)
    processed_at: Optional[datetime] = None


# In-memory storage (replace with database in production)
webhooks_db: dict[str, WebhookConfig] = {}
webhook_events_db: dict[str, WebhookEvent] = {}


def verify_webhook_signature(
    payload: bytes,
    signature: str,
    secret: str,
    source: WebhookSource,
) -> bool:
    """
    Verify webhook signature based on source.

    Args:
        payload: Raw payload bytes.
        signature: Signature from webhook headers.
        secret: Shared secret for verification.
        source: Webhook source type.

    Returns:
        True if signature is valid.
    """
    if source == WebhookSource.PAGERDUTY:
        # PagerDuty uses SHA-256 HMAC
        expected = hmac.new(
            secret.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(signature, expected)

    elif source == WebhookSource.DATADOG:
        # Datadog uses SHA-256 HMAC
        expected = hmac.new(
            secret.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(signature, expected)

    elif source == WebhookSource.GITHUB:
        # GitHub uses SHA-256 HMAC with sha256= prefix
        expected = "sha256=" + hmac.new(
            secret.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(signature, expected)

    elif source == WebhookSource.GENERIC:
        # Generic: simple HMAC SHA-256
        expected = hmac.new(
            secret.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(signature, expected)

    else:
        return False


def extract_field_value(payload: dict[str, Any], jsonpath: str) -> Any:
    """
    Extract value from payload using simplified JSONPath.

    Supports:
    - $.field - top level field
    - $.parent.child - nested field
    - $.array[0] - array index

    Args:
        payload: Webhook payload.
        jsonpath: JSONPath expression.

    Returns:
        Extracted value or None.
    """
    if not jsonpath.startswith("$."):
        return None

    path = jsonpath[2:]  # Remove $.
    current = payload

    for part in path.split("."):
        if "[" in part:
            # Handle array index
            field, rest = part.split("[", 1)
            index_str = rest.rstrip("]")
            try:
                index = int(index_str)
                if field:
                    current = current.get(field, {})
                if isinstance(current, list) and 0 <= index < len(current):
                    current = current[index]
                else:
                    return None
            except (ValueError, KeyError, TypeError):
                return None
        else:
            # Regular field access
            if isinstance(current, dict):
                current = current.get(part)
                if current is None:
                    return None
            else:
                return None

    return current


def map_webhook_to_goal(
    webhook: WebhookConfig,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """
    Map webhook payload to goal parameters.

    Args:
        webhook: Webhook configuration.
        payload: Webhook payload.

    Returns:
        Mapped goal parameters.
    """
    mapped = {}

    for param_name, jsonpath in webhook.field_mapping.items():
        if isinstance(jsonpath, str) and jsonpath.startswith("$."):
            # Extract from payload using JSONPath
            value = extract_field_value(payload, jsonpath)
            if value is not None:
                mapped[param_name] = value
        else:
            # Static value
            mapped[param_name] = jsonpath

    return mapped


def format_goal_from_template(
    template: str,
    mapped_params: dict[str, Any],
) -> str:
    """
    Format goal description from template with parameters.

    Args:
        template: Goal template with {placeholders}.
        mapped_params: Mapped parameters.

    Returns:
        Formatted goal description.

    Example:
        >>> template = "Investigate {severity} alert for {service}"
        >>> params = {"severity": "high", "service": "api"}
        >>> format_goal_from_template(template, params)
        "Investigate high alert for api"
    """
    try:
        return template.format(**mapped_params)
    except KeyError:
        # If a key is missing, return template as-is
        return template


# Webhook source-specific payload parsers
def parse_pagerduty_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    """Parse PagerDuty webhook payload to standard format."""
    messages = payload.get("messages", [])
    if not messages:
        return {}

    event = messages[0].get("event", {})
    incident = messages[0].get("incident", {})

    return {
        "severity": event.get("data", {}).get("severity", "unknown"),
        "service": incident.get("service", {}).get("name", "unknown"),
        "title": incident.get("title", ""),
        "incident_key": incident.get("incident_key", ""),
        "status": incident.get("status", ""),
    }


def parse_datadog_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    """Parse Datadog webhook payload to standard format."""
    return {
        "severity": payload.get("priority", "unknown"),
        "service": payload.get("tags", {}).get("service", "unknown"),
        "title": payload.get("title", ""),
        "alert_id": payload.get("id", ""),
        "status": payload.get("alert_status", ""),
        "message": payload.get("body", ""),
    }


def parse_opsgenie_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    """Parse OpsGenie webhook payload to standard format."""
    alert = payload.get("alert", {})

    return {
        "severity": alert.get("priority", "unknown"),
        "service": alert.get("tags", [None])[0] if alert.get("tags") else "unknown",
        "title": alert.get("message", ""),
        "alert_id": alert.get("alertId", ""),
        "status": payload.get("action", ""),
    }


def parse_webhook_payload(
    source: WebhookSource,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """
    Parse webhook payload based on source.

    Args:
        source: Webhook source type.
        payload: Raw webhook payload.

    Returns:
        Standardized payload format.
    """
    if source == WebhookSource.PAGERDUTY:
        return parse_pagerduty_webhook(payload)
    elif source == WebhookSource.DATADOG:
        return parse_datadog_webhook(payload)
    elif source == WebhookSource.OPSGENIE:
        return parse_opsgenie_webhook(payload)
    else:
        return payload

