# Security

Keep credentials and private project data outside source checkouts. Use an
authorized runtime account when invoking a skill that reads project context.
Run discovery only against projects you are authorized to inspect.

Use separate OS accounts or isolated execution environments for sensitive
domains. Restrict access to the data directory and its backups. Windows
deployments should verify inherited ACLs. Treat discovery evidence as private
and review it before displaying it in an agent session. Keep the checkout
and state free of concurrent changes by other tools during a skill update.

Report vulnerabilities using the repository's private vulnerability reporting
feature when available. Keep credentials and private reproduction data out of
public issues.
