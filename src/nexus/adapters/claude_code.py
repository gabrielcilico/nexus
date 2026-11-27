"""Claude Code project installation layout."""

from pathlib import Path

SKILL_ROOT = Path(".claude", "skills")


def render(contents: bytes) -> bytes:
    head, body = contents.split(b"\n---\n", 1)
    return head + b"\ndisable-model-invocation: true\n---\n" + body
