# Authenticated Claude Code pilot

Use PowerShell from the Nexus checkout and an account authorized to process
synthetic data. This pilot starts Claude Code with a fresh configuration
directory. Sign in manually with `/login` if prompted. Credentials already
exported for Anthropic or an alternate Claude Code provider are omitted from
the child environment. The script creates a temporary Git checkout, seeds a
separate synthetic domain, and cleans up the checkout, data, and Claude
profile when the session exits or the script fails.

Install the local CLI once with `uv tool install .`. Then run the following
from the Nexus checkout.

```powershell
@'
import json
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

source = Path.cwd()
nexus = shutil.which("nexus")
claude = shutil.which("claude")
if not nexus or not claude:
    raise SystemExit("Put nexus and claude on PATH before running the pilot.")

owned = Path(tempfile.mkdtemp(prefix="nexus-pilot-")).resolve()
cleanup = str(owned)
if os.name == "nt":
    cleanup = "\\\\?\\UNC\\" + cleanup[2:] if cleanup.startswith("\\\\") else "\\\\?\\" + cleanup

def remove_readonly(remove, filename, error):
    path = Path(filename)
    if (os.name == "nt" and isinstance(error, PermissionError)
            and path.is_relative_to(Path(cleanup))):
        info = path.lstat()
        if (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                and not info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            path.chmod(stat.S_IWRITE)
            remove(filename)
            return
    raise error

try:
    project = owned / "pilot project"
    project.mkdir()
    environment = {
        key: value for key, value in os.environ.items()
        if not key.upper().startswith(("ANTHROPIC_", "CLAUDE_CODE_", "GIT_"))
    }
    environment.update(
        NEXUS_DATA_DIR=str(owned / "nexus-data"),
        CLAUDE_CONFIG_DIR=str(owned / "claude-profile"),
        GIT_CONFIG_GLOBAL=str(owned / "git-config"),
        GIT_CONFIG_NOSYSTEM="1",
    )

    def run(*args, **options):
        return subprocess.run(args, cwd=project, env=environment, check=True, **options)

    def read_field(field, domain):
        result = run(nexus, "config", "get", field, "--domain", domain, capture_output=True)
        return json.loads(result.stdout)[field]

    run("git", "init", "-b", "main")
    (project / "README.md").write_text(
        "# Synthetic Calculator\n\nTest with \x60python -m unittest\x60.\n"
        "\nBase branch: \x60main\x60.\n", encoding="utf-8"
    )
    (project / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    unrelated = project / "UNRELATED.md"
    sentinel = b"Keep the synthetic fixture unchanged.\n"
    unrelated.write_bytes(sentinel)
    run("git", "add", "--", "README.md", "calc.py", "UNRELATED.md")
    run(
        "git", "-c", "user.name=Nexus Pilot", "-c", "user.email=pilot@example.invalid",
        "-c", "commit.gpgsign=false", "-c", "core.hooksPath=.git/no-hooks",
        "commit", "-m", "Add synthetic calculator",
    )
    run("git", "update-ref", "refs/remotes/origin/main", "HEAD")
    run("git", "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    (project / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    run(nexus, "config", "set", "commit_language", "synthetic-other-domain",
        "--domain", "other", "--approve")
    assert read_field("commit_language", "pilot") is None
    assert read_field("base_branch", "pilot") is None

    run(nexus, "install", "--source", str(source), "--skill", "bootstrap-project",
        "--skill", "plan-task", "--skill", "review-code")
    installed_tree = run("git", "status", "--porcelain", "--untracked-files=all",
                         capture_output=True).stdout

    print("Follow the manual steps below. Use /exit after completing all checks.", flush=True)
    run(claude, "--setting-sources", "project")

    assert read_field("base_branch", "pilot") == "main", "Approved convention was not saved"
    assert read_field("commit_language", "pilot") is None
    assert read_field("commit_language", "other") == "synthetic-other-domain"
    assert unrelated.read_bytes() == sentinel
    run(nexus, "uninstall")
    assert run("git", "status", "--porcelain", "--untracked-files=all",
               capture_output=True).stdout == b" M calc.py\n"
    assert b".claude/skills/" in installed_tree
    print("Convention, domain, and working-tree checks passed.")
finally:
    shutil.rmtree(cleanup, onexc=remove_readonly)
'@ | uv run --locked python -
```

## In the Claude Code session

1. If prompted, enter `/login` and complete sign-in yourself. Type `/` and
   confirm that the three pilot skills are listed.
2. Enter `/bootstrap-project domain pilot. Discover conventions and propose the base branch. Wait for my approval.`
   Confirm it cites evidence for `main` and asks before writing. If it asks for
   permission to view detailed evidence, authorize it for this synthetic
   checkout. Approve only `base_branch=main` in domain `pilot`.
3. Enter `/plan-task domain pilot. Give a short plan to add calculator unit tests. Read base_branch only and make no edits.`
   Confirm the tool call requests only that field and uses domain `pilot`.
4. Enter `/review-code domain pilot. Review the working-tree diff against the approved base branch. Read base_branch only and make no edits.`
   Confirm it reports the arithmetic regression in `calc.py`. Observe that
   neither workflow queries domain `other` or includes its convention.
5. Enter `/exit`. The script verifies persistence and working-tree state,
   then removes the directory it created. An immediate process kill or
   power loss can leave that temporary directory for manual cleanup.

The cross-domain check verifies the observed CLI and agent workflow. OS
permissions are required to prevent direct access from another process
running under the same account.
