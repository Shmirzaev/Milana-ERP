# Security Runbook

Use this runbook for production operations and security maintenance.

## Secrets

Required production secrets:

- `DATABASE_URL`
- `JWT_SECRET`
- `FILE_SIGNING_SECRET`
- `INITIAL_ADMIN_PASSWORD`
- `INTEGRATION_1C_TOKEN`
- email provider or SMTP credentials

Rules:

1. Use unique high-entropy values for every secret.
2. Do not reuse `JWT_SECRET` as `FILE_SIGNING_SECRET`.
3. Rotate secrets after staff turnover, suspected exposure, or provider compromise.
4. Store secrets only in the deployment provider's secret manager or an approved vault.
5. Never commit `.env` files.

## Secret Rotation

1. Generate the replacement secret.
2. Schedule a maintenance window if rotating `JWT_SECRET`, because active sessions will be invalidated.
3. Update the deployment provider secret.
4. Redeploy the backend.
5. Validate login, signed file URLs, 1C sync, and password reset.
6. Record the date, owner, and validation result.

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
