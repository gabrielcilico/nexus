"""Inspect local evidence without fetching or running project commands."""

import os
import re
import subprocess
from pathlib import Path

from .storage import checked

FILES = {
    "documentation": ("README*", "docs/*.md"),
    "agent_instructions": (
        "AGENTS.md",
        "CLAUDE.md",
        ".claude/CLAUDE.md",
        ".cursor/rules/*.mdc",
    ),
    "pr_templates": (
        ".github/*PULL_REQUEST_TEMPLATE*",
        ".github/PULL_REQUEST_TEMPLATE/*.md",
        ".gitlab/merge_request_templates/*.md",
        "PULL_REQUEST_TEMPLATE.md",
    ),
    "ci": (
        ".github/workflows/*.yml",
        ".github/workflows/*.yaml",
        ".gitlab-ci.yml",
        "Jenkinsfile",
        "azure-pipelines.yml",
    ),
    "tooling": (
        "pyproject.toml",
        "package.json",
        "Cargo.toml",
        "go.mod",
        "Makefile",
        "pom.xml",
        "*.sln",
        "pytest.ini",
        "ruff.toml",
        "eslint.config.*",
    ),
    "task_tracking": (".github/ISSUE_TEMPLATE/*.yml", ".github/ISSUE_TEMPLATE/*.md"),
}
COMMAND = re.compile(
    r"^\s*(?:-\s+)?(?:run:\s+)?\x60?((?:uv run|npm run|pnpm|yarn|make|pytest|ruff|cargo|go test|dotnet test)\b[^\x60\r\n]{0,150})"
)


def git(project: Path, *args: str) -> str:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("GIT_")
    }
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    result = subprocess.run(
        ["git", "--no-pager", "-c", "core.fsmonitor=false", "-C", str(project), *args],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
        env=environment,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def project_root(path: Path) -> Path:
    root = git(path.resolve(strict=True), "rev-parse", "--show-toplevel")
    if not root:
        raise ValueError("Select a local Git working tree")
    return Path(root).resolve(strict=True)


def discover(project: Path) -> dict:
    evidence = []
    for category, patterns in FILES.items():
        paths = set()
        for pattern in patterns:
            for path in project.glob(pattern):
                relative = path.relative_to(project)
                try:
                    candidate = checked(project, relative)
                except ValueError:
                    continue
                if candidate.is_file():
                    paths.add(relative.as_posix())
        evidence.append(
            {
                "category": category,
                "status": "confirmed" if paths else "unknown",
                "files": sorted(paths)[:32],
            }
        )
    commands = []
    for item in evidence:
        if item["category"] not in {"ci", "documentation", "tooling"}:
            continue
        for filename in item["files"]:
            with checked(project, Path(filename)).open("rb") as stream:
                lines = (
                    stream.read(32_768).decode("utf-8", errors="replace").splitlines()
                )
            for number, line in enumerate(lines, 1):
                if match := COMMAND.match(line):
                    commands.append(
                        {
                            "candidate": match[1].strip(),
                            "file": filename,
                            "line": number,
                            "status": "inferred",
                        }
                    )
    default_ref = git(project, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    branches = git(
        project, "for-each-ref", "--count=20", "--format=%(refname:short)", "refs/heads"
    )
    subjects = git(project, "log", "-12", "--format=%s", "HEAD")
    return {
        "files": evidence,
        "layout": sorted(
            path.name for path in project.iterdir() if not path.name.startswith(".")
        )[:40],
        "command_candidates": commands[:30],
        "branches": branches.splitlines(),
        "recent_commit_subjects": [line[:160] for line in subjects.splitlines()],
        "base_branch": {
            "status": "inferred" if default_ref else "unknown",
            "candidate": default_ref.removeprefix("refs/remotes/origin/") or None,
            "source": "refs/remotes/origin/HEAD" if default_ref else None,
        },
    }
