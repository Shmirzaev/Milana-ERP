# Existing inactive-material batch correction — 29 October 2026

Scope requested: "Fix this so I can edit batch 7148 without changing its material."
The owner then instructed "use clone_main" after stale baseline/access checks
blocked the original attempt. Base: `origin/clone_main`
`002a0aba16f67c6692b13e29a7083d564eae0eb8`. Dedicated worktree:
`C:/ERP/.codex-work/edit-inactive-batch-7148`, branch
`codex/edit-inactive-batch-7148`. No merge or deployment is authorized here.

Inventory owner: Ismail; human reviewer: Mirshoir; operator acceptance: Shavkat.
Codex root implements; independent Codex `/root/inactive_batch_review` reviewed
without editing and found no actionable findings. These assignments do not
claim human review or production acceptance.

## Operation and exact change

The real inventory editor always includes `item_id`, including when only Count
changes. Its PATCH route retains `storage.items`/`storage.receive` authorization
and delegates to `models/inventory/stock_service.py:update_batch`. That service
checks material scope, force permissions, batch locking, Eco custody, reserved
quantity, unit and warehouse compatibility, then batch/item changes, ledger,
archive policy, audit and the outer commit. An unchanged inactive item previously
hit the same refusal as a reassignment to another inactive item.

Change only the inactive-material predicate: refuse an inactive target when its
ID differs from the current item's ID. Existing same-item corrections work;
another inactive target still returns 409, including with `force=true`.
The existing relink path runs only when the material actually changes.

No DTO, schema, enum vocabulary, type, persistence boundary, transaction ownership,
permission or frontend code changes. `Item.is_active` remains the existing Boolean
and `StockBatch.item_id` remains the existing foreign key. Broader batch persistence
extraction/type adoption is existing debt outside this exact bug-fix scope.

## Evidence

- Before the service change, the new regression returned the exact inactive
  material 409 for both ordinary and forced same-item saves: 2 failed/2 passed.
- After the fix, inventory master data, batch correction bounds, QC, access/restore,
  movement integrity and the four new cases: **119 passed, 7 opt-in PG skips**.
- All seven opt-in movement PostgreSQL locking/integrity cases were then executed
  on an owned loopback PostgreSQL instance: **7 passed, no skips**. Tests created
  their own schemas; production was never connected. QA used candidate metadata,
  not a migration rehearsal; no schema/migration changes are proposed.
- Independent reviewer reran the new tests and relevant bounds/access tests:
  **30 passed** (overlaps the above, not additional unique cases).
- Actual connected Chrome used the candidate frontend and backend with owned
  local PostgreSQL. Synthetic batch 7148 had 320.4 kg and an inactive current
  material. The UI saved Count=24 without changing the selection; refresh and
  reopen showed Count=24, the original material and no error. The screenshot was
  visually inspected. Direct persisted readback retained the inactive Boolean,
  material ID, 320.4 kg and its single receipt movement. Browser warning/error
  capture was empty after the successful workflow.
- Bounded post-browser recovery workload: 20 serial full-editor saves, maximum
  concurrency 1, 5-second request timeout, stop on the first error or integrity
  mismatch. **20/20 passed**, p95 10.58 ms, maximum 10.98 ms locally. Pre/post
  material, inactive flag, Count=24, quantity and movement count were identical.
  This is retry/integrity evidence, not a production capacity claim.
- Scoped Ruff, Python compilation and `git diff --check` passed.
- Frontend source is unchanged from recorded runtime `921d6464`. The first local
  dev launch failed because Turbopack rejects the external dependency junction;
  restarting with supported Webpack succeeded. Initial browser navigation before
  readiness returned connection refused; the ready server was then verified.
  Next's generated next-env.d.ts changes were restored before commit.
- No frontend build/full backend suite was rerun for this one-predicate backend
  change. Existing deprecation/Pydantic warnings remain. No production data,
  quantity, master material status or release was changed. QA services were stopped.

Local transient evidence: `outputs/qa/saved-count.jpg`, `postgres-tests.log`,
`repeat-saves.json`, backend/frontend logs and the owned QA runner. These are
ignored artifacts, not release source.

## Handoff and human checklist

Scoped candidate: **AI_VERIFIED_AWAITING_HUMAN**; no production-fix claim.
Recorded production baseline remains green `20261029_042945`, retained blue
`20261028_123531`, database `0149_besttex_cutting_access`; this task did not
independently reverify live release state. No production business rows touched.

Human checklist after separately approved integration/deployment: open real
batch 7148, retain its material, edit the intended receipt field, save, refresh
and reopen; confirm the field persisted and material/stock remained correct.
Check an active-material batch edit as the adjacent working operation.
Another inactive material must remain unavailable/refused. No new receipt,
reservation, Cutting, Sewing or Packaging handoff is introduced by this edit.
