---
name: review-code
description: Review a working tree or diff for defects, regressions, security issues, and test gaps.
---

# review-code

Establish the diff and acceptance criteria. If the scope or validation
depends on a convention the session may read, fetch only that field with
`nexus config get <field> --domain <domain>` from the selected checkout.
Use `--project` with a quoted path when working elsewhere.

Trace affected callers and verify concrete failures when possible. Report
findings by severity with file, line, triggering conditions, and impact.
Record the checks run and material gaps.
