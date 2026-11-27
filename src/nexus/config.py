"""Read approved conventions from the selected domain and project."""

from pathlib import Path
from typing import Annotated

import yaml
from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError

from .storage import atomic_write, checked, regular_file

Text = Annotated[str, StringConstraints(min_length=1, max_length=256)]


class Conventions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    base_branch: Text | None = None
    branch_prefix: Text | None = None
    commit_language: Text | None = None
    pr_language: Text | None = None
    build_command: Text | None = None
    test_command: Text | None = None
    lint_command: Text | None = None


class UniqueLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        result = super().construct_mapping(node, deep=deep)
        if len(result) != len(node.value):
            raise ValueError("Duplicate YAML mapping key")
        return result


def load_yaml(source: bytes):
    if len(source) > 65_536:
        raise ValueError("YAML input exceeds 64 KiB")
    depth = 0
    for event in yaml.parse(source, Loader=UniqueLoader):
        if getattr(event, "anchor", None) is not None:
            raise ValueError("YAML anchors and aliases are unsupported")
        if isinstance(event, (yaml.MappingStartEvent, yaml.SequenceStartEvent)):
            depth += 1
            if depth > 16:
                raise ValueError("YAML nesting exceeds 16 levels")
        if isinstance(event, (yaml.MappingEndEvent, yaml.SequenceEndEvent)):
            depth -= 1
    return yaml.load(source, Loader=UniqueLoader)


def read_conventions(path: Path) -> dict:
    if not regular_file(path):
        return {}
    try:
        with path.open("rb") as stream:
            values = load_yaml(stream.read(65_537))
        return Conventions.model_validate(values).model_dump(exclude_unset=True)
    except (ValueError, yaml.YAMLError):
        raise ValueError(
            "Invalid conventions.yaml. Check its YAML and supported fields locally."
        ) from None


def effective(state: Path) -> dict:
    domain = state.parent.parent
    return read_conventions(
        checked(domain, Path("conventions.yaml"))
    ) | read_conventions(checked(state, Path("conventions.yaml")))


def set_convention(state: Path, field: str, value: str) -> None:
    path = checked(state, Path("conventions.yaml"))
    values = read_conventions(path) | {field: value}
    try:
        validated = Conventions.model_validate(values).model_dump(exclude_unset=True)
    except ValidationError:
        raise ValueError(
            "A convention value must contain 1 to 256 characters"
        ) from None
    atomic_write(path, yaml.safe_dump(validated).encode("utf-8"))
