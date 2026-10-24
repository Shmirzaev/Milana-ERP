# Milana ERP: current working context

Updated 2026-10-24. Keep this file short: current decisions, release pointers and
unresolved risks. Detailed history belongs in [the archive](archive/README.md),
not appended here. This summary does not replace live release verification.

## Source and production

- Shared integration/production branch: clone_main. origin/main is stale for this work.
- Continue a suitable isolated worktree; preserve the legacy C:\ERP checkout.
  Use separate engineer work directories and one landing queue coordinated by Mirshoir.
- [DEPLOYMENT.md](../DEPLOYMENT.md) is the only supported release procedure.
  Before release reconcile Git, production-base.json, both manifests and runtime slots.
- Last recorded application release: green 20261024_032622; rollback blue
  20261023_061627; application commit 5c45531db350ba79e2e0167b942530a5b0f9bef8;
  database revision 0148_second_grade_packages. These are historical pointers,
  NOT a fresh live check. See [the complete deployment record](archive/PROJECT_CONTEXT-2026-10-24.md#clone_main-department-dashboards-deployed-2026-10-24).
- That deployment recorded an initial performance failure and rollback, followed
  by reactivation of the same images; public-path tail variation remains unresolved.
  The owner waived the timed observation period. The archive preserves all attempts.

## Architecture and migration state

- Keep the FastAPI/SQLAlchemy/PostgreSQL monolith. Router -> feature service ->
  SQLAlchemy schema models + Session -> database. No microservice/ORM replacement.
- Target: api/routes/ for HTTP, services/ for business operations, schemas/ for
  database schema models, libs/dto/<feature>/ for input/update/output contracts,
  libs/enums/ for fixed vocabulary, libs/types/ for distinct internal contracts.
- CURRENT source still uses models/ for SQLAlchemy and schemas/ for Pydantic DTOs.
  Migrate DTOs and all callers/shims first; only then reuse schemas/ for the ORM
  definitions and their registration/Alembic discovery. No mixed namespace or
  duplicate mappings. No application migration has been implemented by this task.
- Twelve service-group directories and libs guides are documentation scaffolds.
  Existing same-named service .py modules remain authoritative. Do not add package
  initializers that shadow them before coordinated import migration.
- Humans decide business policy, interfaces and cutover; AI implements approved
  scope. Multitenancy is deferred. No deletion quota or table-per-service requirement.

## Work and ownership

- [Refactor plan](REFACTOR_PLAN.md): tasks/dependencies; [source map](REFACTOR_MAP.md):
  current files and proposed homes; [team ownership](TEAM_OWNERSHIP.md): exact assignments.
- Mirshoir: architecture, database integrity, production, packaging, fulfillment,
  release approval. Ismail reviews Mirshoir's changes.
- Ismail: catalog, purchasing, sales, inventory, planning, finance; DTO/enum/type
  conventions. Dilmurod: identity, people/payroll, tasks, shared platform and CI.
- Shavkat: business clarification, priorities and operator acceptance, not technical
  review or migrations. Each code change has an engineer and a separate reviewer.
- Use [active bugs](../bugs/bugs.md) for defects and [finished bugs](../bugs/finished_bugs.md)
  only after named human production verification. Refactoring tasks stay in the plan.
- Shared [skills](AGENT_SKILLS.md): milana-refactor for extraction, milana-feature
  for new behavior; both Codex and Claude use repository-controlled instructions.

## Required checks and open risks

- Follow [verification gates](VERIFICATION.md) after each runtime migration/fix/feature:
  test validity, relevant automated tests, actual visual E2E with screenshot inspection,
  bounded isolated stress, persisted integrity/recovery, then human acceptance.
  Required missing/skipped checks are BLOCKED, not PASS. No production stress/data fabrication.
- Default backend pytest fixtures use SQLite. Real PostgreSQL checks need their
  documented setup/collection; do not infer locking correctness from SQLite success.
- One write path per request and one outer transaction owner. Preserve locks, audit,
  idempotency and side-effect timing. [Retry identity rules](idempotency.md) are active.
- Preserve stable business rules in [AGENTS.md](../AGENTS.md). Particular regression
  cases include sewing 600 received -> 495 then 105, independent Nastils, optional
  stages, and validated packaging receipts before finished-goods stock.
- Historical authorization/audit-chain findings are not declared resolved here;
  consult AGENTS.md and the relevant bug/evidence. OPS01/OPS07 still require the
  correlated factory-path evidence described in [performance evidence](performance-evidence.txt).
- CI branch triggering and automatic recovery improvements in the plan remain
  implementation tasks; skills/docs do not install enforcement or rollback.
- Recovery targets in [DISASTER_RECOVERY.md](DISASTER_RECOVERY.md) remain requirements,
  not proof of measured capacity. Preserve backups, active/rollback releases and evidence.

## Latest documentation work

- Shared skill/ownership baseline: f8719d19; verification gates: c1277680.
- Removed superseded developer/review instructions, consolidated backend/docs into
  docs/, archived dated reports and the full old context, and relocated training
  generation tools under scripts/training/. Runtime code, data, tests, deployment
  settings and test-consumed audit baselines remain unchanged.
- Documentation cleanup is not a deployment. See the final task handoff for its
  publication commit; do not infer current production from a documentation commit.
- Obsidian mirror location from AGENTS.md was unavailable during prior planning;
  no mirror synchronization is claimed. Search archived evidence only as needed.
