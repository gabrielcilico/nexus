"""Install versioned Claude Code skills and recover interrupted changes."""

import json
from pathlib import Path

from .adapters.claude_code import SKILL_ROOT, render
from .config import load_yaml
from .discovery import git
from .storage import atomic_write, checked, digest, locked, slug, write_json

EMPTY = {"revision": None, "files": {}}


def catalog(source: Path) -> dict[str, bytes]:
    root = source.resolve(strict=True)
    folder = checked(root, Path("skills"))
    result = {}
    for candidate in sorted(folder.iterdir()):
        name = slug(candidate.name)
        path = checked(root, Path("skills", name, "SKILL.md"))
        with path.open("rb") as stream:
            data = stream.read(131_073).replace(b"\r\n", b"\n")
        if len(data) > 131_072:
            raise ValueError(f"Skill exceeds 128 KiB: {name}")
        opening, metadata, body = data.split(b"---\n", 2)
        if opening or not body.strip():
            raise ValueError(f"Invalid skill document: {name}")
        header = load_yaml(metadata)
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
    revision = git(source, "rev-parse", "HEAD") or None
    if revision and git(
        source, "status", "--porcelain", "--untracked-files=all", "--", "skills"
    ):
        revision = None
    return {
        "revision": revision,
        "files": {
            name: {"sha256": digest(data), "text": data.decode("utf-8")}
            for name, data in contents.items()
        },
    }


def target(project: Path, name: str) -> Path:
    return checked(project, SKILL_ROOT / slug(name) / "SKILL.md")


def read_state(state: Path) -> dict:
    path = checked(state, Path("installation.json"))
    if not path.exists():
        return {"current": EMPTY, "previous": None, "pending": None}
    return json.loads(path.read_text(encoding="utf-8"))


def content_at(path: Path) -> bytes | None:
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError(f"Expected a regular file: {path}")
    with path.open("rb") as stream:
        return stream.read(131_200)


def scan(project: Path, before: dict, after: dict, *, recovery: bool) -> list:
    operations = []
    for name in sorted(before.keys() | after.keys()):
        path = target(project, name)
        original = before.get(name)
        desired = after.get(name)
        if not original and not recovery and path.parent.exists():
            raise ValueError(f"Skill directory already exists: {path.parent}")
        observed = content_at(path)
        current = digest(observed) if observed is not None else None
        old_hash = original["sha256"] if original else None
        new_hash = desired["sha256"] if desired else None
        allowed = {old_hash, new_hash} if recovery else {old_hash}
        if current not in allowed:
            raise ValueError(f"Installation conflict: {path}")
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
    write_json(path, {"current": after, "previous": before, "pending": None})


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
        selected = names or []
        if action == "update" and not selected:
            basis = (
                pending["next"]
                if pending and pending["action"] == "update"
                else record["current"]
            )
            selected = list(basis["files"])
        incoming = snapshot(source, selected) if source is not None else None
        if pending:
            finish(project, path, record)
            # A retry of the interrupted operation completes it once.
            if pending["action"] == action and (
                incoming is None or pending["next"] == incoming
            ):
                return
            record = read_state(state)
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
            write_json(path, record)
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
    }
