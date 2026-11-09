"""Tests for webhook signature checks, payload handling and goal formatting."""

import hashlib
import hmac
import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from autoops_architect.api.app import create_app
from autoops_architect.api.routes.webhooks import MAX_WEBHOOK_BODY_BYTES
from autoops_architect.api.routes.workflows import _active_workflows
from autoops_architect.api.webhooks import (
    WebhookConfig,
    WebhookSource,
    extract_field_value,
    format_goal_from_template,
    parse_datadog_webhook,
    verify_webhook_signature,
    webhook_events_db,
    webhooks_db,
)

SECRET = "a-sufficiently-long-secret"
HEADER = "X-Signature"


def sign(body: bytes, secret: str = SECRET) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture
def client() -> Iterator[TestClient]:
    yield TestClient(create_app())
    webhooks_db.clear()
    webhook_events_db.clear()


def create_webhook(client: TestClient, **overrides: Any) -> str:
    payload = {
        "name": "Alerts",
        "secret": SECRET,
        "goal_template": "Investigate {title} alert for the service",
        "field_mapping": {"title": "$.title"},
        **overrides,
    }
    response = client.post("/api/v1/webhooks", json=payload)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def trigger(client: TestClient, webhook_id: str, body: bytes, signature: str | None = None) -> Any:
    headers = {"Content-Type": "application/json"}
    if signature is not None:
        headers[HEADER] = signature
    return client.post(f"/api/v1/webhooks/{webhook_id}/trigger", content=body, headers=headers)


class TestTrigger:
    def test_signed_request_creates_a_retrievable_workflow(self, client: TestClient) -> None:
        webhook_id = create_webhook(client)
        body = json.dumps({"title": "disk-full"}).encode()

        response = trigger(client, webhook_id, body, sign(body))

        assert response.status_code == 200, response.text
        workflow_id = response.json()["workflow_id"]
        assert workflow_id in _active_workflows
        assert "disk-full" in _active_workflows[workflow_id].goal_description

    def test_template_id_is_used(self, client: TestClient) -> None:
        webhook_id = create_webhook(client, template_id="latency-investigation")
        body = json.dumps({"title": "slow"}).encode()

        response = trigger(client, webhook_id, body, sign(body))

        workflow = _active_workflows[response.json()["workflow_id"]]
        assert workflow.metadata["template_id"] == "latency-investigation"

    def test_unsigned_request_is_rejected_and_not_stored(self, client: TestClient) -> None:
        webhook_id = create_webhook(client)

        response = trigger(client, webhook_id, b'{"title": "x"}')

        assert response.status_code == 401
        assert webhook_events_db == {}

    def test_bad_signature_is_rejected_and_not_stored(self, client: TestClient) -> None:
        webhook_id = create_webhook(client)
        body = b'{"title": "x"}'

        response = trigger(client, webhook_id, body, sign(body, "the-wrong-secret-value"))

        assert response.status_code == 401
        assert webhook_events_db == {}

    def test_webhook_without_a_secret_cannot_be_triggered(self, client: TestClient) -> None:
        webhooks_db["wh-open"] = WebhookConfig(id="wh-open", name="Open")

        response = trigger(client, "wh-open", b"{}", "anything")

        assert response.status_code == 401

    @pytest.mark.parametrize("body", [b"not json", b"[1, 2]"])
    def test_signed_non_object_body_is_a_client_error(
        self, client: TestClient, body: bytes
    ) -> None:
        webhook_id = create_webhook(client)

        response = trigger(client, webhook_id, body, sign(body))

        assert response.status_code == 400

    def test_oversized_body_is_rejected(self, client: TestClient) -> None:
        webhook_id = create_webhook(client)
        body = b" " * (MAX_WEBHOOK_BODY_BYTES + 1)

        response = trigger(client, webhook_id, body, sign(body))

        assert response.status_code == 413

    def test_non_string_environment_does_not_crash(self, client: TestClient) -> None:
        webhook_id = create_webhook(client, field_mapping={"environment": "$.env"})
        body = json.dumps({"env": 42}).encode()

        response = trigger(client, webhook_id, body, sign(body))

        assert response.status_code == 200, response.text

    def test_malformed_source_payload_is_a_client_error(self, client: TestClient) -> None:
        webhook_id = create_webhook(client, source="pagerduty")
        body = json.dumps({"messages": ["not-an-object"]}).encode()

        response = client.post(
            f"/api/v1/webhooks/{webhook_id}/trigger",
            content=body,
            headers={"X-PagerDuty-Signature": f"v1={sign(body)}"},
        )

        assert response.status_code == 400


class TestManagement:
    def test_secret_is_never_returned(self, client: TestClient) -> None:
        webhook_id = create_webhook(client)

        listed = client.get("/api/v1/webhooks").json()
        fetched = client.get(f"/api/v1/webhooks/{webhook_id}").json()

        assert "secret" not in listed[0]
        assert "secret" not in fetched
        assert SECRET not in json.dumps([listed, fetched])

    def test_creating_a_webhook_requires_a_real_secret(self, client: TestClient) -> None:
        missing = client.post("/api/v1/webhooks", json={"name": "Alerts"})
        short = client.post("/api/v1/webhooks", json={"name": "Alerts", "secret": "short"})

        assert missing.status_code == 422
        assert short.status_code == 422


class TestSignatureVerification:
    def test_non_ascii_signature_is_invalid_not_an_error(self) -> None:
        assert not verify_webhook_signature(b"{}", "café", SECRET, WebhookSource.GENERIC)

    def test_github_prefix(self) -> None:
        body = b"{}"
        assert verify_webhook_signature(body, f"sha256={sign(body)}", SECRET, WebhookSource.GITHUB)
        assert not verify_webhook_signature(body, sign(body), SECRET, WebhookSource.GITHUB)

    def test_pagerduty_accepts_any_listed_signature(self) -> None:
        body = b"{}"
        header = f"v1={sign(body, 'old-secret-being-rotated')}, v1={sign(body)}"

        assert verify_webhook_signature(body, header, SECRET, WebhookSource.PAGERDUTY)

    def test_opsgenie_is_verified_rather_than_always_failing(self) -> None:
        body = b"{}"

        assert verify_webhook_signature(body, sign(body), SECRET, WebhookSource.OPSGENIE)


class TestPayloadHelpers:
    def test_format_does_not_expose_object_attributes(self) -> None:
        result = format_goal_from_template("{title.__class__} {title}", {"title": "disk"})

        assert "class" not in result.replace("{title.__class__}", "")
        assert result == "{title.__class__} disk"

    def test_format_tolerates_stray_braces_and_missing_keys(self) -> None:
        assert format_goal_from_template("{} {a} {b}", {"a": 1}) == "{} 1 {b}"

    def test_extract_index_on_non_object_is_none(self) -> None:
        assert extract_field_value({"a": [1]}, "$.a.b[0]") is None

    @pytest.mark.parametrize(
        ("tags", "expected"),
        [
            ({"service": "api"}, "api"),
            ("env:prod,service:api", "api"),
            (["env:prod", "service:api"], "api"),
            (None, "unknown"),
        ],
    )
    def test_datadog_service_tag_formats(self, tags: Any, expected: str) -> None:
        assert parse_datadog_webhook({"tags": tags})["service"] == expected
