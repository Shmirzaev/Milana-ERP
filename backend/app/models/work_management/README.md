# Tasks and notifications

Business-service group guide, relocated into models/ on 24 October 2026.
`tasks_service.py` contains the user-facing Task CREATE, PATCH and COMPLETE
operations and the separate focused system stock-shortage participant. Deletion
remains an independent route-owned operation.

**Purpose:** Own task assignment/status and notification delivery/read-state behavior.

**Engineering owner:** Dilmurod. **Reviewer:** Mirshoir.
**Business acceptance:** Shavkat with operators.
This owner covers the feature's routes, DTOs, enums, database definitions and tests.
See [team ownership](../../../../docs/TEAM_OWNERSHIP.md) for shared-layer coordination.

## User-facing Task CREATE

`create_user_task` coordinates the existing self, manager-assignment and bounded
manager-broadcast behaviors on the supplied Session. Task rows are staged through
the Work Management schema participant; notifications use shared notification
operations; audit uses the shared hash-chain service. This service owns the one
outer commit and refreshes the first created task for the existing 201 response.
It preserves current assignment permissions, inactive existing-assignee behavior,
notification payloads, broadcast ordering/cap and rollback semantics. It adds no
idempotency or task locks. PATCH, COMPLETE and delete remain separate operations.

## User-facing Task PATCH

`update_user_task` coordinates the existing creator/manager/assignee rules,
reassignment notice, completion timestamp and update audit on the request's
Session. The mapped Task changes are applied by the Work Management schema
participant; the service owns the single commit and refresh. PATCH presence is
carried in a typed command so omission remains distinct from explicit null. Null
for database-required title/status/priority remains a database constraint failure;
this extraction does not silently define a new HTTP validation policy. The
dedicated `/complete` operation remains separate, including its notification and
audit behavior.

TaskStatus/TaskPriority are canonical fixed-vocabulary contracts for task
create/update/complete/output and status filtering; the mapped columns remain
VARCHAR with string values. Historical stored values were not censused here, so
output/runtime compatibility and visual/database acceptance remain required gates.

## User-facing Task COMPLETE

`complete_user_task` owns the existing assignee-or-manager check, status/timestamp
write, conditional creator notification, completion audit, one commit and refresh.
The Work Management schema participant assigns the canonical completed value and
timestamp on the caller's attached Task row without flushing or committing.
Repeated calls intentionally retain current behavior: each sets a fresh completion
timestamp and creates another completion audit and (when the creator differs from
the actor) another creator notification. This operation does not deduplicate or
add locks. Its notification text/link and audit shape remain distinct from PATCH.

## System stock-shortage participant

`create_stock_shortage_task` receives the current Session and exact required
title/description/assignee/actor/due-date fields. Sales retains the when/why and
existing planning-recipient selection. Work management preserves pending/high
semantics and calls its schema-owned insert. It adds no transaction, flush,
deduplication, audit, notification or permission behavior. No Task ORM object is
returned to Sales. This is the already assigned task-creation responsibility;
it does not introduce a generic CRUD API or migrate user-facing task routes.

Canonical TaskStatus/TaskPriority remain used by this writer and schema defaults.
It remains a separate caller-owned participant; no generic CRUD, notification or
audit behavior was added to it.

## Existing code to study first

- Routes: [tasks.py](../../api/routes/tasks.py), [notifications.py](../../api/routes/notifications.py).
- Services/helpers: [notifications_service.py](../notifications_service.py).
- Existing SQLAlchemy schema models: [Notification](../../schemas/core.py#L88), [Task](../../schemas/work_management/tasks.py#L9).
- Existing Pydantic contracts: [tasks.py](../../libs/dto/work_management/tasks.py).

These are source pointers, not permission to move entire mixed files. Trace the
particular operation and every caller/write before choosing what belongs here.

## When making a service file

| Proposed file | Responsibility |
| --- | --- |
| `tasks_service.py` | Task create/update/assignment/state rules. |
| `notifications_service.py` | Notification creation, visibility and delivery coordination. |

Use snake_case_service.py filenames and operation names such as `create_*`, `record_*`,
`receive_*` or `approve_*`. A typed function is sufficient; a class is optional
when it owns real dependencies. Accept the Session, validated input and actor
explicitly. State the transaction owner, refusal rules and result contract.
Use the existing ORM definitions in schemas/ and DTOs in libs/dto/<feature>/;
keep fixed values in libs/enums/. See [DTO conventions](../../libs/dto/README.md).
Do not import routers, call an endpoint, or commit inside a helper owned by another
transaction. Do not create an interface/repository or generic CRUD class by default.

**First operation to study:** Trace task updates, actor/assignee visibility and notification side effects. Keep department inbox projections with the workflows they display.

**DTOs and enums:** Task and notification categories/states only where fixed; users and departments remain references. Reuse Create/In, Update and Read/Out contracts
where they exist. Add action-specific input only for a real action. Do not generate
three DTOs for every table or expose privileged fields through generic updates.

## Boundaries and verification

Other groups request notifications through a supported operation; preserve after-commit behavior and existing delivery guarantees. Tasks do not own manufacturing status changes.

Verify task dates/references, assignee visibility, factory permissions and notification duplication on retries. Visually check assignment, status updates and another account receiving/reading its notification.

## Migration steps

Follow [the shared sequence](../README.md#migration-sequence): study route/DB/rules
and callers -> agree one operation -> capture baseline tests -> extract -> test
old/new separately -> test the real UI on isolated data -> reviewed switch -> human
production verification -> remove old code. Keep one write path per request.
Record the test result, visual evidence, approver and cleanup condition in the task.
Visual success alone does not prove permissions, concurrency or data correctness.
