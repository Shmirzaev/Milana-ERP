# Packaging

Documentation scaffold authorized on 24 October 2026. No Python package or business
logic has been created here. The files below are destinations for approved work.

**Purpose:** Own package creation, contents/allocation, identity, change approval and production of valid labels.

**Engineering owner:** Mirshoir. **Reviewer:** Ismail.
**Business acceptance:** Shavkat with operators.
This owner covers the feature's routes, DTOs, enums, database definitions and tests.
See [team ownership](../../../../docs/TEAM_OWNERSHIP.md) for shared-layer coordination.

## Existing code to study first

- Routes: [packages.py](../../api/routes/packages.py), [package_workflows.py](../../api/routes/package_workflows.py), [packaging_reports.py](../../api/routes/packaging_reports.py), [usluga_packaging.py](../../api/routes/usluga_packaging.py), [production.py](../../api/routes/production.py).
- Services/helpers: [packages.py](../packages.py), [package_workflows.py](../package_workflows.py), [package_identity.py](../package_identity.py), [legacy_package_identity.py](../legacy_package_identity.py), [package_label_pages.py](../package_label_pages.py), [package_corrections.py](../package_corrections.py), [packaging_corrections.py](../packaging_corrections.py), [packaging_report_exports.py](../packaging_report_exports.py), [packaging_reports.py](../packaging_reports.py), [packaging_scope.py](../packaging_scope.py).
- Existing SQLAlchemy schema models: [PackagePrintRun](../../models/package_workflows.py#L19), [PackagePrintRunMember](../../models/package_workflows.py#L38), [PackagingRecord](../../models/production.py#L458), [Package](../../models/tracking.py#L54), [PackageBarcodeAlias](../../models/tracking.py#L157), [PackageItem](../../models/tracking.py#L176), [PackageBatchAllocation](../../models/tracking.py#L190), [PackageScanLog](../../models/tracking.py#L203), [PackageChangeRequest](../../models/tracking.py#L214).
- Existing Pydantic contracts: [tracking.py](../../schemas/tracking.py), [package_workflows.py](../../schemas/package_workflows.py), [production.py](../../schemas/production.py).

These are source pointers, not permission to move entire mixed files. Trace the
particular operation and every caller/write before choosing what belongs here.

## When making a service file

| Proposed file | Responsibility |
| --- | --- |
| `packages.py` | Package creation, contents and allocations. |
| `identity.py` | Canonical/legacy identifier resolution. |
| `corrections.py` | Package change requests and approvals. |
| `labels.py` | Label eligibility and print-run orchestration. |

Use snake_case filenames and operation names such as `create_*`, `record_*`,
`receive_*` or `approve_*`. A typed function is sufficient; a class is optional
when it owns real dependencies. Accept the Session, validated input and actor
explicitly. State the transaction owner, refusal rules and result contract.
Use the existing ORM models. Migrate existing schemas/ DTOs to libs/dto/<feature>/
with their callers; keep fixed values in libs/enums/. See [DTO conventions](../../libs/dto/README.md).
Do not import routers, call an endpoint, or commit inside a helper owned by another
transaction. Do not create an interface/repository or generic CRUD class by default.

**First operation to study:** Trace package_workflows importing packages._package_lookup_candidates. Review package_identity.py and legacy_package_identity.py before selecting one supported identity operation.

**DTOs and enums:** Package/change-request/print-run lifecycle values, preserving existing barcode and API contracts. Reuse Create/In, Update and Read/Out contracts
where they exist. Add action-specific input only for a real action. Do not generate
three DTOs for every table or expose privileged fields through generic updates.

## Boundaries and verification

Fulfillment owns warehouse acceptance, stock reservations and dispatch. Package identity/content stays authoritative here. Rendering helpers remain reusable infrastructure; a printout is not proof of stock receipt.

Verify selected-batch quantities, partial packages, ambiguous codes, stale labels, permission checks and audit history. Visually check creation, correction approval, printed/scanned labels and receiving eligibility.

## Migration steps

Follow [the shared sequence](../README.md#migration-sequence): study route/DB/rules
and callers -> agree one operation -> capture baseline tests -> extract -> test
old/new separately -> test the real UI on isolated data -> reviewed switch -> human
production verification -> remove old code. Keep one write path per request.
Record the test result, visual evidence, approver and cleanup condition in the task.
Visual success alone does not prove permissions, concurrency or data correctness.
