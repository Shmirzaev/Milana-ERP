# INV-WAREHOUSE-CREATE

Owner Ismail; reviewer Mirshoir; operator acceptance Shavkat. Base8a270cb9.
Implementation candidate only; independent/browser/human gates remain pending.

The POST warehouse path now uses a canonical WarehouseType input and strict
WarehouseCreatedOut response. Both accept the existing11 creation values and
publish exactly that subset in OpenAPI. The13-member canonical vocabulary also
records source-recognized raw_material/warehouse legacy lookup kinds, which
remain forbidden creation inputs. No normalization or new type default is added.

The existing Inventory stock service calls schema-owned insert_warehouse with
its supplied Session and typed enum. Only construction/add/flush move; audit,
one outer commit and refresh remain service-owned. The helper unwraps .value at
the unchanged String column. No schema migration, permission change, name/FK
policy, idempotency behavior or new UI is introduced.

Converted: used create input/output and internal persistence argument. Intentionally
retained: configurable names, department references; actual stored Warehouse.type
and unrestricted GET WarehouseOut.type remain strings while arbitrary historical
values are unresolved. Pending: authorized stored-vocabulary reconciliation,
strict list/ORM/frontend consumer conversion, other writers and receiving/adjustment
operation contracts. This does not claim system-wide Warehouse enum completion.

Compatibility: GET remains ascending and excludes only accessory_storage for
materials-only users. admin.warehouses alone permits POST but not GET. Legacy
fallback preference order and seed/migration bodies stay unchanged. Duplicate
names, whitespace and nullable/invalid department behavior stay unchanged.

Verification requires the47-case real-PG baseline (only its intentional Literal
runtime expectation becomes canonical Enum), actual used DTO/OpenAPI checks,
same-Session helper/audit/outer-commit and rollback assertions. Run all relevant
cases on immutable candidate and retain owned-database cleanup/source hashes.
Then independent review, actual approved browser selectors/readback, bounded
integrity tests and human acceptance remain required. No creation UI exists;
do not invent a UI or claim a click-based creation test.
