# Tasks and notifications

Documentation scaffold authorized on 24 October 2026. No Python package or business
logic has been created here. The files below are destinations for approved work.

**Purpose:** Own task assignment/status and notification delivery/read-state behavior.

**Engineering owner:** Dilmurod. **Reviewer:** Mirshoir.
**Business acceptance:** Shavkat with operators.
This owner covers the feature's routes, DTOs, enums, database definitions and tests.
See [team ownership](../../../../docs/TEAM_OWNERSHIP.md) for shared-layer coordination.

## Existing code to study first

- Routes: [tasks.py](../../api/routes/tasks.py), [notifications.py](../../api/routes/notifications.py).
- Services/helpers: [notifications.py](../notifications.py).
- Existing SQLAlchemy schema models: [Notification](../../models/core.py#L88), [Task](../../models/tasks.py#L9).
- Existing Pydantic contracts: [tasks.py](../../schemas/tasks.py).

These are source pointers, not permission to move entire mixed files. Trace the
particular operation and every caller/write before choosing what belongs here.

## When making a service file

| Proposed file | Responsibility |
| --- | --- |
| `tasks.py` | Task create/update/assignment/state rules. |
| `notifications.py` | Notification creation, visibility and delivery coordination. |

Use snake_case filenames and operation names such as `create_*`, `record_*`,
`receive_*` or `approve_*`. A typed function is sufficient; a class is optional
when it owns real dependencies. Accept the Session, validated input and actor
explicitly. State the transaction owner, refusal rules and result contract.
Use the existing ORM models. Migrate existing schemas/ DTOs to libs/dto/<feature>/
with their callers; keep fixed values in libs/enums/. See [DTO conventions](../../libs/dto/README.md).
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
