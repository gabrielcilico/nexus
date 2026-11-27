import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nexus import installation
from nexus.cli import app
from nexus.storage import installation_data, project_data

SOURCE = Path(__file__).resolve().parents[1]
RUNNER = CliRunner()


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "nexus.storage.user_data_path", lambda *args, **kwargs: tmp_path / "data"
    )
    root = tmp_path / "fixture"
    root.mkdir()
    subprocess.run(["git", "init", str(root)], capture_output=True, check=True)
    return root.resolve()


def run(project, *args, code=0):
    result = RUNNER.invoke(app, [*args, "--project", str(project)])
    assert result.exit_code == code, (result.output, result.exception)
    return result


def install(project, *args, code=0):
    return run(project, "install", "--source", str(SOURCE), *args, code=code)


def test_portable_catalog_and_install(project):
    catalog = RUNNER.invoke(app, ["skills", "list", "--source", str(SOURCE)])
    assert catalog.exit_code == 0
    assert set(json.loads(catalog.output)) == {
        "bootstrap-project",
        "plan-task",
        "review-code",
        "git-branch",
        "git-commit",
        "pull-request",
        "grilling",
    }
    names = [
        "--skill",
        "bootstrap-project",
        "--skill",
        "plan-task",
        "--skill",
        "review-code",
    ]
    install(project, *names)
    install(project, *names)
    manifest = installation.read_state(installation_data(project))
    assert manifest["previous"]["files"] == {}
    assert set(manifest["current"]["files"]) == {
        "bootstrap-project",
        "plan-task",
        "review-code",
    }
    for name in manifest["current"]["files"]:
        assert (
            "disable-model-invocation: true"
            in installation.target(project, name).read_text()
        )


def test_collision_checked_before_install(project):
    existing = installation.target(project, "review-code")
    existing.parent.mkdir(parents=True)
    existing.write_text("Existing skill", encoding="utf-8")
    install(project, code=1)
    assert existing.read_text() == "Existing skill"
    assert not installation.target(project, "bootstrap-project").exists()


def test_update_rollback_uninstall_preserve_other_files(project, tmp_path):
    install(project, "--skill", "review-code")
    file = installation.target(project, "review-code")
    baseline = file.read_bytes()
    unrelated = file.parent / "notes.md"
    unrelated.write_text("Keep this", encoding="utf-8")
    source = tmp_path / "source"
    candidate = source / "skills" / "review-code" / "SKILL.md"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(
        (SOURCE / "skills" / "review-code" / "SKILL.md").read_bytes() + b"\nNew.\n"
    )
    run(project, "update", "--source", str(source))
    assert file.read_bytes().endswith(b"New.\n")
    run(project, "rollback")
    assert file.read_bytes() == baseline
    file.write_bytes(b"Local edit")
    run(project, "uninstall", code=1)
    assert file.read_bytes() == b"Local edit"
    file.write_bytes(baseline)
    run(project, "uninstall")
    assert not file.exists()
    assert unrelated.exists()


def test_recover_interrupted_install(project, monkeypatch):
    real_write = installation.atomic_write
    written = []

    def interrupt(path, data):
        if written:
            raise OSError("Interrupted")
        real_write(path, data)
        written.append(path)

    with monkeypatch.context() as patch:
        patch.setattr(installation, "atomic_write", interrupt)
        install(project, code=1)
    assert json.loads(run(project, "status").output)["interrupted"]
    install(project)
    records = json.loads(run(project, "status").output)
    assert not records["interrupted"]
    assert set(records["skills"].values()) == {"installed"}


def test_config_is_private_and_explicit(project, tmp_path):
    command = ("config", "set", "base_branch", "main", "--domain", "personal")
    run(project, *command, code=1)
    run(project, *command, "--approve")
    assert project_data(project, "personal").joinpath("conventions.yaml").is_file()
    assert json.loads(
        run(project, "config", "get", "base_branch", "--domain", "personal").output
    ) == {"base_branch": "main"}
    for other_project, domain in [(project, "work"), (tmp_path / "other", "personal")]:
        if other_project != project:
            subprocess.run(
                ["git", "init", str(other_project)], capture_output=True, check=True
            )
        response = run(
            other_project, "config", "get", "base_branch", "--domain", domain
        )
        assert json.loads(response.output) == {"base_branch": None}
    assert {item.name for item in project.iterdir()} == {".git"}


def test_discovery_does_not_execute_commands(project):
    (project / "README.md").write_text("make build\npytest\n", encoding="utf-8")
    response = json.loads(run(project, "discover", "--domain", "personal").output)
    assert response["base_branch"]["status"] == "unknown"
    assert [item["candidate"] for item in response["command_candidates"]] == [
        "make build",
        "pytest",
    ]
    assert project_data(project, "personal").joinpath("discovery.json").is_file()
