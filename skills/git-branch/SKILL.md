---
name: git-branch
description: Create a Git branch using approved project conventions and a verified base.
---

# git-branch

Inspect Git status, the current branch, and local base refs. With an authorized domain, query `nexus config get base_branch branch_prefix --domain <domain>`. Use the supplied ticket only when applicable. If the base or required naming component is unknown, ask before creating the branch. Validate with `git check-ref-format --branch`. Preserve outstanding work and avoid resets, forces, and automatic fetches. Report the new branch and base.
