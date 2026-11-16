# SEC04: image authentication pool starvation, 16 November 2026

The owner requested: "fix it", after a read-only production investigation and
source review. This candidate fixes the reproduced model-file authentication
scheduling defect. It does not establish the initiating request for the incident,
sole personal responsibility, or that every other API concurrency path is safe.

## Source and ownership

- Exact source baseline: `db8d8d64953eb4f9dadc22bb8218942cd0999ac7`.
- Isolated checkout: `outputs/milana-image-auth-fix-20261116/repository`, temporary
  branch `codex/image-auth-pool-fix-20261116`, reconciled onto documentation-only
  `b393dd64871409c27edb2d67eb481e4d7e05b01b`. Application bytes still use the
  production baseline. Existing private and VM checkouts were preserved.
- Human domain owner/reviewer: Dilmurod / Mirshoir; business acceptance: Shavkat.
- Implementation: Codex `/root`, at Ismail's request. Independent AI review:
  `/root/review_image_auth_fix`; no application-code blockers found. This is not
  a recorded human review, merge, release or production acceptance.
- Previously observed active release: blue `20261116_092917`, rollback green
  `20261116_090442`. Production read-only preflight confirmed both live manifests
  and all 2,557 source files match `db8d8d6`, schema `0157`, with unchanged slots.
  No production changes have been made.

## Change and preserved behavior

The old dependency chain authenticated through `CurrentUser` in one synchronous
worker call, then scheduled another synchronous dependency to close the Session.
Under a burst, connection waiters can occupy the worker slots before successful
authentication requests get that second turn to release their connections.

`_require_model_file_token` now opens a short-lived Session, calls the existing
`get_current_user(request, token, db)`, and closes the Session in the same
synchronous worker call. SQL and cleanup remain off the event loop. The factory
is late-bound through `app.db.session`, including in isolated tests. No ORM user
escapes that Session; image filesystem work, generation and streaming run later.

Cookie fallback, Bearer precedence, disabled/deleted account checks, credential
rotation cutoff, factory/band enforcement and idempotency identity binding all
reuse the existing implementation. Filesystem cache revalidation, WebP media type,
database image fallback and signed sales-attachment handling are unchanged.
No browser timeout, pool size, worker count, permission, schema or business rule
was changed. No broader refactor or global admission-control claim is made.

Type/operation ledger: token remains free-form signed credential text; `User.id`,
`is_active`, `tokens_valid_from`, factory policy and band fields are read through
existing typed/schema contracts. No new fixed vocabulary, DTO, ORM mapping,
application write, audit/notification write or migration is introduced.

## Verification

All project runtime checks used resource-limited rootless Docker in verified
VM107. The cached test image required a task-local installation of the pinned
PyJWT 2.15.0; no shared image, package environment or running service was changed.
FastAPI 0.140.0 and SQLAlchemy 2.0.51 match the baseline requirements.

| Check | Result |
| --- | --- |
| Fail first on unchanged baseline | The new actual-route burst test failed with SQLAlchemy `QueuePool` timeouts and HTTP 500 responses. |
| Final focused suite | **35 passed**, zero skipped; includes real PostgreSQL 16.15 and exception cleanup. |
| Related security, fallback/image, pool configuration and upload scheduling suites | **51 passed, 8 skipped**. The eight existing upload PostgreSQL cases require `STABILIZATION_POSTGRES_URL`; they were not claimed passed. |
| Changed-file Ruff | PASS, cached lint image, cache disabled for read-only source. |
| Whitespace/diff validation | PASS. |
| Independent AI code review | No blocking application-code findings; final evidence review recorded separately. |
| Broad backend regression in cached runtime | 6,850 passed, 1,600 skipped, eight failed; original failed report retained. All eight failures also reproduced on unchanged production source. |
| Corrected invoice contract suite | 208 passed, zero skipped. Only stale test assertions changed; invoice generator remains unchanged. |
| Corrected authentication, JWT, transport, image and QR group | 255 passed, zero skipped in the pinned task-local virtual environment. |
| Broad QR/barcode retest with qrcode 8.2 | 1,754 passed, zero skipped. |
| Required PostgreSQL 17 groups | 755 passed, zero skipped, including required/supplemental refactor, dual-engine and numbering gates. |
| Required PostgreSQL 16 groups | Passed, including real upload authorization, concurrency, locking, schema/reservation and business families; exact counts and 17 old-runtime-specific skips remain in the gate ledger. |

The eight broad-suite failures were inherited or test-environment defects: six
invoice assertions required rows taller than 100pt although the separately
approved production layout uses fixed 24pt, 10pt font, unwrapped text and wider
description columns; one detected obsolete python-jose/ecdsa in the cached image;
one subprocess replaced PYTHONPATH and could not import the task-local PyJWT.
The six invoice assertions now enforce the independently documented approved
contract, preserving totals, prices, weights, image, print-header, language and
input-immutability checks. A separate agent reviewed this test-only correction.
The invoice generator and frontend are unchanged.

A genuine bounded-RAM virtual environment matches all 20 runtime pins, includes
PyJWT 2.15.0 and qrcode 8.2, and excludes both obsolete modules and their metadata.
The child Uvicorn process inherits its installed packages. Corrected targeted
runs pass; the original failed full report is not relabeled as a clean full run.
Optional skips not exercised by the separate PostgreSQL groups remain explicit.
Exact-commit CI and security/image gates are still required before promotion.
Detailed evidence is `full-backend-review/final-gate-ledger.json` beside this
task's source checkout. Test counts above overlap and must not be summed.

Burst bounds were specified in the test before running: 80 simultaneous
alternating real file/thumbnail requests; AnyIO 40 worker tokens; actual
SQLAlchemy pool 8 + 4 overflow; one-second test pool timeout; five-second worker
gate; twenty-second total bound. The first DB holders wait until 40 lookups have
started, making the problematic scheduling overlap explicit. The expected result
is 40 HTTP 200 files, 40 authenticated 304 thumbnails, zero leaked checkouts and
a successful notifications API read after load. This is not a production capacity
benchmark and does not use the production database.

The final fixed run met that contract on SQLite (p95 0.879 s) and the isolated
PostgreSQL target (p95 1.067 s). The existing approved-instance fixture verified
the exact private PostgreSQL identity, migrated its owned disposable database,
and completed normal teardown. No PostgreSQL target uncertainty was reported.
Authorization refusal and injected post-checkout failure tests also leave zero
checked-out connections.

## Actual browser and persisted checks

Real Chromium ran through the repository's `qa_visual` MCP client in private
VM107 lanes against the fixed backend and one synthetic user/image. Desktop
1280px and emulated phone 390x844 both visibly render the 320px thumbnail.
Authenticated ETag revalidation returns 304 with zero body bytes. Committing the
synthetic user's `is_active=false` makes retained-cookie file and thumbnail reads
return 401, and the browser visibly renders the denial instead of an image.
Re-enabling that same user restores image rendering. User/role counts remain 1/1
and the source image SHA256 remains unchanged across refusal and recovery.

The first phone native capture was blank despite a decoded DOM image; it is
retained as an invalid visual result. A separate follow-up waited for image decode
and browser paint, then captured both native and browser images. Both were
inspected and visibly contain the image at the correct 390px viewport. Earlier
MCP initialization and reserved-email fixture failures are retained separately;
they are not application passes or unknown business-operation outcomes.

Three CSP console errors were observed in Chromium's direct image viewer under
the unchanged backend CSP. The picture still renders; no CSP relaxation was
made. The follow-up native capture also shows Chrome's development-disk warning;
no shared browser data or caches were cleared. The unchanged Next.js 16.4.3
production build passed lint (14 existing warnings), strict type checking and
every build contract. A real gallery run passed login 200, desktop 1280px and
phone 390px rendering without overflow, file/thumbnail 304 with zero body,
refresh, retained-cookie/ETag 401 after persisted revocation, login redirect
without model cards, and recovery. Initial and final gallery console captures
contain no errors. Synthetic user/role/model/image counts remain 1/1/1/1 with
identical image SHA256. A separate agent inspected the report and screenshots.

The first gallery harness ignored evaluation Error text returned without outer
`isError`, and incorrectly labeled failed login 403 as passing. That report is
retained as `INVALID_HARNESS_RESULT`. The fixture lacked the isolated frontend
origin in its explicit CORS list. Strict Error detection and the explicit local
origin corrected the harness/fixture; distinct `visual-gallery-v2` evidence is
the valid result. Production security policy and application source were unchanged.
EN/RU/UZ content is not changed by this binary-image
authorization operation. Exact private QA lanes for the executed browser flows
were stopped normally; unknown/unidentified discovery resources were preserved.

Raw logs, sanitized browser reports and inspected screenshots are retained in
the sibling `outputs/milana-image-auth-fix-20261116` task evidence directory.
Synthetic credentials remain only in the task's private VM fixture directory.

## Evidence correction and acceptance

The earlier investigation described only SEC04's original 3 October SQLite
packet. The same file's later 27 October follow-up already records PostgreSQL,
browser checks and 80 requests at **8 concurrent**. Those checks must not be
erased or described as absent. The new regression covers the higher scheduling
threshold which that workload did not reach. Authorship is not sole-cause proof.

Human technical/visual acceptance remains **PENDING**. The owner's latest
instruction requests agent/reviewer tests before any commit or PR, followed by
immediate deployment of this bug fix while keeping frontend/deployment audits
separate. It does not grant a new performance exception. Full backend and exact
release gates remain in progress. The human checklist retains adjacent login,
scan/history, notification behavior and production recovery. Broader endpoint
concurrency and production observation remain separate.

There is no push, merge or deployment. Do not mark SEC04 Finished from this
candidate alone. Application rollback does not change business data; no database
rollback or migration is needed for this source-only candidate.
