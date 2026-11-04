# Finance: database schema models

**Engineer:** Ismail. **Reviewer:** Mirshoir. **Business acceptance:** Shavkat.

Invoices and payments. Services coordinate issuance and allocation with Sales and Shipping.

SQLAlchemy definitions now live under app/schemas/; Pydantic DTOs live in
app/libs/dto/. The links below show the authoritative definitions for this group's
records. Business services live in models/*_service.py.

## Authoritative definitions

- [Invoice](../sales/sales.py)
- [Payment](../sales/sales.py)

Manual Finance issuance uses [invoice_persistence.py](invoice_persistence.py):
`insert_order_invoice` receives the existing Session, integer order ID, free-form
invoice number, Decimal amount, canonical InvoiceStatus and UTC datetime. It
only constructs/adds/flushes the authoritative Invoice mapping. No independent
commit, lock acquisition, business rule, mapping, table or migration is added.
The calling Finance service retains audit and the outer transaction. Other
issuance contexts are not converted by this one-operation candidate.

Shipment reopen's invoice participant uses
[invoice_reversal_persistence.py](invoice_reversal_persistence.py): the Finance
service passes already-locked Invoice rows after the shipment coordinator has
preflighted the complete set. The writer stages only `InvoiceStatus.VOID` and a
zero amount in the supplied Session, with no policy check, flush, audit or
commit. Shipment and stock writes remain outside this Finance helper.

These links follow business ownership; some point to mixed files in another group
or shared core.py. Keep one authoritative mapping per table. Moving individual
classes out of mixed files is a separate approved change.

## How to make a file here

1. Trace the approved business operation in [the service guide](../../models/finance/README.md),
   its route, current model, DTO, database writes and other callers.
2. Reuse Pydantic contracts from `libs/dto/<feature>/`; never define DTOs here.
   Find existing mapped classes before adding a new persistence definition.
3. Use a descriptive `snake_case.py` file for related existing model definitions.
   Reuse the existing SQLAlchemy Base and classes; preserve table/column names,
   keys, indexes, relationships, constraints, defaults and serialized enum values.
4. Keep persistence definitions and persistence operations here. Create/update/read validation belongs
   in DTOs; permissions, status transitions, calculations, queries and
   write coordination belong in business services under `models/`. Actual
   inserts, updates, deletes and mapped mutations belong in schema-owned
   operations using the supplied Session; helpers never commit independently.
   Follow the [engineering workflow](../../../../docs/ENGINEERING_WORKFLOW.md).
5. Update callers, model registration and Alembic discovery together. Require one
   mapping per table and no database-schema difference for a source-only move.
6. Check contracts and PostgreSQL behavior, visually exercise the affected factory
   workflow, then verify bounded stress/retries and adjacent department handoffs.
   Remove old paths only after the agreed acceptance and rollback conditions pass.

Only groups with actual definitions are Python packages. A guide without Python
files points to its existing definitions elsewhere; it is not a request to create
duplicate classes or empty implementation files.

See [schema migration rules](../README.md), [DTO conventions](../../libs/dto/README.md),
[the business plan](../../../../docs/REFACTOR_PLAN.md) and
[team ownership](../../../../docs/TEAM_OWNERSHIP.md).
