"""Tests for packaging metadata and deployment files."""

import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

import autoops_architect
from autoops_architect.api.app import create_app
from autoops_architect.api.auth import _load_secret_key

ROOT = Path(__file__).resolve().parent.parent


class TestPackaging:
    def pyproject(self) -> dict[str, Any]:
        return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    def test_runtime_imports_are_declared(self) -> None:
        declared = " ".join(self.pyproject()["project"]["dependencies"]).lower()

        for package in ("structlog", "typer", "rich", "httpx", "pydantic", "pyyaml", "jinja2"):
            assert package in declared

    def test_web_extra_covers_the_api(self) -> None:
        web = " ".join(self.pyproject()["project"]["optional-dependencies"]["web"]).lower()

        for package in (
            "fastapi",
            "uvicorn",
            "pyjwt",
            "bcrypt",
            "prometheus-client",
            "apscheduler",
        ):
            assert package in web

    def test_dev_extra_can_run_the_api_tests(self) -> None:
        dev = self.pyproject()["project"]["optional-dependencies"]["dev"]

        assert "autoops-architect[web]" in dev

    def test_reported_versions_match_the_package_metadata(self) -> None:
        version = self.pyproject()["project"]["version"]

        assert autoops_architect.__version__ == version
        assert create_app().version == version


class TestDeployment:
    def compose(self) -> dict[str, Any]:
        return dict(yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8")))

    def test_dockerfile_does_not_glob_the_extras_suffix(self) -> None:
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

        assert "*.whl[web]" not in dockerfile
        assert '"${wheel}[web]"' in dockerfile

    def test_build_context_includes_files_the_image_copies(self) -> None:
        ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

        assert "!README.md" in ignored
        assert "LICENSE" not in ignored

    def test_redis_is_not_published_to_the_host(self) -> None:
        assert "ports" not in self.compose()["services"]["redis"]

    def test_web_port_is_published_on_loopback_only(self) -> None:
        assert self.compose()["services"]["autoops"]["ports"] == ["127.0.0.1:8000:8000"]

    def test_empty_secret_key_is_treated_as_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AUTOOPS_SECRET_KEY", "")

        assert len(_load_secret_key()) >= 32
