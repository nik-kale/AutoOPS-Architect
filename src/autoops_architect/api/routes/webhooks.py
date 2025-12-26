"""Webhook routes for automated workflow triggering."""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Header, Request, status
from pydantic import BaseModel, Field

from autoops_architect.api.webhooks import (
    WebhookConfig,
    WebhookEvent,
    WebhookSource,
    extract_field_value,
    format_goal_from_template,
    map_webhook_to_goal,
    parse_webhook_payload,
    verify_webhook_signature,
    webhook_events_db,
    webhooks_db,
)
from autoops_architect.models.goal import Environment, Goal
from autoops_architect.planner.architect import Architect

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class CreateWebhookRequest(BaseModel):
    """Request to create a webhook."""

    name: str = Field(..., min_length=3)
    source: WebhookSource = WebhookSource.GENERIC
    template_id: str | None = None
    goal_template: str | None = None
    field_mapping: dict[str, str] = Field(default_factory=dict)
    secret: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_webhook(request: CreateWebhookRequest) -> WebhookConfig:
    """Create a new webhook trigger configuration."""
    webhook_id = f"wh-{uuid.uuid4().hex[:12]}"

    webhook = WebhookConfig(
        id=webhook_id,
        name=request.name,
        source=request.source,
        template_id=request.template_id,
        goal_template=request.goal_template,
        field_mapping=request.field_mapping,
        secret=request.secret,
        metadata=request.metadata,
    )

    webhooks_db[webhook_id] = webhook
    return webhook


@router.get("")
async def list_webhooks() -> list[WebhookConfig]:
    """List all configured webhooks."""
    return list(webhooks_db.values())


@router.get("/{webhook_id}")
async def get_webhook(webhook_id: str) -> WebhookConfig:
    """Get webhook configuration by ID."""
    webhook = webhooks_db.get(webhook_id)
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return webhook


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(webhook_id: str) -> None:
    """Delete a webhook configuration."""
    if webhook_id not in webhooks_db:
        raise HTTPException(status_code=404, detail="Webhook not found")
    del webhooks_db[webhook_id]


@router.post("/{webhook_id}/trigger")
async def trigger_webhook(
    webhook_id: str,
    request: Request,
    x_signature: str | None = Header(None, alias="X-Signature"),
    x_hub_signature: str | None = Header(None, alias="X-Hub-Signature-256"),
) -> dict[str, Any]:
    """
    Receive and process a webhook trigger.

    This endpoint is called by external services to trigger workflows.
    Supports signature verification for security.
    """
    # Get webhook config
    webhook = webhooks_db.get(webhook_id)
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    if not webhook.enabled:
        raise HTTPException(status_code=400, detail="Webhook is disabled")

    # Read raw body for signature verification
    body = await request.body()
    payload = await request.json()

    # Create event record
    event_id = f"evt-{uuid.uuid4().hex[:12]}"
    event = WebhookEvent(
        id=event_id,
        webhook_id=webhook_id,
        source=webhook.source,
        payload=payload,
        signature=x_signature or x_hub_signature,
        verified=False,
        status="received",
    )

    # Verify signature if secret is configured
    if webhook.secret:
        signature = x_signature or x_hub_signature
        if not signature:
            event.status = "failed"
            event.error = "Missing signature"
            webhook_events_db[event_id] = event
            raise HTTPException(status_code=401, detail="Missing webhook signature")

        if not verify_webhook_signature(body, signature, webhook.secret, webhook.source):
            event.status = "failed"
            event.error = "Invalid signature"
            webhook_events_db[event_id] = event
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

        event.verified = True

    # Parse payload based on source
    parsed_payload = parse_webhook_payload(webhook.source, payload)

    # Map to goal parameters
    mapped_params = map_webhook_to_goal(webhook, parsed_payload)

    # Generate goal description
    if webhook.goal_template:
        goal_description = format_goal_from_template(webhook.goal_template, mapped_params)
    else:
        goal_description = f"Webhook trigger: {webhook.name}"

    # Extract environment and services if mapped
    services = mapped_params.get("services", [])
    if isinstance(services, str):
        services = [services]

    environment_str = mapped_params.get("environment", "production")
    try:
        environment = Environment(environment_str.lower())
    except ValueError:
        environment = Environment.PRODUCTION

    # Create goal
    goal = Goal(
        description=goal_description,
        services=services,
        environment=environment,
    )

    # Plan workflow
    try:
        event.status = "processing"
        webhook_events_db[event_id] = event

        architect = Architect()
        workflow = await architect.plan(goal)

        event.workflow_id = workflow.id
        event.status = "completed"
        webhook_events_db[event_id] = event

        return {
            "event_id": event_id,
            "workflow_id": workflow.id,
            "status": "success",
            "message": f"Workflow created: {workflow.name}",
        }

    except Exception as e:
        event.status = "failed"
        event.error = str(e)
        webhook_events_db[event_id] = event
        raise HTTPException(status_code=500, detail=f"Failed to create workflow: {e}")


@router.get("/{webhook_id}/events")
async def list_webhook_events(webhook_id: str) -> list[WebhookEvent]:
    """List events for a specific webhook."""
    webhook = webhooks_db.get(webhook_id)
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    return [
        event for event in webhook_events_db.values()
        if event.webhook_id == webhook_id
    ]


@router.get("/events/{event_id}")
async def get_webhook_event(event_id: str) -> WebhookEvent:
    """Get details of a specific webhook event."""
    event = webhook_events_db.get(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event

