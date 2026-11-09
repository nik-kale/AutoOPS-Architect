"""Tests for the GitHub Actions workflows in the repository."""

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))

# Contexts whose values are chosen by whoever opens the pull request.
UNTRUSTED_CONTEXT = re.compile(
    r"\$\{\{[^}]*(github\.event\.pull_request\.(title|body)|steps\.[\w-]+\.outputs)[^}]*\}\}"
)


def steps_of(path: Path) -> list[dict[str, Any]]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [step for job in document["jobs"].values() for step in job["steps"]]


def named_step(path: Path, name: str) -> dict[str, Any]:
    return next(step for step in steps_of(path) if step.get("name") == name)


class TestWorkflows:
    @pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
    def test_untrusted_values_are_not_expanded_in_shell(self, path: Path) -> None:
        for step in steps_of(path):
            assert not UNTRUSTED_CONTEXT.search(step.get("run", "")), step.get("name")

    @pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
    def test_no_compromised_or_retired_actions(self, path: Path) -> None:
        for step in steps_of(path):
            uses = step.get("uses", "")
            assert not uses.startswith("tj-actions/"), uses
            assert not re.search(r"actions/(upload|download)-artifact@v[123]$", uses), uses

    @pytest.mark.parametrize(
        ("changed", "flagged"),
        [
            ("certs/server.pem", True),
            ("deploy/prod.key", True),
            ("config/app.env", True),
            (".env", True),
            (".env.production", True),
            ("keys/id_rsa", True),
            ("docs/environment.md", False),
            ("tests/test_env.py", False),
            ("src/keyboard.py", False),
            ("README.md", False),
        ],
    )
    @pytest.mark.skipif(shutil.which("bash") is None, reason="requires bash")
    def test_sensitive_file_check(self, tmp_path: Path, changed: str, flagged: bool) -> None:
        (tmp_path / "changed-files.txt").write_text(f"{changed}\n")
        script = named_step(WORKFLOWS_BY_NAME["pr-checks.yml"], "Check for sensitive files")["run"]

        result = subprocess.run(
            ["bash", "-e", "-c", script],
            env={"RUNNER_TEMP": str(tmp_path), "PATH": "/usr/bin:/bin"},
            capture_output=True,
            text=True,
            check=False,
        )

        assert (result.returncode != 0) is flagged, result.stdout

    @pytest.mark.skipif(shutil.which("bash") is None, reason="requires bash")
    def test_pr_title_with_shell_syntax_is_only_data(self, tmp_path: Path) -> None:
        marker = tmp_path / "pwned"
        script = named_step(WORKFLOWS_BY_NAME["pr-checks.yml"], "Check PR title format")["run"]

        result = subprocess.run(
            ["bash", "-e", "-c", script],
            env={"PR_TITLE": f'fix: "$(touch {marker})" `touch {marker}`', "PATH": "/usr/bin:/bin"},
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stdout
        assert not marker.exists()


WORKFLOWS_BY_NAME = {path.name: path for path in WORKFLOWS}
