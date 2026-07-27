# Privacy, PII, And Retention Policy Draft

This is a draft for business/legal review. The application contains employee, customer, finance, and operational records, so production use needs explicit retention and deletion decisions.

## Data Categories

- User identity: name, email, role, department, login activity.
- Employee data: name, department, position, phone, salary, status.
- Customer and supplier data: names, contact details, order/payment history.
- Production data: sales orders, production orders, work orders, bundles, packages, shipments.
- Finance data: invoices, payments, profitability reports, 1C integration data.
- Uploaded files: model images and sales-order printing attachments.
- Audit data: user actions, before/after payloads, timestamps.

## Decisions Required Before Launch

| Decision | Owner | Current Value |
|---|---|---|
| Customer record retention | Business/legal | TBD |
| Employee record retention | Business/legal | TBD |
| Finance record retention | Business/legal/accounting | TBD |
| Audit log retention | Business/legal/security | TBD |
| Uploaded file retention | Business/legal/operations | TBD |
| Backup retention | Business/legal/IT | TBD |
| User deletion vs deactivation policy | Business/legal/security | TBD |
| Data export process | Business/legal/IT | TBD |
| Data deletion approval process | Business/legal/IT | TBD |

## Current Technical Behavior

- User deletion exists and detaches/deletes dependent records where required by database references.
- Audit logs are kept in the database and now include tamper-evident hashes.
- There is no automated retention job yet.
- There is no formal data subject request workflow yet.
- There is no tenant-level data isolation model.

## Recommended Production Policy

1. Prefer deactivation over deletion for staff users tied to operational records.
2. Require manager/admin approval before deleting business records.
3. Keep audit logs for the legally required period, then archive rather than hard-delete when possible.
4. Keep backups for a fixed period and document where they are stored.
5. Define a data export workflow for customers/employees before accepting regulated requests.

## Implementation Backlog

- Add a data export endpoint or admin script for user/customer records.
- Add retention jobs once retention periods are approved.
- Add anonymization for records that must remain for accounting or audit but no longer need direct personal identifiers.
- Add a documented process for deletion requests and approval evidence.
