# Nexus

Nexus installs reusable agent skills and stores approved project conventions
locally. The first runtime is Claude Code.

## Local pilot

Install Git, Python 3.12 or later, uv, and Claude Code. From the Nexus checkout,
install the local CLI on your PATH with `uv tool install .`. For development,
use `uv sync --locked` and `uv run --locked nexus`.

```sh
nexus doctor
nexus skills list --source .
nexus install --source . --project /path/to/test-project --skill bootstrap-project --skill plan-task --skill review-code
nexus status --project /path/to/test-project
```

Start Claude Code in the test Git project. Invoke `/bootstrap-project` with an
authorized domain identifier such as `personal`. Review its evidence and approve
only the conventions you want to retain. Invoke `/plan-task` or `/review-code`
with the same domain when those workflows need project conventions.

To save and read an example convention directly, run these commands from the
test project.

```sh
nexus config set base_branch main --domain personal --approve
nexus config get base_branch --domain personal
```

Use a trusted, clean tag or commit checkout as `--source` when pinning a
version. `nexus update` retains the installed selection by default. Repeat
`--skill` to replace that selection. `nexus rollback` restores the previous
snapshot. `nexus uninstall` removes matching managed skill files, preserving
other files and reporting conflicts. With either command, `--project` points
to the target checkout.

If `nexus status` reports a pending action, retry that action for the same
checkout. Nexus resumes the recorded snapshot before accepting a new action.
If a managed file was edited or removed, restore its exact installed contents
before retrying. Preserve malformed manifests and restore them from a trusted
backup.

Project conventions and discovery reports are stored in the OS user data
directory outside Git working trees. `nexus discover --domain personal` prints
a summary. Use `--show-evidence` only in a terminal or agent session authorized
to receive private paths, branch names, and command candidates. Quote paths
with spaces passed to `--project` or `--source`.

See [the v0.1 plan](docs/v0.1.md) and [architecture](docs/architecture.md).
Use the [authenticated pilot](docs/claude-code-pilot.md) to validate the three
skills end to end in a disposable checkout.
Nexus is licensed under [Apache 2.0](LICENSE).
