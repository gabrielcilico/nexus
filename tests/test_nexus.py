import json
import os
import subprocess
from pathlib import Path
from stat import S_IMODE

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
        if path.name != "SKILL.md":
            return real_write(path, data)
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
    response = json.loads(
        run(project, "discover", "--domain", "personal", "--show-evidence").output
    )
    assert response["base_branch"]["status"] == "unknown"
    assert [item["candidate"] for item in response["command_candidates"]] == [
        "make build",
        "pytest",
    ]
    assert project_data(project, "personal").joinpath("discovery.json").is_file()


@pytest.mark.parametrize(
    "failure", ["syntax", "schema", "hash", "duplicate", "skill-name", "path"]
)
def test_corrupt_manifest_stops_before_changes(project, failure):
    install(project, "--skill", "plan-task")
    manifest = installation_data(project) / "installation.json"
    record = json.loads(manifest.read_bytes())
    file = installation.target(project, "plan-task")
    before = file.read_bytes()
    if failure == "syntax":
        data = "{"
    elif failure == "schema":
        data = "[]"
    elif failure == "duplicate":
        data = '{"pending":null,' + manifest.read_text().lstrip()[1:]
    elif failure == "hash":
        record["current"]["files"]["plan-task"]["text"] = "Changed snapshot"
        data = json.dumps(record)
    elif failure == "skill-name":
        record["current"]["files"]["nested/plan-task"] = record["current"]["files"].pop(
            "plan-task"
        )
        data = json.dumps(record)
    else:
        record["current"]["files"]["plan-task"]["path"] = "notes.md"
        data = json.dumps(record)
    manifest.write_text(data, encoding="utf-8")
    for action in ("status", "update", "rollback", "uninstall"):
        response = run(project, action, code=1)
        assert "Invalid installation manifest" in response.output
    assert file.read_bytes() == before
    assert manifest.read_text() == data


@pytest.mark.parametrize("state", ["missing", "modified", "directory"])
def test_destination_drift_blocks_batch(project, state):
    install(project, "--skill", "plan-task", "--skill", "review-code")
    changed = installation.target(project, "review-code")
    unaffected = installation.target(project, "plan-task")
    changed.unlink()
    if state == "modified":
        changed.write_text("Manual edit", encoding="utf-8")
    elif state == "directory":
        changed.mkdir()
    manifest = installation_data(project) / "installation.json"
    before = manifest.read_bytes()
    run(project, "uninstall", code=1)
    assert unaffected.is_file()
    assert manifest.read_bytes() == before


def test_interrupted_update_requires_matching_operation(project, tmp_path, monkeypatch):
    install(project, "--skill", "plan-task", "--skill", "review-code")
    source = tmp_path / "replacement source"
    for name in ("plan-task", "review-code"):
        path = source / "skills" / name / "SKILL.md"
        path.parent.mkdir(parents=True)
        path.write_bytes(
            (SOURCE / "skills" / name / "SKILL.md").read_bytes() + b"\nNew.\n"
        )

    real_write = installation.atomic_write

    def fail_second_skill(path, data):
        if path.name == "SKILL.md" and path.parent.name == "review-code":
            raise PermissionError(13, "Permission denied")
        real_write(path, data)

    with monkeypatch.context() as patch:
        patch.setattr(installation, "atomic_write", fail_second_skill)
        failed = run(project, "update", "--source", str(source), code=1)
        assert "Check permissions and paths" in failed.output
    ready = installation.target(project, "plan-task")
    waiting = installation.target(project, "review-code")
    before_waiting = waiting.read_bytes()
    assert ready.read_bytes().endswith(b"New.\n")
    assert json.loads(run(project, "status").output)["pending_action"] == "update"
    rejected = run(project, "uninstall", code=1)
    assert "Retry that command first" in rejected.output
    assert waiting.read_bytes() == before_waiting
    run(project, "update", "--source", str(tmp_path / "unavailable source"))
    assert waiting.read_bytes().endswith(b"New.\n")
    run(project, "rollback")
    assert waiting.read_bytes() == before_waiting


def test_discovery_limits_output_and_persists_evidence(project):
    marker = "synthetic-private-marker"
    (project / "README.md").write_text(f"make {marker}\n", encoding="utf-8")
    response = run(project, "discover", "--domain", "personal")
    assert marker not in response.output
    assert json.loads(response.output)["command_candidate_count"] == 1
    state = project_data(project, "personal")
    report = state / "discovery.json"
    assert marker in report.read_text(encoding="utf-8")
    detailed = run(project, "discover", "--domain", "personal", "--show-evidence")
    assert marker in detailed.output
    if os.name == "posix":
        assert S_IMODE(report.stat().st_mode) == 0o600
        assert S_IMODE(state.stat().st_mode) == 0o700


def test_config_errors_omit_private_values(project):
    state = project_data(project, "work")
    state.mkdir(parents=True)
    path = state / "conventions.yaml"
    path.write_text("test_command: [synthetic-private-value]\n", encoding="utf-8")
    response = run(project, "config", "get", "test_command", "--domain", "work", code=1)
    assert "Invalid conventions.yaml" in response.output
    assert "synthetic-private-value" not in response.output


def test_private_data_cannot_use_a_working_tree(project, monkeypatch):
    monkeypatch.setenv("NEXUS_DATA_DIR", str(project / "private"))
    run(project, "discover", "--domain", "personal", code=1)
    assert not (project / "private").exists()


def test_installer_rejects_linked_skill_directory(project, tmp_path):
    outside = tmp_path / "separate directory"
    outside.mkdir()
    skills = project / ".claude" / "skills"
    skills.parent.mkdir()
    if os.name == "nt":
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                (
                    "New-Item -ItemType Junction -Path $env:NEXUS_TEST_LINK -Target "
                    "$env:NEXUS_TEST_LINK_TARGET -ErrorAction Stop | Out-Null"
                ),
            ],
            env=os.environ
            | {"NEXUS_TEST_LINK": str(skills), "NEXUS_TEST_LINK_TARGET": str(outside)},
            capture_output=True,
            check=False,
        )
        if result.returncode:
            pytest.skip("Junction creation is unavailable on this host")
    else:
        skills.symlink_to(outside, target_is_directory=True)
    response = install(project, "--skill", "plan-task", code=1)
    assert "Linked path" in response.output
    assert not list(outside.iterdir())


def test_invalid_source_and_destination(project, tmp_path):
    source = tmp_path / "invalid source"
    bad = source / "skills" / "plan-task" / "SKILL.md"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(b"---\nname: plan-task\ndescription: Example.\n---\n\xff")
    run(project, "install", "--source", str(source), code=1)
    run(tmp_path / "missing project", "install", "--source", str(SOURCE), code=1)
    assert not (project / ".claude").exists()


def test_uninstall_preserves_hard_linked_file(project, tmp_path):
    install(project, "--skill", "plan-task")
    managed = installation.target(project, "plan-task")
    separate = tmp_path / "copy.md"
    original = managed.read_bytes()
    os.link(managed, separate)
    run(project, "uninstall", code=1)
    assert managed.read_bytes() == separate.read_bytes() == original


def test_nested_source_has_no_parent_git_revision(project):
    source = project / "nested source"
    skill = source / "skills" / "plan-task" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_bytes((SOURCE / "skills" / "plan-task" / "SKILL.md").read_bytes())
    subprocess.run(
        [
            "git",
            "-C",
            str(project),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--allow-empty",
            "-m",
            "Synthetic commit",
        ],
        capture_output=True,
        check=True,
    )
    assert installation.snapshot(source, ["plan-task"])["revision"] is None


@pytest.fixture
def committed_skill(project):
    def git(*args):
        return subprocess.run(
            ["git", "-C", str(project), *args], capture_output=True, check=True
        ).stdout.strip()

    path = project / "skills/plan-task/SKILL.md"
    path.parent.mkdir(parents=True)
    contents = (
        (SOURCE / "skills/plan-task/SKILL.md").read_bytes().replace(b"\r\n", b"\n")
    )
    path.write_bytes(contents)
    git("config", "core.autocrlf", "true")
    git("add", "skills/plan-task/SKILL.md")
    git(
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-m",
        "Add synthetic skill",
    )
    return git, path, contents


@pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
def test_index_flags_do_not_label_changed_skill_as_committed(
    project, committed_skill, flag
):
    git, path, contents = committed_skill
    relative = "skills/plan-task/SKILL.md"
    git("update-index", flag, relative)
    path.write_bytes(contents + b"\nChanged skill text.\n")
    assert git("status", "--porcelain", "--", "skills") == b""
    before = (project / ".git/index").read_bytes()
    snapshot = installation.snapshot(project, ["plan-task"])
    assert snapshot["revision"] is None
    assert snapshot["files"]["plan-task"]["text"].endswith("Changed skill text.\n")
    assert (project / ".git/index").read_bytes() == before


def test_matching_crlf_skill_keeps_commit_revision(project, committed_skill):
    git, path, contents = committed_skill
    git("update-index", "--assume-unchanged", "skills/plan-task/SKILL.md")
    path.write_bytes(contents.replace(b"\n", b"\r\n"))
    assert installation.snapshot(project, ["plan-task"])["revision"] == git(
        "rev-parse", "HEAD"
    ).decode("ascii")


@pytest.mark.parametrize("removal", ["uninstall", "update"])
@pytest.mark.parametrize("occupied", [False, True])
def test_rollback_preserves_unmanaged_skill_directory(project, removal, occupied):
    install(project, "--skill", "plan-task")
    managed = installation.target(project, "plan-task")
    contents = managed.read_bytes()
    note = managed.parent / "notes.md"
    note.write_bytes(b"Unmanaged notes.")
    if removal == "update":
        run(project, "update", "--source", str(SOURCE), "--skill", "review-code")
    else:
        run(project, "uninstall")
    assert not managed.exists()
    assert note.read_bytes() == b"Unmanaged notes."
    if occupied:
        managed.write_bytes(contents)
        run(project, "rollback", code=1)
        assert set(json.loads(run(project, "status").output)["skills"]) == (
            {"review-code"} if removal == "update" else set()
        )
    else:
        run(project, "rollback")
        assert json.loads(run(project, "status").output)["skills"] == {
            "plan-task": "installed"
        }
    assert managed.read_bytes() == contents
    assert note.read_bytes() == b"Unmanaged notes."
    if not occupied:
        note.unlink()
        run(project, "uninstall")
        assert managed.parent.is_dir()
        install(project, "--skill", "plan-task")


def test_subdirectory_and_doctor(project):
    working_dir = project / "folder with spaces"
    working_dir.mkdir()
    install(project, "--skill", "plan-task")
    assert json.loads(run(working_dir, "status").output)["skills"] == {
        "plan-task": "installed"
    }
    response = RUNNER.invoke(app, ["doctor"])
    assert response.exit_code == 0
    assert set(json.loads(response.output)) == {"git", "claude", "uv"}
