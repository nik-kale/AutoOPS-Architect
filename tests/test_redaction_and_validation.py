"""Tests for secret redaction in logs and the URL and path safety checks."""

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import pytest
import structlog

from autoops_architect.logging import (
    LogContext,
    add_correlation_ids,
    configure_logging,
    get_logger,
    redact_sensitive_data,
    workflow_id_var,
)
from autoops_architect.memory.semantic import LocalEmbeddingProvider
from autoops_architect.safety.sanitizer import redact_sensitive, validate_path, validate_url

LONG_ANTHROPIC_KEY = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz"
LONG_OPENAI_PROJECT_KEY = "sk-proj-abcdefghijklmnopqrstuvwxyz"


def redact(**fields: Any) -> dict[str, Any]:
    return dict(redact_sensitive_data(logging.getLogger(), "info", dict(fields)))


class TestLogRedaction:
    @pytest.mark.parametrize("key", [LONG_ANTHROPIC_KEY, LONG_OPENAI_PROJECT_KEY])
    def test_prefixed_provider_keys_are_redacted(self, key: str) -> None:
        result = redact(event=f"calling provider with {key}")

        assert key not in result["event"]
        assert key[-10:] not in result["event"]

    def test_secret_nested_in_a_field_is_redacted(self) -> None:
        result = redact(
            event="request",
            request={"headers": [{"note": f"key {LONG_ANTHROPIC_KEY}"}]},
        )

        assert LONG_ANTHROPIC_KEY not in json.dumps(result)

    @pytest.mark.parametrize(
        "field", ["password", "api_key", "client_secret", "access_token", "Authorization"]
    )
    def test_sensitive_field_names_hide_short_values(self, field: str) -> None:
        assert redact(event="login", **{field: "hunter2"})[field] == "***REDACTED***"

    def test_sensitive_name_inside_nested_dict(self) -> None:
        result = redact(event="login", params={"password": "hunter2", "service": "api"})

        assert result["params"] == {"password": "***REDACTED***", "service": "api"}

    @pytest.mark.parametrize("field", ["token_count", "max_tokens", "secret_santa", "keys"])
    def test_ordinary_field_names_are_kept(self, field: str) -> None:
        assert redact(event="usage", **{field: "visible"})[field] == "visible"

    def test_traceback_text_is_redacted(self, capsys: pytest.CaptureFixture[str]) -> None:
        structlog.reset_defaults()
        configure_logging(log_level="INFO", json_logs=True)
        handler = logging.StreamHandler()
        logging.getLogger("redaction-test").addHandler(handler)
        logger = get_logger("redaction-test")

        try:
            try:
                raise ValueError(f"provider rejected password={LONG_ANTHROPIC_KEY}")
            except ValueError:
                logger.error("call_failed", exc_info=True)
        finally:
            logging.getLogger("redaction-test").removeHandler(handler)

        captured = capsys.readouterr()
        assert "provider rejected" in captured.err
        assert LONG_ANTHROPIC_KEY not in captured.err


class TestSanitizerRedaction:
    def test_prefixed_provider_keys_are_redacted(self) -> None:
        assert LONG_ANTHROPIC_KEY not in redact_sensitive(f"key {LONG_ANTHROPIC_KEY}")


class TestLogContext:
    def test_ids_do_not_leak_into_later_log_lines(self) -> None:
        with LogContext(workflow_id="wf-1"):
            pass

        assert workflow_id_var.get() is None
        event = add_correlation_ids(logging.getLogger(), "info", {"event": "later"})
        assert "workflow_id" not in event

    def test_outer_value_is_restored_after_nesting(self) -> None:
        with LogContext(workflow_id="outer"):
            with LogContext(workflow_id="inner"):
                assert workflow_id_var.get() == "inner"
            assert workflow_id_var.get() == "outer"


class TestValidateUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.2/",
            "http://127.1/",
            "http://2130706433/",
            "http://10.0.0.5/",
            "http://192.168.1.10/",
            "http://172.16.0.1/",
            "http://169.254.169.254/latest/meta-data/",
            "http://[::1]/",
            "http://[::ffff:127.0.0.1]/",
            "http://[fd00::1]/",
            "http://LOCALHOST/",
            "http://app.localhost/",
        ],
    )
    def test_internal_addresses_are_refused(self, url: str) -> None:
        valid, _ = validate_url(url)

        assert valid is False, url

    @pytest.mark.parametrize(
        "url", ["https://localhost.example.com/", "https://8.8.8.8/", "https://example.com/"]
    )
    def test_public_hosts_are_allowed(self, url: str) -> None:
        valid, error = validate_url(url)

        assert valid is True, error


class TestValidatePath:
    def test_sibling_with_shared_prefix_is_outside_the_base(self, tmp_path: Path) -> None:
        base = tmp_path / "data"
        base.mkdir()
        sibling = tmp_path / "data-private" / "secrets.txt"

        valid, _ = validate_path(str(sibling), base_dir=str(base), allow_absolute=True)

        assert valid is False

    def test_file_inside_the_base_is_allowed(self, tmp_path: Path) -> None:
        valid, error = validate_path("reports/today.txt", base_dir=str(tmp_path))

        assert valid is True, error

    def test_symlink_out_of_the_base_is_refused(self, tmp_path: Path) -> None:
        base = tmp_path / "data"
        base.mkdir()
        (base / "link").symlink_to(tmp_path)

        valid, _ = validate_path("link/outside.txt", base_dir=str(base))

        assert valid is False

    @pytest.mark.parametrize("path", ["..", "a/..", "a\\..\\b"])
    def test_parent_components_are_refused(self, path: str) -> None:
        valid, _ = validate_path(path)

        assert valid is False


class TestFeatureHashing:
    def test_md5_is_declared_non_security(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[bool] = []
        real_md5 = hashlib.md5

        def spy(data: bytes, *, usedforsecurity: bool = True) -> Any:
            seen.append(usedforsecurity)
            return real_md5(data, usedforsecurity=False)

        monkeypatch.setattr("autoops_architect.memory.semantic.hashlib.md5", spy)

        LocalEmbeddingProvider(dimension=128).embed("database connection errors")

        assert seen
        assert not any(seen)
