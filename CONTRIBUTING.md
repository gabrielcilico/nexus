# Contributing

Use Python 3.12 or later and uv. Run `uv sync --locked`, then
`uv run --locked pytest`, `uv run --locked ruff check` and
`uv run --locked ruff format --check`.

Add portable skills under `skills/<name>/SKILL.md`. Use `name` and `description`
as frontmatter and keep runtime-specific controls in the adapter. The current
installer supports single-file skills. Use original content or document the
provenance and license of third-party material before proposing it.

Keep commits focused and use synthetic examples. Document material decisions
under `docs/decisions/`.
