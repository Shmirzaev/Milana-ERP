# Milana ERP Project Instructions

These instructions apply to the entire Milana ERP repository and every clean
worktree created from it.

Start implementation/review with the [engineering workflow](docs/ENGINEERING_WORKFLOW.md):
it defines each layer, schema-owned writes, system-wide enum/type adoption and
the per-operation AI-then-human gates. Keep folder guides consistent with it.

## Owner's required work cycle

26 October 2026: Ismail reaffirmed this workflow after an agent omitted enum work
and claimed completion. Preserve his direct instructions and accepted corrections
in the task record; a summary, old completion claim or worker brief cannot remove scope.

Work **one business operation at a time**:

1. Study the old source and complete affected behavior: routes, services, every
   caller, DTOs, database definitions/values, permissions and downstream handoffs.
2. Inventory every relevant value/type and move the approved operation to its
   correct existing layer. Track converted, intentionally retained and unresolved items.
3. Pass meaningful automated checks on the candidate, then use the user's connected
   computer/browser to visually exercise the actual website, inspect screenshots,
   reopen the records and check persisted database effects and adjacent workflows.
4. Run the bounded relevant stress/integrity/recovery checks. A missing required
   test, browser or database check is BLOCKED; do not claim a pass.
5. Only after independent AI review and all required evidence passes, mark
   **AI_VERIFIED_AWAITING_HUMAN**. Supply the human's local visual checklist and wait
   for recorded human review. This state is not approval to merge, deploy or retire paths.

Use [VERIFICATION.md](docs/VERIFICATION.md) for the task packet, evidence and human
gate. Audit enums/types [table by table](backend/app/libs/enums/README.md#table-by-table-audit),
not by file/class count. Parallel workers may own disjoint operations; overlapping
operations have one writer and must pass combined verification. Never call an
entire area complete while its operation/type ledger contains unexplained gaps.

## Required context

### Schema-owned writes: owner's explicit target, 26 October 2026

Ismail requires routes -> business services -> schema-model persistence operations.
The earlier namespace move did not implement this boundary. Services keep business
rules, permissions, calculations and one outer transaction; schema-owned operations
perform inserts, updates and deletes using that same supplied Session. Include mapped
attribute/relationship mutations, indirect writers, audit, notifications and idempotency
in the operation trace. Persistence helpers must not commit, change lock order, import
services/routes or introduce a generic CRUD framework. Preserve business values and
storage; identify and test intentional typed-contract changes described below.
Migrate and verify one complete operation before broad enum/type adoption;
do not claim all schemas or all system-wide enums are complete from moved files.

The owner's system-wide mentor-discipline goal requires actual canonical Enum
annotations in fixed-vocabulary DTOs and internal types, used consistently by
schema defaults/constraints, services and relevant consumers. An enum-backed
default on str/Any or Enum|str does not satisfy it. Preserve business values,
normalization and action subsets; document/test intentional API-schema or validation
changes required for real typing instead of retaining str only for OpenAPI parity.
Configurable/free-form fields remain appropriate data types. The six Ismail pilots
are rollout units; remaining domains retain named owners and pending coverage.

Before a substantial change, read `docs/PROJECT_CONTEXT.md` and
`DEPLOYMENT.md`. For a narrow question, read their relevant sections. Do not
rely only on a task title, Git commit, local checkout, or GitHub branch.

## Project

Milana ERP is the real production system for a garment/textile factory. Its
core lifecycle is:

`Sales Order -> Planning -> Cutting -> Bundle QR/barcode -> optional Printing
-> Sewing -> Packaging -> Package QR/barcode -> Finished Goods -> Shipment`

It also contains branded stock, Besttex, Eco Cotton, inventory, purchasing,
reservations, waste, payroll, finance/1C, customers, audit history,
forecasting, traceability, tasks, notifications, daily sewing reports, role
management, and an MCP/AI assistant.

The stack is FastAPI, SQLAlchemy, Alembic, PostgreSQL, Next.js, React,
TypeScript, TailwindCSS, Docker, and HAProxy blue-green runtime slots.

## Production source of truth

- Public domain: `https://erp.milanapremium.uz`
- PostgreSQL VM: `172.16.10.3`
- Backend VM: `172.16.10.4`
- Frontend VM: `172.16.10.5`
- Releases: `/opt/milana-erp/releases/<release_id>`
- Current source: `/opt/milana-erp/current`
- Runtime state: `/opt/milana-erp/runtime/slots.json`
- `deploy/production-base.json` records the Git production baseline.
- `DEPLOYMENT.md` is the only supported deployment procedure.
- Vercel, Render, and Hugging Face deployment notes are historical.

Before release work, verify both production manifests and slot states. Never assume
the task title, a local checkout, a branch head or a historical release is current.

## Shared branch and working-directory rule

The owner confirmed clone_main is the shared production/integration branch.
Do not use stale origin/main as the base or merge destination. A branch head does
not establish the exact active production release.

Keep each engineer/agent's working directory isolated. The legacy C:\ERP checkout
contains preserved work: never reset, discard, overwrite, broadly format or release
from it. Continue a task's existing dedicated worktree when suitable.

The owner's current choice is one shared integration line. Do not create a long-
lived refactor branch. When directly working on clone_main, use separate clean
clones/checkouts and serialize landing through one responsible integrator. Temporary
task branches are an alternative only if accepted by the team. Branch choice never
authorizes concurrent writers to one checkout or force-pushing over another person.

Before implementation, inspect current Git state and recent production fixes. For
release work, reconcile the exact active sources/manifests/slot states, production-
base.json, candidate and GitHub. A mismatch blocks release, not read-only analysis
or explicitly requested planning documentation. The existing documentation worktree
may be used without claiming it is a verified production baseline.

Before landing, re-fetch, reconcile overlapping changes and test the exact combined
revision. Stage only intended paths. Do not broadly add, reset, clean or stash the
legacy checkout. An urgent factory fix invalidates stale candidate evidence.
Push/merge and deployment still require the user's authorization. Releases use an
exact reviewed clean commit and DEPLOYMENT.md, never uncommitted files.

At handoff report worktree, branch, commit, actual checks, push/merge and deployment
state. Keep the human summary short.

## Shared refactor discipline

For monolith refactoring, read [.agents/skills/milana-refactor/SKILL.md](.agents/skills/milana-refactor/SKILL.md)
and the relevant sections of [docs/REFACTOR_PLAN.md](docs/REFACTOR_PLAN.md). Read the README.md only in the
affected architecture folders. Claude Code uses the same rules via /milana-refactor.
For new or extended features, use [.agents/skills/milana-feature/SKILL.md](.agents/skills/milana-feature/SKILL.md).
Use [docs/TEAM_OWNERSHIP.md](docs/TEAM_OWNERSHIP.md) to name the engineer and reviewer
before editing. [docs/AGENT_SKILLS.md](docs/AGENT_SKILLS.md) explains team invocation.
Both skills are versioned with the source; never substitute a personal copy of old rules.
Target business services live in backend/app/models/<group>/*_service.py.
This clone_main documentation update does not integrate draft PR #308; current
root services and mixed DTOs remain until their reviewed operation is migrated. SQLAlchemy definitions
and registration live in backend/app/schemas/; Pydantic contracts live in
backend/app/libs/dto/<business-group>/. The namespace separation is implemented.
Do not recreate services/, put ORM mappings in models/, or put DTOs in schemas/.
Business-operation extraction and visual/production acceptance remain separate work.
Service responsibilities/interfaces and business policy are human decisions; AI
implements the approved scope. Planning requests do not authorize source refactoring.

Use [bugs/bugs.md](bugs/bugs.md) for active/unverified work. Move entries to
[bugs/finished_bugs.md](bugs/finished_bugs.md) only after recorded human production
verification. Preserve stable IDs and historical evidence. Markdown guidance is
not a substitute for meaningful tests, required CI and independent review.

## Implementation execution

- MiniMax M3.1-Flash performs implementation. Codex orchestrates, integrates,
  independently reviews, and tests visually.
- Use two MiniMax implementation sessions, each requesting up to three scoped
  subagents (six total), when the runtime supports it. Give them separate working
  directories and disjoint file ownership.
- Each session reports its actual model, workers started, changed paths, and
  checks run.
- Codex owns integration, independent review, visual E2E, and bounded stress.
  Human engineering and business review, and the deployment gates, remain.
- Session capacity, speed, and token cost (for example free or unlimited
  tokens) are not permanently verified facts; treat them as capacity to
  observe per run.
- If MiniMax is unavailable or a worker is stuck, report the blocker and
  recover or reassign inside MiniMax. Do not silently substitute Codex for
  implementation.

## Verification gates

For every completed runtime migration, bug fix or feature, follow
[docs/VERIFICATION.md](docs/VERIFICATION.md): meaningful automated checks, actual
browser/computer visual E2E, then bounded relevant stress and data-integrity checks.
Record PASS/FAIL/BLOCKED evidence; missing tools or skipped required tests are not
passes. Do not retire old paths before the required verification and human acceptance.

## Safety and scope

- Make the smallest exact change requested.
- Do not create business data unless explicitly requested.
- Do not deploy unless requested or clearly included.
- Preserve unrelated work and data.
- Back up PostgreSQL before every production migration/cutover.
- Build outside production, stage the inactive slot, warm it, compare it with
  active, and switch only after every gate passes.
- Keep active and rollback slots/releases.
- Never expose passwords, tokens, private keys, or environment values.
- Verify frontend visibility and backend authorization for permission changes.
- Test the complete department handoff affected by workflow changes.
- Report active/rollback releases, data touched, checks, and unresolved risks.

## Stable business rules

- Creating a Production Order starts Cutting automatically.
- Optional stages are skipped when not required.
- Cutting overproduction lifts downstream plans to real quantity.
- Cutting shortfalls and sewing defects remain visible and traceable. Failed pieces do not create replacement work.
- User pages show business names/numbers, not raw IDs.
- Sales prices are net; tax calculation is unused.
- Package creation respects selected-batch quantities and partial packages.
- Finished-goods stock requires validated packaging/receipt evidence.
- Batch-row pictures affect only that stock batch.
- Deletion is narrow and blocked for reserved, linked, or used records.
- Important UI text supports English, Russian, and Uzbek.
- Tablet, phone, scanner, print, and label usability are production concerns.

## Known high-risk areas

Do not assume historical authorization/business-logic risks are fixed without
current regression evidence, including cross-stage mutation, unsupported
finished-goods stock, shipment/delivery bypass, client-controlled payroll,
premature invoicing, sewing-factory scope, and audit hash-chain record `#744`.

Audit evidence is under `.codex-work/deep-security-quality-audit/final/`.

## Context maintenance

After architecture, production, business-rule, permission, deployment, or risk
changes:

1. update the short `docs/PROJECT_CONTEXT.md` summary and its date; put detailed
   dated records in `docs/archive/` and link them from the summary instead of appending
   an unbounded history. Start documentation navigation at `docs/README.md`;
2. record active/rollback releases and slots;
3. keep secrets out;
4. mirror durable context to
   `C:\Users\User\Documents\Obsidian Vault\Milana ERP - Project Context.md`
   when accessible.
