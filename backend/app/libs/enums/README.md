# Enums: stable business vocabulary

**Coordination owner:** Ismail. **Reviewer:** Mirshoir.
Shavkat confirms business meanings; feature owners update callers. See [team ownership](../../../../docs/TEAM_OWNERSHIP.md).

This folder is part of the refactor. `finance.py` contains an RF-011 candidate
for the five persisted invoice status strings. It preserves the existing API
strings and SQL `String` column; no database change has been made. Mirshoir and
Shavkat still need to review its business meaning before it is landed.

## Purpose

Give repeated, fixed business values one definition, following the enum pattern
in the mentor's Nestar and Meditech backends. Organize definitions by the feature
that owns their meaning, for example a future `production.py` for production
states. Schemas and services should reuse the same definition.

## What belongs here

- Stable status values and operation categories used by multiple callers.
- Explicit string values that preserve the existing API and database contract.

## Rules

- Confirm the complete vocabulary and its meaning with the feature owner before
  converting existing strings. Shavkat clarifies business meaning; Mirshoir
  reviews changes to sensitive workflow states.
- Preserve existing serialized values, including their spelling and case.
- Configurable factories, employees, products, and permission records stay in
  their existing storage. They do not become enums simply because they have IDs.
- Membership in an enum does not grant permission or validate a state transition.
  Services still enforce those rules.
- Keep enum definitions independent of routers, services, and database sessions.
- A small choice used in one contract can remain a `Literal` when that is clearer.
- Python enums do not require a PostgreSQL enum migration. Any storage change
  needs its own review; verify enum names versus values if using SQLAlchemy Enum.

Introduce each enum with its actual callers during an approved feature refactor.
This folder is not a requirement to convert every string in the application.

## RF-011 pilot inventory for Ismail (source `84bbc03`)

| Stored field | Current source vocabulary | Conversion gate |
| --- | --- | --- |
| `SewingAssignment.status` | `planned`, `in_progress`, `completed`, `cancelled`, `transferred` in the ORM comment and assignment routes. | No SQL CHECK constraint exists on this column. Query distinct values in a read-only production snapshot first; Shavkat confirms each meaning. `sewing_flows.py` defines active as only planned/in-progress and managed as planned/in-progress/completed; output currently accepts completed too. Preserve each operation's subset rather than using enum membership as editability. Mirshoir reviews the callers. |
| `WorkOrder.status` | `new`, `planning`, `waiting`, `pending`, `ready`, `collected`, `in_progress`, `paused`, `completed`, `rejected`, `cancelled` in `ck_work_orders_status`. | This is shared by Cutting, Printing, Sewing, Packaging and Storage. Mirshoir owns the vocabulary and transitions; do not create a Sewing-only copy. Preserve the current string column and database constraint. |
| `Invoice.status` | `unpaid`, `partially_paid`, `paid`, `void`, `cancelled` in `ck_invoices_status`. | Ismail owns this candidate. The five values now have one Python definition in `backend/app/libs/enums/finance.py` (`InvoiceStatus`); `ck_invoices_status` and the `invoices.status` default are derived from it. The persisted `String(32)` column, the rendered CHECK text and every API string are unchanged, and no database migration was made or is needed. `payments_service.py` derives settlement status; finance, sales, customer payment and shipment delivery have different issuance rules. Customer-facing `payment_status` values such as `no_invoice` and `partial` are a separate projection and are not enum members. Preserve USD tolerance and all API strings. |

This inventory does not approve business transitions or authorize a release. The
`Invoice.status` row is already a candidate conversion; the other rows are still
inventory. Use explicit `str` enum values after the responsible engineers and
Shavkat confirm meaning, then compare validation, serialization, storage and
rollback behavior on the accepted operation. The enum must not replace
authorization or transitions.

Ismail coordinates enum conventions and the vocabulary inventory. Each feature
owner verifies its callers and serialization; Shavkat confirms business meanings.
See the [team plan](../../../../docs/REFACTOR_PLAN.md).

## How to make an enum file

Use a domain-named file such as payroll.py and an explicit string-valued Enum.
Inventory every stored value and client first. For example, the current payroll
period vocabulary is draft, open, locked, approved, paid and cancelled; creation
allows only draft/open. Preserve both facts instead of accepting every enum member
for every action. The service owns legal transitions and authorization.

Use `class PayrollPeriodStatus(str, Enum)` with explicit serialized values when
that conversion is approved. Preserve the existing public strings and database
column type. Do not switch to PostgreSQL ENUM as a side effect of adding Python types.
Ismail coordinates conventions; each feature owner updates its actual callers/tests.
