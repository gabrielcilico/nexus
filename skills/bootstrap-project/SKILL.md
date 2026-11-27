---
name: bootstrap-project
description: Discover local project conventions from Git, build files, CI, and repository documentation.
---

# bootstrap-project

Ask for the authorized domain identifier if it is missing. Run `nexus discover --domain <domain>` from the project. Use the report as an index and verify relevant evidence locally without executing discovered commands. Cover branch and commit practices, PR or MR templates and base refs, stack, build, test, lint, CI, documentation, agent instructions, and task tooling. Mark each convention confirmed, inferred, or unknown and give its evidence. Present proposed values before saving. After explicit approval, save only those values with `nexus config set <field> <value> --domain <domain> --approve`. Keep reports and conventions outside the repository and avoid promoting them to domain defaults.
