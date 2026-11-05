# Identity and access

Business-service group guide, relocated into models/ on 24 October 2026. This
directory contains pure policy evaluation in [access_policy_service.py](access_policy_service.py),
access catalog and shared grant checks in [access_service.py](access_service.py), and create-user
coordination in [users_service.py](users_service.py). Authenticated role listing and role creation live in [roles_service.py](roles_service.py);
other account operations remain in the existing *_service.py files and admin route.

**Purpose:** Own authentication, user accounts, roles and permission evaluation. Keep object/factory access checks reusable by every operation.

**Engineering owner:** Dilmurod. **Reviewer:** Mirshoir.
**Business acceptance:** Shavkat with operators.
This owner covers the feature's routes, DTOs, enums, database definitions and tests.
See [team ownership](../../../../docs/TEAM_OWNERSHIP.md) for shared-layer coordination.

## Existing code to study first

- Routes: [auth.py](../../api/routes/auth.py), [admin.py](../../api/routes/admin.py), [catalog.py](../../api/routes/catalog.py).
- Services/helpers: [credentials_service.py](../credentials_service.py), [factory_scope_service.py](../factory_scope_service.py), [password_reset_service.py](../password_reset_service.py), [user_access_service.py](../user_access_service.py).
- Existing SQLAlchemy schema models: [Role](../../schemas/core.py#L9), [User](../../schemas/core.py#L21), [PasswordResetToken](../../schemas/core.py#L99).
- Existing Pydantic contracts: [auth.py](../../libs/dto/identity/auth.py), [catalog.py](../../libs/dto/catalog/catalog.py), [user_access.py](../../libs/dto/identity/user_access.py).

These are source pointers, not permission to move entire mixed files. Trace the
particular operation and every caller/write before choosing what belongs here.

## When making a service file

| Proposed file | Responsibility |
| --- | --- |
| `access_policy_service.py` (implemented) | Pure policy allow/deny evaluation; imports only the permission catalog. Factory scope imports it directly, and user access re-exports its existing names. |
| authentication_service.py | Authentication and session-factory selection; authorized real factory-switch requests append an audit row before token issuance. |
| users_service.py (create implemented) | Account creation; profile updates remain in the admin route. One creation commit and refresh precede route scheduling of a setup email. |
| access_service.py (shared checks implemented) | Unchanged role/grant and policy-change checks shared with creation, profile updates and role creation. |

Shared grant checks sit above the factory-context and policy helpers;
neither lower helper may import `access_service.py` back. The policy-only split
remains a separate prerequisite and changes no access decisions.

Use snake_case_service.py filenames and operation names such as `create_*`, `record_*`,
`receive_*` or `approve_*`. A typed function is sufficient; a class is optional
when it owns real dependencies. Accept the Session, validated input and actor
explicitly. State the transaction owner, refusal rules and result contract.
Use the existing ORM definitions in schemas/ and DTOs in libs/dto/<feature>/;
keep fixed values in libs/enums/. See [DTO conventions](../../libs/dto/README.md).
Do not import routers, call an endpoint, or commit inside a helper owned by another
transaction. Do not create an interface/repository or generic CRUD class by default.

**First operation to study:** Trace admin.create_user and admin.update_user, their catalog.UserIn/UserUpdate contracts, and every privileged field before choosing the first extraction.

**DTOs and enums:** Authentication-related fixed choices only when needed. Configurable role records and permission grants remain database data. Reuse Create/In, Update and Read/Out contracts
where they exist. Add action-specific input only for a real action. Do not generate
three DTOs for every table or expose privileged fields through generic updates.

## Boundaries and verification

Other groups call the agreed access evaluator. Department records belong to People; audit export and test-data reset are administrative infrastructure, not user CRUD.

Verify ordinary versus privileged updates, denied permissions, disabled users, factory restrictions and password/token confidentiality. Visually check login and user administration with allowed and denied accounts.

## Migration steps

Follow [the shared sequence](../README.md#migration-sequence): study route/DB/rules
and callers -> agree one operation -> capture baseline tests -> extract -> test
old/new separately -> test the real UI on isolated data -> reviewed switch -> human
production verification -> remove old code. Keep one write path per request.
Record the test result, visual evidence, approver and cleanup condition in the task.
Visual success alone does not prove permissions, concurrency or data correctness.
