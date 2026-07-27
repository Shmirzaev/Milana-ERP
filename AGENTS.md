# Milana ERP Project Instructions

These instructions apply to the entire `C:\ERP` repository. New Codex tasks
opened in this project must use this file as persistent project context.

## Required Context

Before planning or making a substantial ERP change, read
`docs/PROJECT_CONTEXT.md`. It contains the consolidated decisions, production
topology, business rules, security findings, deployment state, and unfinished
work from the project's previous chats.

For a narrow question, read at least the relevant sections of that file before
answering. Do not rely only on a task title or the current Git commit.

## Project Summary

Milana ERP is the real production system for a garment/textile factory, not a
demo. Its core lifecycle is:

`Sales Order -> Planning -> Cutting -> Bundle QR/barcode -> optional Printing
-> Sewing -> Packaging -> Package QR/barcode -> Finished Goods -> Shipment`

It also contains branded-stock, Besttex, Eco Cotton, inventory, purchasing,
reservations, waste, payroll, finance/1C, customers, audit history, forecasting,
traceability, tasks, notifications, daily sewing reports, role management, and
an MCP/AI assistant.

The stack is FastAPI, SQLAlchemy, Alembic, PostgreSQL, Next.js, React,
TypeScript, TailwindCSS, and Docker.

## Production Source of Truth

- Public domain: `https://erp.milanapremium.uz`
- PostgreSQL VM: `172.16.10.3`
- Backend VM: `172.16.10.4`
- Frontend VM: `172.16.10.5`
- Production releases: `/opt/milana-erp/releases/<release_id>`
- Active symlink: `/opt/milana-erp/current`
- Backend container: `milana-backend`
- FastAPI container port `10000` is published as VM port `8000`.
- `DEPLOYMENT.md` is the only supported production deployment procedure.
- Vercel, Render, and Hugging Face deployment notes are historical.

On 2026-07-23, production was explicitly rolled back to release
`20260723_065753`. Do not assume that later same-day releases remain live.
Verify the current release and behavior before making follow-up changes.

The sales-to-warehouse item-detail notification was implemented and tested
locally, but the production release containing it was rolled back.

## Working-Tree Warning

This repository has historically contained extensive uncommitted work and was
11 commits behind `origin/main` when this context was written. Treat that as a
snapshot, not a permanent fact: always run fresh Git checks.

Never discard, reset, overwrite, or broadly reformat existing local changes.
Before deployment, reconcile:

1. The active production release.
2. The current local working tree.
3. GitHub `origin/main`.

Use a clean staging checkout or worktree for reconciliation and deployment.
Do not deploy blindly from only local HEAD or only GitHub.

## Safety and Scope Rules

- Make the smallest exact change requested.
- Do not create models, production orders, stock, packages, shipments, users,
  or other business data unless the user explicitly requests it.
- Do not deploy unless the user asks for deployment or the request clearly
  includes it.
- Preserve unrelated work and data.
- Back up production PostgreSQL before migrations or material data changes.
- Keep the active release untouched until builds and migrations succeed.
- Keep a working rollback release and run all four health checks from
  `DEPLOYMENT.md`.
- Never expose or repeat passwords, tokens, private keys, or `.env` values.
- Credentials pasted into old chats must be considered compromised and rotated.
- Verify frontend visibility and backend authorization for every permission
  change.
- Test the complete department handoff affected by a workflow change.
- Report the active release, data touched, checks run, and unresolved risks.

## Stable Business Rules

- Creating a Production Order starts Cutting automatically.
- Optional stages are skipped when not required.
- Cutting overproduction lifts downstream Sewing, Packaging, and Storage plans
  to the real quantity.
- Cutting shortfall and replacement work must remain visible and traceable.
- User-facing pages show business names/numbers, not raw database IDs.
- Sales prices are net; tax calculation is not used.
- Package creation must respect selected-batch packed quantities and partial
  packages.
- Finished-goods stock must be backed by validated packaging/receipt evidence.
- Batch-row material pictures affect only that exact stock batch.
- Deletion must be narrow and blocked for reserved, linked, or used records.
- Important UI text supports English, Russian, and Uzbek.
- Tablet, phone, scanner, print, and label usability are production concerns.

## Known High-Risk Areas

The 2026-07-11 deep audit confirmed high-risk authorization and business-logic
problems involving cross-stage work-order mutation, finished-goods stock
minting without packaging evidence, shipment scan bypass, delivery before
shipment, client-controlled payroll amounts, premature/arbitrary invoicing,
and missing sewing-factory scope checks.

Do not assume these are fixed unless current code and regression tests prove it.
The audit hash chain has also repeatedly failed at record `#744`.

Audit evidence is under:
`.codex-work/deep-security-quality-audit/final/`

## Context Maintenance

After work that materially changes production state, architecture, business
rules, permissions, deployment, or open risks:

1. Update `docs/PROJECT_CONTEXT.md`.
2. Refresh its `Last updated` date.
3. Record the active release or rollback.
4. Keep secrets out of the document.
5. When accessible, mirror the same durable changes to the Obsidian note at
   `C:\Users\User\Documents\Obsidian Vault\Milana ERP - Project Context.md`.
