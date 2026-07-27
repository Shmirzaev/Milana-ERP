# Production Readiness Checklist

Use this checklist before exposing Milana ERP to real users or customer data.

## Already Implemented In Repo

- HttpOnly cookie auth for browser sessions.
- Bearer token endpoint for machine clients.
- Role-based permission gates with admin wildcard.
- Password strength checks and legacy default password blocking.
- Login and password-reset rate limits.
- Global API rate limit middleware.
- CSRF origin guard for unsafe browser requests.
- Security headers on backend and frontend.
- Signed URLs for sensitive sales-order attachments.
- Authenticated model file access.
- Audit logs with hash-chain tamper evidence.
- Backend regression tests for security, auth, audit, production, inventory, and sales flows.
- CI dependency scanning with `pip-audit` and `npm audit`.
- CI static/security checks with Bandit, Ruff, lint, typecheck, and build.
- Dependabot configuration for backend, frontend, and GitHub Actions.

## Must Be Completed Before Production

1. Set production environment variables.
   - `ENV=production`
   - `DEBUG=false`
   - Unique 32+ character `JWT_SECRET`
   - Different unique 32+ character `FILE_SIGNING_SECRET`
   - Strong `INITIAL_ADMIN_PASSWORD`
   - Strong `INTEGRATION_1C_TOKEN`
   - Explicit `CORS_ORIGINS`

2. Configure database backups.
   - Pick backup provider.
   - Define backup frequency.
   - Define retention period.
   - Test restore into a separate environment.

3. Decide RTO and RPO.
   - RTO: maximum acceptable downtime.
   - RPO: maximum acceptable data loss.
   - Record both in `docs/DISASTER_RECOVERY.md`.

4. Decide privacy and retention rules.
   - Customer data retention period.
   - Employee data retention period.
   - Audit log retention period.
   - Backup retention period.
   - Who can approve deletion/anonymization.

5. Configure monitoring and alerting.
   - Backend health check.
   - Frontend availability.
   - Database connection errors.
   - 5xx error rate.
   - Failed login spikes.
   - Backup failures.

6. Run release validation.
   - Backend pytest with coverage.
   - Frontend lint/typecheck/build.
   - Manual smoke test for login, sales order, production flow, package scan, shipment, admin audit logs.
   - Dependency audit review.

7. Train admins.
   - Unique account per person.
   - No shared passwords.
   - Role assignment rules.
   - Audit log review.
   - Password reset flow.

## Should Be Completed Soon After Launch

- Add frontend Playwright E2E tests for login, RBAC navigation, sales order creation, package scan, and logout.
- Add automated accessibility tests using Playwright and axe.
- Add k6 or Locust load tests for login, dashboards, order creation, package scan, and shipment scan.
- Add an audit-log export and verification script for `prev_hash` / `entry_hash`.
- Add idempotency keys for payment creation, stock reservation, package scan, and shipment scan endpoints.
- Raise backend coverage threshold above the initial CI floor as tests expand.
- Add an incident-response drill and restore drill schedule.
