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

Always verify both production manifests and slot states. Never assume the task
title, local checkout, GitHub `main`, or a historical release is current.

## Working-tree rule

The legacy `C:\ERP` checkout contains extensive preserved work and must not
be used as a release source. Never reset, discard, overwrite, or broadly
reformat it. New work starts in a clean worktree from the latest exact
production-baseline branch. Port only the reviewed change.

Before deployment reconcile:

1. exact active production source and manifest;
2. `deploy/production-base.json`;
3. the clean change branch;
4. GitHub state.

A mismatch is a hard stop.

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
- Cutting shortfall and replacement work remain visible and traceable.
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

1. update `docs/PROJECT_CONTEXT.md` and its date;
2. record active/rollback releases and slots;
3. keep secrets out;
4. mirror durable context to
   `C:\Users\User\Documents\Obsidian Vault\Milana ERP - Project Context.md`
   when accessible.

