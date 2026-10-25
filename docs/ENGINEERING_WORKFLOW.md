# Required engineering workflow

Owner's requirements, consolidated 26 October 2026. This is the required target
for the Milana modular monolith. Existing folder moves and passing pilot checks
do not establish system-wide compliance. Use [AGENTS.md](../AGENTS.md) for repository
instructions, [ownership](TEAM_OWNERSHIP.md) for assignments and
[VERIFICATION.md](VERIFICATION.md) for evidence and acceptance gates.

## Start or resume an agent session

Read the current repository instructions, this contract, the relevant shared
[skill](AGENT_SKILLS.md), current project context and the operation's ledger.
Record the user's scope and corrections, source revision, responsible engineer,
reviewer, allowed files and next operation. After compaction or a handoff, reread
that record and inspect the actual diff. A previous assistant's completion claim
cannot remove unfinished requirements. Report conflicting guidance and reconcile
it with the owner's latest instruction before relying on an older shortcut.

Study all source and callers affected by the operation before changing it,
including shared/root helpers, jobs, imports, UI and downstream handoffs. Read
in bounded slices and record coverage; neither reading one route nor loading a
large directory without tracing behavior is a completed study.

## Required request and write path

```text
HTTP route/controller
  -> dedicated business service (typed DTO + actor + supplied Session)
    -> schema-model persistence methods/operations (same Session)
      -> database
```

| Layer | Owns | Must not do |
| --- | --- | --- |
| `api/routes/` | HTTP binding, authenticated context/dependencies, dedicated service call, response/error mapping | Business calculations, workflow transitions, ORM writes/queries, transaction commits or calling another route |
| `models/<group>/*_service.py` | Business rules, object/factory authorization, calculations, legal transitions, queries and cross-operation coordination | Direct insert/update/delete, mapped-field/relationship mutation, importing HTTP handlers or reaching into another domain's private helpers |
| `schemas/<group>/` | Mapped definitions/constraints and explicit typed persistence methods or companion operations that perform writes | Business-policy orchestration, HTTP dependencies, service/route imports or independent commits |
| `libs/dto/` | Input, update and output contracts, validation and serialization | Database access, permissions-as-field-validation or service imports |
| `libs/enums/` | One authoritative definition for each fixed business vocabulary | Duplicated per-layer vocabularies or enum members invented from arbitrary data |
| `libs/types/` | Distinct internal contracts actually used by producers and consumers | An unused parallel type hierarchy or unstructured dictionaries for known shapes |

SQLAlchemy does not automatically give mapped classes Mongoose-style CRUD methods.
Use explicit methods or domain-owned persistence functions beside the mapping;
do not pretend that renaming ORM files implements this boundary. The service
decides what may happen; the schema operation carries out the decided write.
Reads may remain in services, subject to domain ownership. Shared enums/types do
not import services or routers. DTOs describe the request/result; they are not an
extra execution layer between the service and persistence.

One outer business operation coordinates the transaction. Every participating
schema operation uses the same supplied Session and may flush when required,
but does not commit or silently roll back another participant's work. Preserve
SQLAlchemy autobegin behavior, locks, audit hooks and failure recovery. Do not
blindly add a nested `begin()` to a Session that is already active. Include
attribute assignments, relationship/cascade changes, bulk/raw SQL, audit rows,
notification rows and idempotency records in the write inventory. External
notifications/files need explicit failure and timing semantics; they are not
made atomic by a database rollback.

Cross-domain work calls the owning domain's agreed public service operation with
typed inputs/results. Keep transaction ownership explicit for participating
operations. Do not directly mutate another domain's table or import its private
helpers. Keep dependencies acyclic; place coordination at the agreed use-case
entry point. Existing root helpers are migration debt to trace, not an exemption.
No microservice split, generic CRUD framework or second `services/` tree is required.

## Enum and type adoption is system-wide

Audit every mapped table and relevant field, then follow its DTOs, internal types,
services, jobs, reports and frontend consumers. Use the
[table-by-table ledger](../backend/app/libs/enums/README.md#table-by-table-audit)
to distinguish fixed vocabularies, configurable references, free text, projections
and unresolved data. Configurable records can still contain a fixed discriminator.
For a supported value missing from an enum, establish its meaning and add it to
the canonical definition and callers/tests. Do not legitimize corrupt values or
invent a new business rule merely to make historical data validate.

Known fixed-vocabulary fields use actual canonical Enum annotations in input,
update and output DTOs and internal contracts. `status: str = Status.DRAFT.value`,
`Any`, `Status | str`, or copied string Literals do not complete adoption. Check
both omitted and supplied values at runtime: use enum-member defaults or explicit
default validation so a supposedly typed field does not remain a raw string.
Preserve normalization with explicit validators; use `.value` at an existing raw
string boundary rather than assuming `str(member)` returns the stored value.

Enum membership does not grant a transition or permission. Preserve action-specific
subsets, omitted/null update semantics and serialized business values. Document
and test deliberate OpenAPI/validation changes needed for actual typing; an old
snapshot cannot justify retaining untyped fields. Keep existing storage types and
constraints unless an actual database migration is separately authorized.
The six Ismail pilots are rollout steps. Track the remaining domains with owners;
complete declarations without complete consumer coverage are unfinished work.

## Work and verify one business operation at a time

1. **Study and specify:** old behavior, callers, tables/fields, permissions,
   transactions, accepted examples, refusal cases and existing defects.
2. **Implement the approved operation:** move each responsibility to its layer,
   migrate real enum/type consumers and all writers, then freeze the candidate.
   Parallel work uses disjoint ownership; shared writers have one integrator.
3. **Prove technically:** meaningful contract/integration tests, persisted effects,
   refusal/rollback/retry cases and applicable CI. Independently challenge AI tests;
   do not derive every expected value from the implementation being tested.
4. **Inspect the actual website:** use the connected browser/computer and inspect
   rendered screenshots. Exercise each affected action, validation/refusal and
   role, reopen/refresh records, verify saved data and the next department handoff.
   Use an isolated candidate environment. DOM output or a screenshot filename alone
   is not visual verification.
5. **Challenge integrity and recovery:** bounded relevant stress/concurrency on
   isolated data, including real PostgreSQL locking when relevant. Record bounds,
   stop conditions and outcomes. A required skipped or unavailable check is BLOCKED.
6. **Independent AI review, then human:** only passing required evidence earns
   `AI_VERIFIED_AWAITING_HUMAN` for the named operation/revision. Provide the human
   the exact local visual steps, expected results and unresolved findings. Record
   their additional visual/technical approval separately. Never self-approve the
   human gate. Merge, deployment and retirement follow their own authorization.

Keep commands, results, screenshots/observations, database readback, source identity,
review findings and remaining coverage in the task packet. A changed candidate
invalidates affected evidence. Documentation-only changes check consistency,
links and skill metadata; runtime checks are not applicable and confer no runtime
verification status. See [VERIFICATION.md](VERIFICATION.md) for the full procedure.

## Mentor reference and supporting practice

The mentor's inspected Meditech snapshot is
`b4c646ce471efbf6fe984f3315bba366b197281a`; the Pizza House snapshot is
`0039d4752910c05c15995c3239524b450410f72d`. The
[DTO guide](../backend/app/libs/dto/README.md#the-mentors-actual-structure) links
the concrete enum-typed Member input/update/output contracts, service and database
model. Reuse the separation and typed call boundaries, while reviewing each
permission, exposed field and transaction for Milana's actual rules. The references
are examples of discipline, not proof that every detail is safe or should be copied.

The following primary sources support specific practices; the schema-owned writer
location and ordered human gate above are Ismail's project requirements:

- [OpenAI repository instructions](https://learn.chatgpt.com/docs/agent-configuration/agents-md):
  keep durable guidance in repository entrypoints and explicitly reload it when
  an ongoing session needs updated instructions.
- [SQLAlchemy Session lifecycle](https://docs.sqlalchemy.org/en/20/orm/session_basics.html#when-do-i-construct-a-session-when-do-i-commit-it-and-when-do-i-close-it):
  keep transaction/session lifecycle outside individual data-manipulation helpers.
- [Pydantic default validation](https://docs.pydantic.dev/latest/concepts/fields/#validate-default-values):
  defaults are not validated automatically; test the omitted-input path too.
- [Playwright testing practices](https://playwright.dev/docs/best-practices):
  test visible behavior in isolated sessions with stable user-facing locators and
  condition-based assertions. Automated E2E complements the required visual review.
