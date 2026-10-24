# Milana ERP Project Instructions

These instructions apply to the entire Milana ERP repository and every clean
worktree created from it.

## Required context

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
Service responsibilities/interfaces and business policy are human decisions; AI
implements the approved scope. Planning requests do not authorize source refactoring.

Use [bugs/bugs.md](bugs/bugs.md) for active/unverified work. Move entries to
[bugs/finished_bugs.md](bugs/finished_bugs.md) only after recorded human production
verification. Preserve stable IDs and historical evidence. Markdown guidance is
not a substitute for meaningful tests, required CI and independent review.

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
