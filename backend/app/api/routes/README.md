# Routers: HTTP controllers

**Coordination owner:** Dilmurod. **Reviewer:** Mirshoir.
Feature owners handle their own endpoints. See [team ownership](../../../../docs/TEAM_OWNERSHIP.md).

Bind and validate HTTP inputs, obtain authenticated context and a database session,
call a feature service, and map the result/errors to HTTP. Coarse permission
dependencies may remain here; object/factory rules also belong in the operation.

Do not introduce business calculations, workflow transitions, direct ORM reads/
writes, commits, or calls to another endpoint. Return the existing response shape
through its Pydantic contract. Raw ORM persistence objects are not public API schemas.

For legacy routes, trace every caller and side effect before extracting a complete
operation. Preserve status codes, pagination, errors, auth, idempotency and audit.
Do not mechanically copy lines without their transaction and dependency context.
Use the approved temporary switch only until the new path has human production
acceptance; one request must run one write path. Then remove the old business body.

Target behavior is a thin router, not an arbitrary line limit. Existing violations
are migration work; do not rewrite unrelated endpoints while changing one operation.
See the [team plan](../../../../docs/REFACTOR_PLAN.md) and use $milana-refactor in
Codex or /milana-refactor in Claude Code.

## Making or changing a router file

Keep the current URL/method and request/response contract unless a separate API
change is agreed. The handler binds input, obtains actor/session, calls the feature
operation and maps its result/error. Permission dependencies may stay at the HTTP
edge; the service still checks object/factory policy. It must not call another route.
Before extracting, list all ORM queries/writes, commits, calculations and side
effects in the existing handler. Follow the [eight-step migration sequence](../../models/README.md#migration-sequence),
including technical AND visual checks before removing its legacy body.
