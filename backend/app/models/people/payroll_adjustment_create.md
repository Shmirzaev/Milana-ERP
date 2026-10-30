# Manual payroll adjustment creation

## Scope and ownership

- Operation: `POST /api/payroll/adjustments` only.
- Engineer: Dilmurod. Human reviewer: Mirshoir. Business acceptance: Shavkat with operators.
- Candidate base: `ff1542f02c137f24fc9fe78492aa69aa463a7293` (clean `clone_main` base).
- Route adapter: `api/routes/payroll.py::create_adjustment`.
- Business operation: `models/people/payroll_adjustment_service.py::create_manual_payroll_adjustment`.
- Schema write: `schemas/people/payroll_adjustment_persistence.py::insert_manual_payroll_adjustment`.
- Transaction owner: the People payroll business operation. The schema helper uses the same Session, adds and flushes one row, and never commits.

The operation preserves the route's order: selected-factory lookup; optional period
query scoped to that factory with `populate_existing()` and `FOR UPDATE`; supplied
period 404; finalized-period refusal; employee existence in the selected factory;
amount/type normalization; schema insert and flush; existing audit append; one
commit; refresh. It preserves the existing permission dependency and HTTP response
shape. No notification, idempotency, file or external side effect participates.

## Behavior and canonical type ledger

| Value/field | Decision and coverage |
|---|---|
| `adjustment_type` | Canonical `PayrollAdjustmentType` (`bonus`, `deduction`) now types DTO input/output, internal create command, mapped field, and the existing summary/reversal consumers. The DTO still trims and lowercases strings; omitted, null and blank normalize to no explicit type. Invalid API values retain 422 validation; direct normalization refusals retain their 400 behavior. |
| `factory_code` | Canonical `FactoryCode` (`MIL`, `BST`, `ECO`) now types this operation's internal command, this table's mapped field and `PayrollAdjustmentOut`. `FACTORY_CODES` is derived from that enum in the same order; selected-factory normalization and its string return behavior are unchanged, and conversion to the enum happens only at the command boundary after scope checks. |
| Storage | `PayrollAdjustmentTypeStorage` converts enum values to the existing string values on bind and returns enum members on load/refresh. For compatibility with existing ORM callers, raw strings pass through at the SQLAlchemy boundary; the existing database CHECK remains responsible for rejecting invalid strings. Domain/DTO/mapped annotations stay canonical-enum typed. The column remains `VARCHAR(16)` with the existing two-value CHECK, and the Python default remains `bonus`; no migration or native PostgreSQL enum is introduced. |
| Factory storage | `FactoryCodeStorage` converts enum values to the existing strings and reloads them as enum members; raw-string ORM values still reach the existing database CHECK. The column remains `VARCHAR(3)`, its server default remains `MIL`, and its CHECK values/order remain `MIL`, `BST`, `ECO`; no migration is introduced. This worker did not perform a production-data census. |
| Amount | The internal command uses `Decimal`. Existing cent precision, finite check, maximum, nonzero rule, sign/type combination and negative-to-deduction behavior remain in the service. |
| Currency and reason | Currency remains free-form storage normalized as `(payload.currency or "UZS").upper()[:8]`; reason remains exact payload text with the existing DTO length bound. |
| Payroll period status | Adjacent fixed vocabulary remains the existing string mapping and string-based finalized-period check (`locked`, `approved`, `paid`, `cancelled`). `PayrollPeriodStatus` conversion and the period lifecycle remain separate unresolved work. |

Other People payroll factory fields and DTOs remain string-typed and are outside this
operation's slice. `SewingFactoryCode` remains a separate domain enum and was not
reused or changed. No all-People factory typing completion or production-data audit
is claimed.

## Other writers and consumers

`POST /api/payroll/records/{record_id}/reverse-as-adjustment` remains a separate
writer with its own reversal checks, audit payload and transaction. Its constructor
now passes `PayrollAdjustmentType.DEDUCTION` so the shared mapped field is canonical;
the reversal is not routed through the manual-create use case and still needs its
own schema-owned persistence extraction. The payroll summary and list/output paths
read enum members through the mapped storage adapter and serialize the unchanged
strings. Direct test fixtures use enum members for mapped assignments.

## Verification ledger

- Added coverage: DTO normalization and JSON/storage round trip, raw stored string,
  fresh/expired ORM loads, unchanged mapping length/CHECK, response and audit actor/
  payload, legacy raw-string ORM assignments/query binds, transient deduction sign,
  database CHECK rejection, all three factory enum wire/storage/reload values and
  invalid-factory database CHECK refusal, plus approved-instance PostgreSQL wrappers
  for the existing period-lock and failure-after-flush rollback/retry oracles.
- Preserved coverage: API amount/bounds/refusal cases, summary totals, reversal
  response, and PostgreSQL writer-versus-period-lock race (race synchronization now
  patches the actual service status guard).
- This worker did not run tests, PostgreSQL, UI or application processes because
  the parent task holds those gates under the current RAM/runtime restriction.
  AST, Ruff and diff checks passed; independent AI source review accepted the
  corrected enum/storage/factory and approved-wrapper changes. Runtime checks remain pending. Browser/readback, real
  PostgreSQL, bounded stress, human technical/visual acceptance, merge and deploy
  are not claimed.
