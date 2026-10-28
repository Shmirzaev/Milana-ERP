# Enums: stable business vocabulary

## Guidance publication and runtime scope

26 October 2026: these engineering rules were published on `clone_main`
through `b92ee8ff109d47e573ff4e506267500a9db1f649`. That documentation-only
publication did not integrate the runtime candidate in
[draft PR #308](https://github.com/Shmirzaev/Milana-ERP/pull/308).
This candidate reconciles those published rules with the grouped services,
entity-named DTOs and scoped enum corrections. Historical test results belong
to their recorded revisions; they do not verify this combined candidate.
Remaining legacy/root services, mixed DTO files, schema-owned writers and
full enum/type adoption stay in the operation ledger. Browser and human
acceptance are separate gates.

**Coordination owner:** Ismail. **Reviewer:** Mirshoir.
Shavkat confirms business meanings; feature owners update callers. See [team ownership](../../../../docs/TEAM_OWNERSHIP.md).

This folder is part of the refactor. `finance.py` contains an RF-011 candidate
for the five persisted invoice status strings. It preserves the existing API
strings and SQL `String` column; no database change has been made. Mirshoir and
Shavkat still need to review its business meaning before it is landed.

26 October 2026: Ismail reaffirmed that enums are part of his assignment and
must be audited business operation by business operation and table by table.
This historical pilot inventory is a starting point, not proof of full coverage
or completion of the current enum workers. Use the procedure below and the
[verification/human gate](../../../../docs/VERIFICATION.md).

## Purpose

Give repeated, fixed business values one definition, following the enum pattern
in the mentor's Nestar and Meditech backends. Organize definitions by the feature
that owns their meaning, for example a future `production.py` for production
states. Schemas, DTO field annotations, internal types and services must reuse the
same definition for the same fixed business concept. Ismail's current goal is
system-wide adoption in the modular monolith, not only the six initial pilot areas.
Domain owners keep responsibility for business policy; pilots define rollout order,
not a smaller completion scope.

## What belongs here

- Stable status values and operation categories used by multiple callers.
- Explicit string values that preserve the existing API and database contract.

## Rules

Audit each field's raw accepted vocabulary separately from its canonical business
meaning, default/fallback and action subset. Padded legacy values may normalize
for business use while their original spelling remains significant for replay or
failure audit. Unknown input is not a fallback. Verify actual runtime enum values
and all callers, including copied DTOs and direct service producers; an enum file,
enum-backed string default or passing OpenAPI snapshot alone does not prove usage.

- Confirm the complete vocabulary and its meaning with the feature owner before
  converting existing strings. Shavkat clarifies business meaning; Mirshoir
  reviews changes to sensitive workflow states.
- Preserve existing serialized values, including their spelling and case.
- Configurable factories, employees, products, and permission records stay in
  their existing storage. They do not become enums simply because they have IDs.
- Membership in an enum does not grant permission or validate a state transition.
  Services still enforce those rules.
- Keep enum definitions independent of routers, services, and database sessions.
- Known fixed business vocabularies must use the owning Enum in DTO and internal
  type annotations. An enum-backed default on a `str` field is not enum typing.
  For an action subset, use the canonical enum with an explicit subset validator,
  or a type expressed using those enum members; retain the service transition guard.
- Python enums do not require a PostgreSQL enum migration. Any storage change
  needs its own review; verify enum names versus values if using SQLAlchemy Enum.

Introduce each enum with its actual callers during an approved feature refactor.
Free text, identifiers and genuinely configurable references remain appropriately
typed. A configurable table can still contain a fixed discriminator: inspect each
field and its consumers instead of excluding it because its rows are configurable.

## Table-by-table audit

Audit the complete assigned database scope systematically, not just fields found
by searching for "status". Establish the exact old-source revision, database/
snapshot identity, migration head, mapped schema and audit date. Enumerate tables
from both SQLAlchemy metadata and the actual authorized PostgreSQL snapshot;
reconcile unmapped/legacy tables and relevant views. A code-only scan or an empty
test database cannot prove the deployed vocabulary. Prefer an authorized restored
read-only snapshot; unavailable real-value evidence is BLOCKED, never guessed.
This procedure grants no new production access or data-repair authority.
Label provenance as synthetic fixtures, restored production snapshot or explicitly
authorized live read, and state its date/coverage. Synthetic rows can verify tested
behavior but cannot prove that all real factory values have been found. Keep that
data-coverage gap open; do not present local fixture values as production truth.

For each table, inspect every column and relevant structured JSON/discriminator
field: actual database and ORM type, nullability, client/server defaults, CHECK/
native-enum constraints, keys, references and meaning. Then inspect distinct stored
values including null/blank/case variants for candidate vocabulary fields, all
writes/updates/importers, service comparisons, alternate routes, DTOs and UI/report
projections. Record read-only query scope/results without secrets or unrelated
personal/business records. An empty or sampled result is not a complete vocabulary.
Bound costly reads and record incomplete scans instead of claiming full coverage.

Keep a table/field ledger in the task evidence:

```text
Table/field/business concept / operation / accountable owner:
Old source / database snapshot+migration / observation date:
DB+ORM type, null/defaults/CHECKs/references / observed values and counts:
Writers+alternate callers / readers+DTOs+UI projections:
Existing enum/type and exact members / missing or conflicting values:
Decision: enum | DTO | needed internal type | existing scalar/reference type | configurable/free-form | retain Literal/string
Converted consumers / retained-with-reason / unresolved question+owner:
Candidate identity / compatibility checks / operation verification status:
```

Every enumerated table needs a reviewed, pending, blocked or justified excluded
row; every reviewed field needs a classification or an explicit unresolved result.
Keep global table coverage and per-operation migration status separate. A partial
table review does not complete the full audit, and creating a shared enum does not
verify every business operation using that table. Name out-of-area owners and
pending work instead of implementing their policy or dropping their rows.

### Reconcile a newly discovered value

1. Trace its source, stored occurrences, consumers and business meaning. Decide
   whether it is a legitimate existing fixed value, a configurable record, an
   output projection, a legacy alias, a typo/corrupt value or a new business rule.
2. For a legitimate existing fixed value missing from its domain enum, update the
   one authoritative enum and affected callers/tests in the operation's reviewed
   slice, preserving its exact representation and action-specific subsets. An
   ambiguous meaning or proposed new rule needs the accountable engineer/business
   owner's decision before it is enforced. Do not silently accept bad data by
   appending every observed string, or reject legacy values by omitting them.
3. Check create/update/read behavior, defaults, omitted/null, normalization, error
   paths, serialization, audit and stored effects before/after. `class X(str, Enum)`
   may stringify as `X.MEMBER`; use `.value` where the existing boundary expects
   its raw string. Do not introduce native SQLAlchemy/PostgreSQL ENUM storage or
   constraints as an incidental source cleanup.
   If requests use idempotency, test replay against fingerprints produced by the
   pre-change DTO and serializer. Moving padding/case normalization before hashing
   can reject an identical historical retry. Preserve typed enum contracts and the
   required fingerprint boundary; never bypass hash/identity checks or rewrite
   saved records as a shortcut. Include omitted defaults and numeric serialization.
   An ORM enum annotation/default also needs a real database round-trip check:
   verify fresh-session and expired/refresh reads, stored values, and the enum type
   reaching business interfaces. A plain string column does not become an enum
   converter because its annotation changed. Follow the
   [persistence runtime-type checks](../../schemas/README.md#verify-runtime-types-across-persistence).
4. Compare the ledger with schemas and every caller again. Then execute focused
   tests, real UI/readback and bounded stress for this operation; independent AI
   verification produces AI_VERIFIED_AWAITING_HUMAN, followed by the human's actual
   visual check and recorded approval. Missing required evidence keeps the gate open.

For Ismail's user-type example: first establish whether a users table/field actually
stores a fixed user-type discriminator or references configurable roles. A newly
discovered supported discriminator belongs in the relevant enum and callers/tests;
a role row, permission grant, user ID or display label does not automatically
become an enum member. Do not infer the vocabulary from a file name or one example.

## Enum, DTO and internal type are different decisions

- Enums give a fixed business vocabulary one definition. A full lifecycle can
  include states forbidden for a particular create/approve/receive action; keep
  the service's subset/transition/permission guard and test it independently.
- Pydantic input/update/output DTOs for known fixed vocabularies must carry actual
  enum annotations. Do not retain `str`, `Enum | str`, `Any`, a duplicated string
  union, or only an enum-backed default as the completed result. Preserve supported
  normalization and action subsets with explicit validators. Record and test any
  intentional validation/OpenAPI change required by the typed contract; byte-identical
  OpenAPI is not a reason to evade this requirement. Unknown historical values need
  explicit reconciliation rather than a silent open-string escape or data rewrite.
- Add dataclasses/TypedDicts/type aliases in libs/types only for a real distinct
  internal contract with named consumers. Do not mirror every table/DTO or create
  unused declarations to make the folder look complete.
- Persisted state and report/UI projections can differ: invoice partially_paid
  and customer-ledger partial/no_invoice are not one storage vocabulary. Fields
  sharing a word such as cancelled do not automatically share a business concept.

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
