"""Inspect local evidence without fetching or running project commands."""

import os
import re
import subprocess
from pathlib import Path

from .storage import checked, regular_file

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


def _run_git(project: Path, *args: str) -> bytes | None:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("GIT_")
    }
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    environment["GIT_NO_LAZY_FETCH"] = "1"
    environment["GIT_TERMINAL_PROMPT"] = "0"
    environment["GIT_ALLOW_PROTOCOL"] = ""
    result = subprocess.run(
        [
            "git",
            "--no-pager",
            "--no-replace-objects",
            "-c",
            "core.fsmonitor=false",
            "-C",
            str(project),
            *args,
        ],
        capture_output=True,
        timeout=10,
        env=environment,
        check=False,
    )
    return result.stdout if result.returncode == 0 else None


def git(project: Path, *args: str, require_success: bool = False) -> str:
    output = _run_git(project, *args)
    if output is None and require_success:
        raise ValueError("Git could not verify the source checkout")
    return (
        output.decode("utf-8", errors="replace").strip() if output is not None else ""
    )


def git_blob(project: Path, object_name: str, max_size: int) -> bytes | None:
    size = _run_git(project, "cat-file", "-s", object_name)
    if size is None or not size.strip().isdigit() or int(size) > max_size:
        return None
    return _run_git(project, "cat-file", "blob", object_name)


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
            directory, _, wildcard = pattern.rpartition("/")
            try:
                folder = checked(project, Path(directory))
            except ValueError:
                continue
            for path in folder.glob(wildcard):
                relative = Path(directory, path.name)
                try:
                    available = regular_file(checked(project, relative))
                except ValueError:
                    continue
                if available:
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
    subjects = git(project, "log", "-12", "--format=%s", "HEAD").splitlines()
    conventional = re.compile(r"^[a-z]+(?:\([^)]*\))?!?: ")
    return {
        "files": evidence,
        "layout": sorted(
            path.name for path in project.iterdir() if not path.name.startswith(".")
        )[:40],
        "command_candidates": commands[:30],
        "branches": branches.splitlines(),
        "commit_format": {
            "source": "latest 12 local commit subjects",
            "sample_size": len(subjects),
            "conventional_matches": sum(
                bool(conventional.match(line)) for line in subjects
            ),
            "status": "inferred" if subjects else "unknown",
        },
        "base_branch": {
            "status": "inferred" if default_ref else "unknown",
            "candidate": default_ref.removeprefix("refs/remotes/origin/") or None,
            "source": "refs/remotes/origin/HEAD" if default_ref else None,
        },
    }


def summarize(report: dict) -> dict:
    return {
        "files": [
            {
                "category": item["category"],
                "status": item["status"],
                "count": len(item["files"]),
            }
            for item in report["files"]
        ],
        "command_candidate_count": len(report["command_candidates"]),
        "branch_count": len(report["branches"]),
        "commit_format": report["commit_format"],
        "base_branch_status": report["base_branch"]["status"],
    }
