# Architecture

The CLI validates inputs and invokes ordinary Python functions for local Git
discovery, configuration, and installation. The Claude Code adapter selects
the destination and adds explicit invocation metadata. The source checkout
provides the public skills. Installation uses a local source and requires no
model calls.

The OS user data directory (or an absolute `NEXUS_DATA_DIR` outside Git working
trees) stores conventions under
`domains/<domain>/conventions.yaml` and
`domains/<domain>/projects/<project-key>/conventions.yaml`. The project key is
the SHA-256 of the normalized canonical checkout path. Select the domain
explicitly. Project fields override domain fields. Only requested convention
fields are returned by `config get`.

Discovery saves a separate evidence report. Standard output shows counts and
evidence status by default. Detailed output is explicit, and raw commit
subjects are reduced to format counts. Source files and commands found in
them are evidence to evaluate. Nexus does not run those commands.

Installation state belongs to a physical checkout and is stored under
`installations/<project-key>/`. It is shared across domain selections because
Claude Code discovers the same installed public files in that checkout. The
manifest retains the current and previous snapshots. A pending record supports
retrying a partially applied file operation. Hash comparison detects local
changes. Before a mutation, Nexus validates the manifest structure, verifies
snapshot hashes, and checks affected destinations. The manifest stores validated
skill identifiers. Nexus derives destinations beneath the Claude Code skill
root. Hashes detect changes relative to local state. Source authenticity
depends on verifying the checkout independently. A writer that can replace the
manifest can also replace its hashes. A pending action resumes
only when its command is retried, using the recorded snapshot. Cooperating
Nexus processes serialize mutations per checkout. Keep other editors and
installers away from managed paths during a mutation.

Domain selection scopes normal Nexus operations. Storage is external to Git
working trees. Newly created private directories and files use owner-only
permissions on POSIX. Windows inherits ACLs from the data directory. Review
existing permissions and give each sensitive domain a dedicated account or
execution environment with restricted storage, processes, and network access.
The same OS user can choose another domain or read its files directly.
Invoking a skill may send selected context to its model provider. Skill
invocation metadata scopes context loading in Claude Code. OS and runtime
permissions govern file access.
