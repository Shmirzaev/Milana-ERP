# Existing inactive-material batch correction — 29 October 2026

Scope requested: "Fix this so I can edit batch 7148 without changing its material."
The owner then instructed "use clone_main" after stale baseline/access checks
blocked the original attempt. Base: `origin/clone_main`
`002a0aba16f67c6692b13e29a7083d564eae0eb8`. Dedicated worktree:
`C:/ERP/.codex-work/edit-inactive-batch-7148`, branch
`codex/edit-inactive-batch-7148`. At this initial checkpoint, merge/deployment were not yet authorized.

Subsequent owner authorization: "Push and merge this into clone_main, then deploy
it without 30 minut monitoring so I can edit batch 7148 in production. Keep blue
as rollback and don’t replace it, deploy the current change on top of green".
This supersedes the initial local-only scope. Preserve both blue container
identities/images/releases; use verified green as the application baseline,
temporarily route to healthy retained blue only as necessary to stage green
safely, then return traffic to the updated green. Timed monitoring is waived;
all other release gates remain required. No business-row edit is authorized.

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


## Production release completed — 29 October 2026

The owner authorized merge/deployment and explicitly clarified: do not add
Mirshoir or Dilmurod's separate changes. PR [342](https://github.com/Shmirzaev/Milana-ERP/pull/342)
was created under Shmirzaev and fast-forward merged into `clone_main` as
`186110a549d48f42801058241ffcabbb22acdaf9`. Against the original serving green runtime `921d6464`, the only
application change is the inactive-material predicate; the new regression test
and task/release records are supporting changes. Existing green code is retained.

Active backend/frontend: **green `20261029_053553`**, exact runtime `186110a549d48f42801058241ffcabbb22acdaf9`.
Both source manifests: `b5ca28076acb7b740073c32a40b0b0bf7eb818c83a4d84ba79cf51233d60b570`. Source archive contains
1809 files. Blue **`20261028_123531`** remains running
as rollback: both original blue container IDs, images, start times and source
manifests were verified unchanged. Blue was temporarily activated only after
candidate gates passed, so supported slot staging could safely replace green.
No blue container/image was replaced, restarted, removed or rebuilt.

Exact-source [immutable CI](https://github.com/Shmirzaev/Milana-ERP/actions/runs/40824319549) passed full backend/frontend gates
and built both images outside production. The backend regression suite passed
4,838 cases with 538 expected opt-in skips; the separate required PostgreSQL
workflow passed all 165 cases with no skips. Initial scoped tests, seven
PostgreSQL integrity cases, actual isolated browser save/reopen/readback and
20 serial retries remain valid for the byte-identical application change.
Independent application/helper review passed, including two challenged recovery
ordering checks; no human reviewer impersonation or separate engineer changes.

Fresh backup `/opt/milana-erp/shared/backups/milana_erp_pre_20261029_053553.dump`: 96226427 bytes,
1246 restore objects, SHA-256
`145fa805bfc393bb8b9eec500618db8135dfa6c2326fad9cc330fccd9b33f109`. Restore-list/0600/hash checks passed.
Schema verification was a no-op at `0149_besttex_cutting_access`.

Temporary exact-image verification containers were checked on loopback-only
ports while old green served. A GET-only browser proxy explicitly connected
the candidate frontend and candidate backend; its ephemeral existing-admin token
stayed in process memory, and literal Host/Origin/cross-site guards were enforced.
The proxy initially refused browser navigation with 403 because the extension
classified it as cross-site. A reviewed exception permits only top-level GET/HEAD
document navigation; cross-site fetch/iframe, writes and literal Origin:null
remain refused. The initial screenshot CDP capture timed out; the supported
browser screenshot API subsequently captured the inspected public editor.
Candidate and final public batch-7148 reads, unauthenticated refusal, actual
browser editor opening and source-guard checks passed without submitting a
production correction. Authentication GET heartbeat metadata is expected.

The 120-sample alternating old-green/candidate gate and final public comparison
passed the existing median/p95/payload budgets with identical result counts.
All four internal/public health/login checks passed. Immediate postflight verified
source/image/slot/router identity, two backend workers, zero restarts/OOM/runtime
error markers, database headroom/revision, zero invalid indexes and disk bounds.
The first postflight attempt failed because `docker top -eo args` requires a PID
column on this Docker version. Sanitized inspection confirmed both workers.
The independently reviewed inspection-only correction uses PID/PPID/args and
requires exactly two spawn workers sharing the existing Uvicorn parent;
the corrected full postflight passed. No runtime change or restart was needed.
Temporary verification containers were removed by their exact recorded IDs;
final green and retained blue checks passed again afterward.

Batch 7148's material, inactive state, current quantity, Count and stock ledger
fingerprint remained `4a787022af231dd390bd27e5434973663597602036f0e875cb2fd71b1526bcc8` across the deployment. No production
business rows were created, corrected, reactivated or reassigned by this task.
The existing quantity was 120.4 kg, Count
24 at verification; the earlier screenshot's
320.4 kg was not used as a production correction target.

The owner explicitly waived the 30-minute monitoring window. Timed observation
was **not performed**, and no monitoring automation was created. All other gates
above were executed. Human/operator business acceptance remains pending: edit
real batch 7148 with its material unchanged, save and reopen the intended field.

Backend image: `ghcr.io/shmirzaev/milana-erp-backend@sha256:f4d092e15e269fda2701fab4129987279f492021f48e100f8afea3fc0948cf9e`.
Frontend image: `ghcr.io/shmirzaev/milana-erp-frontend@sha256:6daae69a9acf2617d966a801c5ea8017171d69b5cdead9b2a3fc8aec47f853dc`.
Transient detailed evidence is under `outputs/deployment/` in the dedicated
worktree; the production screenshot is `outputs/deployment/production-editor.jpg`.
