---
name: plan-task
description: Plan a project change in small steps with verifiable outcomes.
---

# plan-task

When the selected domain is known and authorized, query `nexus config get base_branch build_command test_command lint_command --domain <domain>` for relevant fields. Inspect the affected entry points and nearby tests. State the outcome, implementation steps, and how to verify each risky change. For a small change, keep the plan to a few lines. Surface only decisions that materially change scope or behavior.
