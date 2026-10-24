# Packaging

Business-service group guide, relocated into models/ on 24 October 2026. This
directory remains README-only; existing implementations are the *_service.py files
linked below. The proposed files describe later approved operation extractions.

**Purpose:** Own package creation, contents/allocation, identity, change approval and production of valid labels.

**Engineering owner:** Mirshoir. **Reviewer:** Ismail.
**Business acceptance:** Shavkat with operators.
This owner covers the feature's routes, DTOs, enums, database definitions and tests.
See [team ownership](../../../../docs/TEAM_OWNERSHIP.md) for shared-layer coordination.

## Existing code to study first

- Routes: [packages.py](../../api/routes/packages.py), [package_workflows.py](../../api/routes/package_workflows.py), [packaging_reports.py](../../api/routes/packaging_reports.py), [usluga_packaging.py](../../api/routes/usluga_packaging.py), [production.py](../../api/routes/production.py).
- Services/helpers: [packages_service.py](../packages_service.py), [package_workflows_service.py](../package_workflows_service.py), [package_identity_service.py](../package_identity_service.py), [legacy_package_identity_service.py](../legacy_package_identity_service.py), [package_label_pages_service.py](../package_label_pages_service.py), [package_corrections_service.py](../package_corrections_service.py), [packaging_corrections_service.py](../packaging_corrections_service.py), [packaging_report_exports_service.py](../packaging_report_exports_service.py), [packaging_reports_service.py](../packaging_reports_service.py), [packaging_scope_service.py](../packaging_scope_service.py).
- Existing SQLAlchemy schema models: [PackagePrintRun](../package_workflows.py#L19), [PackagePrintRunMember](../package_workflows.py#L38), [PackagingRecord](../production.py#L458), [Package](../tracking.py#L54), [PackageBarcodeAlias](../tracking.py#L157), [PackageItem](../tracking.py#L176), [PackageBatchAllocation](../tracking.py#L190), [PackageScanLog](../tracking.py#L203), [PackageChangeRequest](../tracking.py#L214).
- Existing Pydantic contracts: [tracking.py](../../schemas/tracking.py), [package_workflows.py](../../schemas/package_workflows.py), [production.py](../../schemas/production.py).

These are source pointers, not permission to move entire mixed files. Trace the
particular operation and every caller/write before choosing what belongs here.

## When making a service file

| Proposed file | Responsibility |
| --- | --- |
| `packages_service.py` | Package creation, contents and allocations. |
| `identity_service.py` | Canonical/legacy identifier resolution. |
| `corrections_service.py` | Package change requests and approvals. |
| `labels_service.py` | Label eligibility and print-run orchestration. |

Use snake_case_service.py filenames and operation names such as `create_*`, `record_*`,
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
