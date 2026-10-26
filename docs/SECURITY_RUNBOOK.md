# Security Runbook

Use this runbook for production operations and security maintenance.

## Secrets

Required production secrets:

- `DATABASE_URL`
- `JWT_SECRET`
- `FILE_SIGNING_SECRET`
- `INITIAL_ADMIN_PASSWORD`
- email provider or SMTP credentials

Rules:

1. Use unique high-entropy values for every secret.
2. Do not reuse `JWT_SECRET` as `FILE_SIGNING_SECRET`.
3. Rotate secrets after staff turnover, suspected exposure, or provider compromise.
4. Store secrets only in the deployment provider's secret manager or an approved vault.
5. Never commit `.env` files.

## Secret Rotation

The business owner approved replacing credentials exposed in handover documents and disabling/revoking the old credentials on 2026-10-02. Vault ownership and the affected-account inventory remain to be assigned. This records approval and the execution procedure; it does not rotate a live credential.

1. Assign the vault/rotation owner. Inventory affected accounts and consumers privately, including database, VM/VPN, application admin, signing and external-provider credentials as applicable. Record identifiers and owners; never copy secret values into Git, tickets, reports or command output.
2. Generate unique replacements in the approved vault. Review restart, client-update and rollback requirements for each consumer, including active and retained application slots. Schedule the session invalidation caused by `JWT_SECRET` rotation and the invalidation of old file URLs caused by `FILE_SIGNING_SECRET` rotation.
3. Update the protected shared runtime configuration through the authorized deployment procedure in `DEPLOYMENT.md`. Changing `INITIAL_ADMIN_PASSWORD` alone does not replace an existing admin account's password: use the audited account-password operation and its session cutoff. A database/provider password must also be changed at its authoritative service.
4. Switch consumers to the replacement and verify login, authorized read-only finance/attendance access, new signed file URLs, password reset and dependency readiness. Exercise business writes only in isolated regression fixtures unless separately authorized for production. Ensure a retained release can recover using the replacements before revoking its old credentials.
5. Revoke or disable each exposed credential at its authoritative service. Verify that old credentials/sessions/links fail and replacements succeed across every serving slot. Do not restore exposed credentials when rolling back application code or restoring a backup.
6. Record date, owner, affected credential identifiers, revocation evidence and validation results without values. Restrict/remove secret-bearing handover copies where possible; replacement and revocation are still required because every copy cannot be proven destroyed.

The retired 1C connector requires no credentials. Obsolete `INTEGRATION_1C_*`
variables are ignored; remove them from managed environment templates when
performing the next authorized configuration update. Preserve historical
invoice/payment origin identifiers and audit records.

## TLS And Certificates

The supported deployment terminates public TLS at Nginx Proxy Manager and keeps the frontend, backend, and PostgreSQL services on their designated internal VMs. See `DEPLOYMENT.md`.

Before production:

1. Confirm all public URLs are HTTPS.
2. Confirm cookies are marked `Secure` in production.
3. Confirm certificate renewal is automatic.
4. Record the provider renewal mechanism and owner.

## Audit Review

Recommended weekly checks:

- New admin users.
- Role changes.
- Failed or unusual password reset activity.
- Package edit/delete approvals.
- Large inventory corrections.
- Finance/payment changes.

## Incident Response

1. Preserve logs and audit data.
2. Disable compromised users.
3. Rotate relevant secrets.
4. Export audit logs around the incident window.
5. Check audit hash continuity.
6. Restore from backup only if data integrity is compromised.
7. Record root cause, impact, corrective action, and owner.

## Dependency Vulnerabilities

1. Review Dependabot pull requests weekly.
2. Treat high/critical advisories as urgent.
3. Run CI before merging.
4. If a patch breaks compatibility, document the temporary risk acceptance and owner.
