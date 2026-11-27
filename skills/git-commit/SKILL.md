---
name: git-commit
description: Prepare and create a Git commit for the authorized change scope.
---

# git-commit

Inspect staged and unstaged diffs separately. With an authorized domain, query `nexus config get commit_language --domain <domain>` and check repository evidence for commit format. Identify unrelated staged changes and pause if they would be included. Review the prospective commit for secrets and private material without echoing their values. Stage only authorized paths or hunks. Commit when authorized, then report the commit and test results.
