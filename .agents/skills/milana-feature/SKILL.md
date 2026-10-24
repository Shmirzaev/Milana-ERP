---
name: milana-feature
description: Add or extend Milana ERP features while preserving the agreed monolith boundaries, DTO and schema discipline, named ownership, regression coverage, and human acceptance. Use for approved new endpoints, workflows, fields, integrations, and related UI changes; use milana-refactor for behavior-preserving extraction.
---

# Milana feature discipline

Read repository AGENTS.md, [ownership](../../../docs/TEAM_OWNERSHIP.md), and the
affected folder's README. Use [the backend guide](../../../backend/app/README.md)
for the agreed layers and [the plan](../../../docs/REFACTOR_PLAN.md) for migration
state. Load only the feature, its callers, relevant models/contracts and tests.
Planning requests produce a concrete proposal, not implementation. Existing user
authorization covers ordinary implementation choices within the agreed scope.

## Establish the feature before editing

1. Identify the group, its engineer and independent reviewer. Shavkat supplies
   business rules and operator examples. Record success, refusal, permissions,
   affected department handoffs and expected data effects. If a missing decision
   changes business behavior or crosses a boundary, resolve that decision with
   the owner while continuing independent approved work.
2. Inspect the current branch, recent fixes and all affected callers. Reuse an
   existing operation/DTO/model where it fits. Document any genuinely new public
   interface, table, state transition or permission; do not add them by habit.
3. State the intended behavior change separately from necessary cleanup. Extract
   only the seam needed for the feature; apply milana-refactor for that extraction.
   Do not hide unrelated behavior changes or broad migrations in feature work.

## Keep these boundaries

- HTTP routes bind input, obtain actor/session, call services and map results/errors.
  Add no business calculations, direct ORM queries/writes or commits to a route.
- Feature services own business decisions, object/factory authorization and CRUD.
  Accept dependencies explicitly. No route imports/calls from services, private
  cross-group reach-through or cyclic service dependencies. Coordinate via the
  agreed public operation; do not create a generic repository/interface framework.
- DTO target is libs/dto/<feature>/: separate creation, allowed updates and output
  contracts, plus action/query inputs when needed. Reuse Pydantic and existing
  names, validators and serialization. Distinguish missing from explicit null;
  never patch with creation defaults. Response DTOs must filter confidential data.
- Fixed shared vocabulary belongs in libs/enums/; distinct internal contracts in
  libs/types/. Reuse actual stored values. Configurable roles/factories/products
  remain data; enum membership does not authorize a transition or grant access.
- Database schema-model target is schemas/, using SQLAlchemy and PostgreSQL.
  TODAY models/ contains mappings and schemas/ contains legacy Pydantic DTOs.
  Never put a new ORM model in schemas/ while those DTO imports remain. During
  transition extend mappings in the currently authoritative models/ location;
  put new DTOs in libs/dto/, and migrate an existing DTO once with its callers.
  Temporary old imports re-export the same class. Retire every old DTO caller/shim
  before moving ORM definitions, registration and Alembic discovery to schemas/.
  Do not undertake that global migration merely to add a feature.
- One outer operation owns the transaction. Helpers participate without committing.
  Preserve session/autobegin behavior, lock order, precision, audit, idempotency
  and external-effect timing. Exactly one write implementation runs per request;
  no dual writes or automatic legacy retry after an uncertain write failure.
- Enforce backend permissions, object ownership and allowed transitions; UI hiding
  and DTO field membership are not authorization. Client input cannot grant roles,
  override trusted actor/scope, or set protected financial/audit values unchecked.
- Source naming changes do not imply storage changes. Any actual schema migration
  needs explicit scope, reviewed constraints/defaults, compatibility and recovery
  verification. Multitenancy remains deferred. No production data fabrication.

## Required verification for every completed change

Follow [the verification gates](../../../docs/VERIFICATION.md) after every completed
folder/operation migration, bug fix or feature, on the exact candidate revision.
Prove test validity (bug red/green, refactor parity, targeted fault challenges for
critical rules); run relevant real PostgreSQL checks and report required skips.
Then exercise the real UI end to end and actually inspect rendered screenshots
with vision, verify persisted effects and adjacent workflows, and run a bounded
relevant stress scenario with recorded limits, integrity and recovery checks.
Use isolated test data/infrastructure. Missing browser access or a required test
environment is BLOCKED, never PASS. Repeat invalidated checks after further edits;
no cleanup/readiness claim before required gates pass. Human production acceptance
remains separate. Documentation-only work records runtime gates as NOT APPLICABLE.

## Prove and hand off

- Add meaningful tests for new behavior and affected existing workflows: permission
  denials, partial quantities/updates, retries and concurrency where relevant. Use
  isolated PostgreSQL when database constraints or locking matter. Preserve API
  compatibility unless a contract change is explicitly part of the feature.
- Exercise the real UI on isolated data with relevant roles and department handoffs.
  Check readback and quantities/money, plus scanner, label, tablet or translation
  behavior when affected. Screenshots supplement technical evidence.
- Record exact revision, tests/results, visual evidence, owner/reviewer, remaining
  decisions and recovery limitations in the task/bug record. Never invent a human
  review or mark an unrun check as passed. Update relevant folder instructions.
- Use isolated work directories and the shared clone_main landing queue. Fetch,
  reconcile urgent changes and verify the combined revision before an authorized
  push. Publication is not deployment; releases require DEPLOYMENT.md and their
  authorization. A code rollback does not reverse already-written business data.
- Shavkat/operator business acceptance and the engineer's technical evidence are
  required before moving a bug to finished_bugs.md. Retire temporary switches,
  imports and duplicated paths only under their recorded acceptance condition.

This skill guides agents; it does not claim CI or GitHub review enforcement exists.
If a request conflicts with a recorded business/interface decision, name the exact
conflict and prepare an explicit amendment rather than silently taking a shortcut.
