# Enums: stable business vocabulary

**Coordination owner:** Ismail. **Reviewer:** Mirshoir.
Shavkat confirms business meanings; feature owners update callers. See [team ownership](../../../../docs/TEAM_OWNERSHIP.md).

This folder is a documented part of the proposed refactor. No enum implementation
or database change has been made yet.

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
