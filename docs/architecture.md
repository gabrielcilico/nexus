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

Installation state belongs to a physical checkout and is stored under
`installations/<project-key>/`. It is shared across domain selections because
Claude Code discovers the same installed public files in that checkout. The
manifest retains the current and previous snapshots. A pending record supports
retrying a partially applied file operation. Hash comparison detects local
changes. Cooperating Nexus processes serialize mutations per checkout. Keep
other editors and installers away from managed paths during a mutation.

These controls scope Nexus operations. A runtime running as the same OS user
can have broader access. Real domain separation requires external account,
filesystem, process, and network controls. Invoking a skill may send selected
context to its model provider. Autonomous orchestration, persistent knowledge
retrieval, and additional adapters are future work.
