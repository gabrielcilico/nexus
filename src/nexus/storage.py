"""Path and state primitives shared by the local commands."""

import hashlib
import json
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path

from platformdirs import user_data_path

SLUG = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")
RESERVED = {"con", "prn", "aux", "nul"} | {
    f"{prefix}{number}" for prefix in ("com", "lpt") for number in range(1, 10)
}


def slug(value: str) -> str:
    if len(value) > 64 or not SLUG.fullmatch(value) or value in RESERVED:
        raise ValueError(f"Invalid identifier: {value}")
    return value


def checked(root: Path, relative: Path) -> Path:
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Invalid relative path: {relative}")
    path = root
    for part in relative.parts:
        path = native_path(path / part)
        if (
            path.is_symlink()
            or path.is_junction()
            or not native_path(path.resolve()).is_relative_to(native_path(root))
        ):
            raise ValueError(f"Linked path is not supported: {path}")
    return path


def native_path(path: Path) -> Path:
    if os.name != "nt" or path.drive.startswith("\\\\?\\"):
        return path
    name = str(path)
    if name.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + name[2:])
    return Path("\\\\?\\" + name)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def data_root(project: Path) -> Path:
    override = os.environ.get("NEXUS_DATA_DIR")
    path = Path(override) if override else user_data_path("nexus", appauthor=False)
    if not path.is_absolute():
        raise ValueError("NEXUS_DATA_DIR must be an absolute path")
    root = path.resolve()
    if root.is_relative_to(project) or project.is_relative_to(root):
        raise ValueError("Nexus data and project directories must be separate")
    if any((ancestor / ".git").exists() for ancestor in (root, *root.parents)):
        raise ValueError("Nexus data must be stored outside Git working trees")
    return root


def project_key(project: Path) -> str:
    return digest(os.fsencode(os.path.normcase(project)))


def project_data(project: Path, domain: str) -> Path:
    return checked(
        data_root(project),
        Path("domains", slug(domain), "projects", project_key(project)),
    )


def installation_data(project: Path) -> Path:
    return checked(data_root(project), Path("installations", project_key(project)))


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def write_json(path: Path, data: object) -> None:
    atomic_write(path, (json.dumps(data, indent=2, sort_keys=True) + "\n").encode())


@contextmanager
def locked(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    # OS locks are released if the process exits unexpectedly.
    with path.open("a+b") as stream:
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
