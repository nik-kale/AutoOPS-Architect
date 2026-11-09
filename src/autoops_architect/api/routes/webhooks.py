"""Webhook routes for automated workflow triggering."""

import json
import uuid
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from autoops_architect.api.auth import requires
from autoops_architect.api.routes.workflows import _active_workflows
from autoops_architect.api.webhooks import (
    WebhookConfig,
    WebhookEvent,
    WebhookSource,
    format_goal_from_template,
    map_webhook_to_goal,
    parse_webhook_payload,
    verify_webhook_signature,
    webhook_events_db,
    webhooks_db,
)
from autoops_architect.models.goal import Environment, Goal
from autoops_architect.planner.architect import Architect
from autoops_architect.safety.sanitizer import MAX_GOAL_LENGTH

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

MAX_WEBHOOK_BODY_BYTES = 1024 * 1024


class CreateWebhookRequest(BaseModel):
    """Request to create a webhook."""

    name: str = Field(..., min_length=3)
    source: WebhookSource = WebhookSource.GENERIC
    template_id: str | None = None
    goal_template: str | None = None
    field_mapping: dict[str, str] = Field(default_factory=dict)
    secret: str = Field(..., min_length=16, description="Shared secret used to sign requests")
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=[requires("manage:webhooks")])
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


@router.get("", dependencies=[requires("manage:webhooks")])
async def list_webhooks() -> list[WebhookConfig]:
    """List all configured webhooks."""
    return list(webhooks_db.values())


@router.get("/{webhook_id}", dependencies=[requires("manage:webhooks")])
async def get_webhook(webhook_id: str) -> WebhookConfig:
    """Get webhook configuration by ID."""
    webhook = webhooks_db.get(webhook_id)
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return webhook


@router.delete(
    "/{webhook_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[requires("manage:webhooks")],
)
async def delete_webhook(webhook_id: str) -> None:
    """Delete a webhook configuration."""
    if webhook_id not in webhooks_db:
        raise HTTPException(status_code=404, detail="Webhook not found")
    del webhooks_db[webhook_id]


async def _read_limited_body(request: Request) -> bytes:
    """Read the request body, refusing anything over the size limit."""
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_WEBHOOK_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Webhook payload too large")
    return bytes(body)


@router.post("/{webhook_id}/trigger")
async def trigger_webhook(
    webhook_id: str,
    request: Request,
    x_signature: str | None = Header(None, alias="X-Signature"),
    x_hub_signature: str | None = Header(None, alias="X-Hub-Signature-256"),
    x_pagerduty_signature: str | None = Header(None, alias="X-PagerDuty-Signature"),
) -> dict[str, Any]:
    """
    Receive and process a webhook trigger.

    This endpoint is called by external services to trigger workflows and is
    authenticated by the request signature rather than by API credentials.
    """
    webhook = webhooks_db.get(webhook_id)
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    if not webhook.enabled:
        raise HTTPException(status_code=400, detail="Webhook is disabled")

    # Authenticate before parsing or storing anything the sender supplied.
    body = await _read_limited_body(request)
    signature = x_signature or x_hub_signature or x_pagerduty_signature
    if not webhook.secret or not signature:
        raise HTTPException(status_code=401, detail="Missing webhook signature")
    if not verify_webhook_signature(body, signature, webhook.secret, webhook.source):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload = json.loads(body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Webhook payload is not valid JSON") from e
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook payload must be a JSON object")

    event_id = f"evt-{uuid.uuid4().hex[:12]}"
    event = WebhookEvent(
        id=event_id,
        webhook_id=webhook_id,
        source=webhook.source,
        payload=payload,
        signature=signature,
        verified=True,
        status="processing",
    )
    webhook_events_db[event_id] = event

    try:
        parsed_payload = parse_webhook_payload(webhook.source, payload)
        mapped_params = map_webhook_to_goal(webhook, parsed_payload)

        if webhook.goal_template:
            goal_description = format_goal_from_template(webhook.goal_template, mapped_params)
        else:
            goal_description = f"Webhook trigger: {webhook.name}"

        services = mapped_params.get("services", [])
        if isinstance(services, str):
            services = [services]

        try:
            environment = Environment(str(mapped_params.get("environment", "production")).lower())
        except ValueError:
            environment = Environment.PRODUCTION

        goal = Goal(
            description=goal_description[:MAX_GOAL_LENGTH],
            services=services,
            environment=environment,
        )

        architect = Architect()
        if webhook.template_id:
            workflow = architect.plan_from_template(webhook.template_id, goal)
        else:
            workflow = await architect.plan(goal)

    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as e:
        # Malformed payloads, invalid goals and blocked prompt injection
        event.status = "failed"
        event.error = str(e)
        raise HTTPException(status_code=400, detail=f"Could not process webhook: {e}") from e

    except Exception as e:
        event.status = "failed"
        event.error = str(e)
        raise HTTPException(status_code=500, detail=f"Failed to create workflow: {e}") from e

    # Keep it so the planned run can be reviewed and executed through the API
    _active_workflows[workflow.id] = workflow

    event.workflow_id = workflow.id
    event.status = "completed"

    return {
        "event_id": event_id,
        "workflow_id": workflow.id,
        "status": "success",
        "message": f"Workflow created: {workflow.name}",
    }


@router.get("/{webhook_id}/events", dependencies=[requires("manage:webhooks")])
async def list_webhook_events(webhook_id: str) -> list[WebhookEvent]:
    """List events for a specific webhook."""
    webhook = webhooks_db.get(webhook_id)
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    return [event for event in webhook_events_db.values() if event.webhook_id == webhook_id]


@router.get("/events/{event_id}", dependencies=[requires("manage:webhooks")])
async def get_webhook_event(event_id: str) -> WebhookEvent:
    """Get details of a specific webhook event."""
    event = webhook_events_db.get(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event
