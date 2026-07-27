# Code Review Standard

Use this standard for pull requests before merging to production branches.

## Required Checks

- Backend tests pass with coverage threshold.
- Frontend lint, typecheck, and build pass.
- Dependency audit results are reviewed.
- Security-sensitive changes include tests.
- Database changes include migration or `schema_hotfix` coverage.

## Reviewer Checklist

1. Auth and permissions:
   - Does every state-changing endpoint require the correct permission?
   - Can a lower-privileged user escalate access?

2. Data integrity:
   - Are inventory, payment, shipment, and package transitions protected by business rules?
   - Is concurrent access considered for stock or reservation updates?

3. Security:
   - Are user-controlled values validated or escaped?
   - Are uploaded files type and size checked?
   - Are secrets kept out of logs, audit payloads, and client responses?

4. Reliability:
   - Does the change fail with clear errors?
   - Are retries safe for write operations?
   - Does the change preserve idempotent startup behavior?

5. Observability:
   - Is there an audit log for meaningful business writes?
   - Would an admin be able to understand who changed what?

6. Frontend:
   - Is the UI permission-gated consistently with the backend?
   - Are loading, empty, and error states handled?
   - Are labels and controls accessible?

## High-Risk Areas

- Authentication and password reset.
- Role and permission management.
- Stock reservation and release.
- Package edit/delete approvals.
- Shipment scanning and delivery.
- Payment creation and invoice status.
- Startup seed and schema hotfix code.

## Merge Rule

Do not merge a high-risk change until at least one reviewer has checked the relevant high-risk area and the PR includes a regression test or a documented reason why a test is not practical.
