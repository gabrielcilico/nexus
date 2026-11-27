"""Install versioned Claude Code skills and recover interrupted changes."""

import json
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from .adapters.claude_code import SKILL_ROOT, render
from .config import load_yaml
from .discovery import git
from .storage import atomic_write, checked, digest, locked, regular_file, slug

EMPTY = {"revision": None, "files": {}}
MAX_SKILL = 128 * 1024
MAX_INSTALLED = MAX_SKILL + 64
MAX_MANIFEST = 32 * 1024 * 1024
Hash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Revision = Annotated[str, StringConstraints(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")]


def skill_name(name: str) -> str:
    if slug(name) in {"synced", "anthropic-skills"}:
        raise ValueError("Reserved Claude Code skill name")
    return name


class ManagedFile(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    sha256: Hash
    text: Annotated[str, StringConstraints(max_length=MAX_INSTALLED)]


class Snapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    revision: Revision | None
    files: dict[str, ManagedFile]

    @model_validator(mode="after")
    def verify_files(self):
        for name, item in self.files.items():
            skill_name(name)
            data = item.text.encode("utf-8")
            if len(data) > MAX_INSTALLED or digest(data) != item.sha256:
                raise ValueError("Invalid snapshot content")
        return self


class Pending(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    action: Literal["install", "update", "uninstall", "rollback"]
    next: Snapshot


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    current: Snapshot
    previous: Snapshot | None
    pending: Pending | None

    @model_validator(mode="after")
    def verify_transition(self):
        if self.pending is None:
            return self
        action, next_state = self.pending.action, self.pending.next
        required_current = action == "update"
        if (
            next_state == self.current
            or (action in {"install", "update"} and not next_state.files)
            or (action == "install" and self.current.files)
            or (required_current and not self.current.files)
            or (action == "uninstall" and next_state.model_dump() != EMPTY)
            or (action == "rollback" and next_state != self.previous)
        ):
            raise ValueError("Invalid pending operation")
        return self


def catalog(source: Path) -> dict[str, bytes]:
    root = source.resolve(strict=True)
    folder = checked(root, Path("skills"))
    result = {}
    for candidate in sorted(folder.iterdir()):
        name = skill_name(candidate.name)
        path = checked(root, Path("skills", name, "SKILL.md"))
        if not regular_file(path):
            raise ValueError(f"Missing SKILL.md for {name}")
        with path.open("rb") as stream:
            raw = stream.read(MAX_SKILL + 1)
        if len(raw) > MAX_SKILL:
            raise ValueError(f"Skill exceeds 128 KiB: {name}")
        data = raw.replace(b"\r\n", b"\n")
        metadata, separator, body = data[4:].partition(b"\n---\n")
        if not data.startswith(b"---\n") or not separator or not body.strip():
            raise ValueError(f"Invalid skill document: {name}")
        try:
            data.decode("utf-8")
            header = load_yaml(metadata)
        except (ValueError, yaml.YAMLError):
            raise ValueError(f"Invalid UTF-8 or YAML in skill: {name}") from None
        if (
            not isinstance(header, dict)
            or set(header) != {"name", "description"}
            or header["name"] != name
            or not isinstance(header["description"], str)
            or not header["description"].strip()
        ):
            raise ValueError(f"Invalid skill metadata: {name}")
        result[name] = data
    if not result:
        raise ValueError("The source contains no skills")
    return result


def snapshot(source: Path, names: list[str]) -> dict:
    available = catalog(source)
    chosen = names or list(available)
    for name in chosen:
        if name not in available:
            raise ValueError(f"Unknown skill: {name}")
    contents = {name: render(available[name]) for name in chosen}
    root = git(source, "rev-parse", "--show-toplevel")
    revision = None
    if root and Path(root).resolve() == source.resolve():
        tracked = set(
            git(
                source, "ls-tree", "-r", "--name-only", "HEAD", "--", "skills"
            ).splitlines()
        )
        expected = {f"skills/{name}/SKILL.md" for name in chosen}
        if expected <= tracked and not git(
            source,
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            "skills",
            require_success=True,
        ):
            revision = git(source, "rev-parse", "HEAD") or None
    return {
        "revision": revision,
        "files": {
            name: {"sha256": digest(data), "text": data.decode("utf-8")}
            for name, data in contents.items()
        },
    }


def target(project: Path, name: str) -> Path:
    return checked(project, SKILL_ROOT / skill_name(name) / "SKILL.md")


def unique_object(pairs):
    data = dict(pairs)
    if len(data) != len(pairs):
        raise ValueError("Duplicate manifest key")
    return data


def read_state(state: Path) -> dict:
    path = checked(state, Path("installation.json"))
    if not regular_file(path):
        return {"current": EMPTY, "previous": None, "pending": None}
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_MANIFEST + 1)
        if len(data) > MAX_MANIFEST:
            raise ValueError("Manifest is too large")
        record = json.loads(data, object_pairs_hook=unique_object)
        return Manifest.model_validate(record).model_dump()
    except (ValueError, RecursionError):
        raise ValueError(
            "Invalid installation manifest. Preserve it and restore a trusted backup before retrying."
        ) from None


def save_state(path: Path, record: dict) -> None:
    data = (json.dumps(record, indent=2, sort_keys=True) + "\n").encode()
    if len(data) > MAX_MANIFEST:
        raise ValueError("Installation manifest would exceed 32 MiB")
    atomic_write(path, data)


def content_at(path: Path) -> bytes | None:
    if not regular_file(path):
        return None
    with path.open("rb") as stream:
        return stream.read(MAX_INSTALLED + 1)


def scan(project: Path, before: dict, after: dict, *, recovery: bool) -> list:
    operations = []
    for name in sorted(before.keys() | after.keys()):
        path = target(project, name)
        original = before.get(name)
        desired = after.get(name)
        if not original and not recovery and path.parent.exists():
            raise ValueError(f"Skill directory already exists: {name}")
        observed = content_at(path)
        current = digest(observed) if observed is not None else None
        old_hash = original["sha256"] if original else None
        new_hash = desired["sha256"] if desired else None
        allowed = {old_hash, new_hash} if recovery else {old_hash}
        if current not in allowed:
            raise ValueError(
                f"Installed skill is missing or changed: {name}. Restore its exact contents before retrying."
            )
        if current != new_hash:
            data = desired["text"].encode("utf-8") if desired else None
            operations.append((path, data))
    return operations


def finish(project: Path, path: Path, record: dict) -> None:
    pending = record["pending"]
    before = record["current"]
    after = pending["next"]
    for destination, data in scan(
        project, before["files"], after["files"], recovery=True
    ):
        if data is None:
            destination.unlink()
            if not any(destination.parent.iterdir()):
                destination.parent.rmdir()
        else:
            atomic_write(destination, data)
    save_state(path, {"current": after, "previous": before, "pending": None})


def change(
    project: Path,
    state: Path,
    action: str,
    source: Path | None = None,
    names: list[str] | None = None,
) -> None:
    path = checked(state, Path("installation.json"))
    with locked(checked(state, Path("installation.lock"))):
        record = read_state(state)
        pending = record["pending"]
        if pending:
            if pending["action"] != action:
                raise ValueError(
                    f"Interrupted {pending['action']}. Retry that command first."
                )
            finish(project, path, record)
            return
        selected = names or []
        if action == "update" and not selected:
            selected = list(record["current"]["files"])
        incoming = snapshot(source, selected) if source is not None else None
        current = record["current"]
        if action == "install" and current["files"] and incoming != current:
            raise ValueError("Skills are already installed. Use update.")
        if action == "update" and not current["files"]:
            raise ValueError("Install skills before updating")
        next_state = {
            "install": incoming,
            "update": incoming,
            "uninstall": EMPTY,
            "rollback": record["previous"],
        }[action]
        if next_state is None:
            raise ValueError("No previous installation is available")
        scan(project, current["files"], next_state["files"], recovery=False)
        if next_state != current:
            record["pending"] = {"action": action, "next": next_state}
            save_state(path, record)
            finish(project, path, record)


def status(project: Path, state: Path) -> dict:
    record = read_state(state)
    current = record["current"]
    files = {}
    for name, item in current["files"].items():
        path = target(project, name)
        data = content_at(path)
        files[name] = (
            "missing"
            if data is None
            else ("installed" if digest(data) == item["sha256"] else "modified")
        )
    return {
        "revision": current["revision"],
        "skills": files,
        "interrupted": record["pending"] is not None,
        "pending_action": record["pending"]["action"] if record["pending"] else None,
    }
