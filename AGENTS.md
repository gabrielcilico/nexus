# Nexus contributor instructions

Use English for source, public documentation, and commit messages. Keep the CLI
deterministic and local. Use synthetic fixtures and keep private data outside
repositories. Preserve pre-existing runtime files and require authorization for
external Git operations.

See [architecture](docs/architecture.md) for data and runtime boundaries and
[the v0.1 plan](docs/v0.1.md) for scope, status, and acceptance criteria.
Run `uv run --locked pytest` and `uv run --locked ruff check` before proposing changes.
