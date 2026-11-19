# SEC04: model file session authentication

## Browser-cache follow-up — 2026-10-27

Task / operation / state / direct-user scope and corrections: SEC04 model-file
revocation; **AI_CHECKS_RUNNING**. Browser caching defeated server-side revocation
on the earlier `9c90ea80` candidate. This update changes only model-file response
caching and conditional handling, plus its regression tests.

Baseline / candidate commit or frozen patch+file hashes / runtime build / environment:
Earlier `9c90ea80` sent file `private, max-age=86400` and thumbnail
`private, max-age=604800`; conditional ETag requests returned 200 with full bytes.
Corrected candidate `9f6895a9`, backend Docker image, disposable PostgreSQL 16,
isolated storage/SQLite shared store, Next dev frontend and real Chromium from
[RF-004's local stack](https://github.com/Shmirzaev/Milana-ERP/pull/319).
Alembic reached head. The branch then merged current `clone_main` at `cdcbdfe5`
as `5599482c`; that integration adds the separate invoice fix without changing
SEC04 runtime paths. No serving host or production database was used.

Engineer / reviewer / business acceptance owner: Dilmurod / Mirshoir / Shavkat.
Implementation model/session / independent verification model/session: Codex
implementation and executed checks; independent Mirshoir review pending.

Expected behavior and unaffected control workflow: Active sessions may reuse
cached image bytes only after revalidation; a revoked session gets 401 even with
a retained cookie and validator. Generated thumbnails remain `image/webp`.
Database-backed legacy file fallback uses `private, no-store`. Signed sales
attachments retain their separate policy. No schema, permission scope or business
data change is included.

Operation/caller coverage and table/field/type ledger: Full model-file and
thumbnail routes, `CurrentUser`, filesystem and DB fallback, browser catalogue
thumbnail, `User.is_active`. No table or fixed-vocabulary conversion.

Automated: Four new conditional cases (file/thumbnail × ETag/Last-Modified)
failed on the old handler because it returned 200; the same cases and the
full two-file focused set passed after the fix (**57 passed**, 2 warnings).
`python -m ruff check backend/app`, `python -m compileall -q backend/app`,
frontend lint (0 errors, 10 existing warnings) and strict typecheck passed.
The final full backend suite on the corrected runtime revision passed:
**3,892 passed, 312 skipped, 13 warnings**, exit 0, 567.80 s. The skipped
tests are not claimed verified. Log: `/private/tmp/sec04-cache-final-full-suite.log`.
After the disjoint `clone_main` merge, SEC04 auth, security hardening and invoice
export tests passed together (**91 passed**, 2 warnings); full-app Ruff and
compilation passed on that combined revision.

Test validity: Real Chromium on the first implementation found a thumbnail
`application/octet-stream` regression that the browser treated as a download.
The final helper restores explicit `image/webp`; focused tests and the real
browser check pass. Against final candidate, active conditional GETs through
both the backend and the Next.js `/storage` proxy returned 304 with **zero body
bytes** for the PNG and WebP. Authorization runs before the 304 decision.

Visual E2E: **PASS (technical)**. Real login as isolated Modeling user showed
the model picture on `/models`; direct file and thumbnail both rendered. After
committing `User.is_active = false`, the same cookie produced 401 for both URLs
and rendered the JSON denial. I inspected the model-list, thumbnail and both
revoked-response screenshots; no image remains in the revoked views. Network
trace has both post-revocation 401s, zero page errors; DB readback has inactive
user, one image row and the file present. Evidence:
[network/readback](sec04-cache-evidence/results.json),
[model list](sec04-cache-evidence/01-model-list.png),
[initial thumbnail](sec04-cache-evidence/03-thumbnail.png),
[revoked file](sec04-cache-evidence/04-revoked-file.png),
[revoked thumbnail](sec04-cache-evidence/05-revoked-thumbnail.png).
The RF-004 browser script's initial strict error-message expectation was corrected
in PR #319; SEC04's response contract requires the 401, not that earlier text.

Stress: **PASS (technical; Mirshoir's limits review pending)**. The bounds were
recorded before the run in RF-004: 8 concurrent, 80 alternating file/thumbnail
GETs per phase, 45 s total limit, 5 s request timeout, p95 ≤2,500 ms,
p99 ≤4,000 ms, PostgreSQL client connections ≤20, zero 5xx and post-revocation
200. A separate fresh fixture produced active 80/80 200, post-revocation
80/80 401, fresh-admin recovery 80/80 200 in 2.83 s. p95 by phase:
39.5/24.0/30.4 ms; p99: 43.9/34.9/38.0 ms. Sampled peak DB connections 4,
baseline 2; `/ready` returned 200 after load. Revoked user remained inactive,
image row/file remained. [Full results](sec04-cache-evidence/stress.json).
These numbers apply only to this single-instance local stack.

Independent review findings / resolution / outstanding requirements: Mirshoir
must review the sensitive-workflow limits and candidate. Each revalidation still
performs the session/DB authentication check; 304 saves image transfer but does
not remove that query cost. No production-capacity inference is made. A browser
holding a response cached under the **old** one-day/one-week `max-age` header
will not see this new policy until that old entry expires or its cache is cleared;
the fresh-browser gate cannot prove immediate invalidation of those old copies.

Human checklist: On this candidate, log in as an isolated active Modeling user,
load the model image and thumbnail, revoke that user, retry both with the retained
session and confirm 401 plus inactive DB readback. Repeat with an active account
and an ETag to confirm 304 and no body bytes.

Human technical and visual/business acceptance: PENDING.
Merge / deployment / production operator acceptance: None; no production data touched.
Cleanup/rollback condition and remaining limitations: Disposable stack teardown
removes only its random local project. Rolling back this cache policy restores the
browser-cache revocation gap. Existing old-policy browser caches need a rollout
decision (cache clearing/URL versioning or accepting their remaining TTL) before
production release; don't merge or deploy until review and acceptance.

## Current branch update — 2026-10-25

- Engineer owner: Dilmurod. Independent reviewer: Mirshoir (pending).
  Business rule supplied by the owner: authenticated model-file access is
  intentionally company-wide across MIL/BST/ECO; no per-model/factory scope added.
- Existing branch `codex/sec04-model-file-auth` retained commit `0596ad39` and
  merged current `origin/clone_main` at `ba70e0cb`. The only merge conflict was
  imports in `main.py`: retain current proxy trust, rate-limit token decoding and
  `CurrentUser`/`DbSession`. The handlers still match the original fix.
- Adapted the test ORM import from `app.models` to current `app.schemas` after
  the namespace relocation. Both routes use the auth dependency, which closes
  its session before filesystem access; short-lived DB image fallback is unchanged.

### Automated evidence

Python 3.12.13; isolated temporary virtualenv with the branch's requirements-dev.txt.
Normal test fixtures create disposable SQLite databases/files. No production calls.

- RED: same current tests against the exact `ba70e0cb` main.py handler:
  **13 failed, 11 passed**, exit 1. All 12 warmed-cache revocation combinations
  (file/thumbnail x cookie/bearer x disabled/deleted/credential rotation), plus
  the old-token rotation test, received 200 instead of required 401. This was a
  behavior failure, not collection/dependency failure. The fixed file was restored
  in a finally block in this isolated task worktree.
- GREEN: fixed handler **24 passed**, then **24 passed** again after restoration.
  Tests cover active sessions, missing/invalid/expired credentials, account deletion,
  revocation, fresh-token acceptance, zero checked-out authentication connections
  at path lookup, signed-model-link refusal, unchanged signed sales attachments,
  and company-wide MIL/BST/ECO access.
- Full backend suite: **3,888 passed, 312 skipped, 13 warnings**, exit 0,
  in 569.06 seconds. Skipped cases are not claimed verified; PostgreSQL-dependent
  coverage is unavailable without its disposable DB configuration.
- Separate `python -m pytest -q -ra backend/tests`: **2 skipped** because
  `S06_POSTGRES_URL` is absent. This stock-adjustment suite is outside default
  collection; no PostgreSQL locking pass is claimed.
- Ruff: `python -m ruff check backend/app` — PASS.
- Compilation: `python -m compileall -q backend/app` — PASS.
- Frontend: `npm run lint` — PASS (0 errors, 10 existing warnings).
- Diff review: only SEC04 main.py/test/evidence and tracker/context changes relative
  to `ba70e0cb`; `git diff --check` — PASS. Frontend source is unchanged.
- Local logs: `/private/tmp/sec04-20261025-{red,green,green-restored,full-suite,frontend-lint}.log`.

Commands (from the isolated task worktree unless noted):

```sh
python -m pytest -q backend/app/tests/test_static_file_auth.py
python -m ruff check backend/app
python -m compileall -q backend/app
cd frontend && npm run lint
```

Full-suite command runs from `/private/tmp/milana-font-support`, using existing
external Arial/Arial Bold symlinks needed by this Mac's report tests (no repo font
change), with absolute config and test paths:

```sh
python -m pytest -q -c <worktree>/pyproject.toml <worktree>/backend/app/tests
```

### Remaining gates and release state

- Visual E2E: **BLOCKED**. No isolated running frontend/backend stack and test
  accounts provisioned for real browser login/model-list inspection. API fixture
  tests are not a substitute for screenshots and real UI verification.
- Bounded stress: **BLOCKED**. No isolated running stack/baseline/approved workload
  provisioned for a thumbnail burst and revocation-under-load scenario with pool,
  error/latency and recovery measurements. The sequential pool-release regression
  above is not a load-test pass. No production stress performed.
- Named engineering review and human production acceptance: pending.
- Branch publication is for PR review; no merge to `clone_main`, deployment,
  production data changes or fresh production slot/manifest verification. Retain
  historical production pointers in PROJECT_CONTEXT.md without recertifying them.
- Rollback: reverting this application change restores the old weak file auth;
  there are no schema changes or data writes to undo. Do not claim release-ready
  while required visual/stress/review gates remain blocked/pending.

## Historical implementation evidence — 2026-10-03

Branch: `codex/sec04-model-file-auth`, from `clone_main` at `e808891a`.
Edited in place under real `backend/` paths.

## Donor port

Ported only the model-file authentication changes in `backend/app/main.py`
from develop commit `3881177e4d3cc661387d6591471f2641103b5987`.
Current routes had shifted line numbers, but their serving/fallback structure
matched the donor. No omnibus changes or unrelated donor files were imported.

`_require_model_file_token` now takes `CurrentUser` and `DbSession` dependencies.
The normal authentication dependency rejects disabled/deleted users and tokens
older than the credentials cutoff. The guard immediately calls `db.close()`.
Both full-file and thumbnail routes declare
`dependencies=[Depends(_require_model_file_token)]`, so authentication finishes
and its connection is returned before path lookup, image generation or streaming.
Existing short-lived DB fallback sessions are unchanged.

Model files remain company-wide. No factory, role permission or per-model
ownership restriction was added. Signed sales-attachment behavior is unchanged.

## Fail first: SQLite

Adapted the donor `test_static_file_auth.py`, independently parametrizing both
file and thumbnail routes. Added same-file access for MIL, BST and ECO users.

Original clone_main: **13 failed, 11 passed** in 26.14 seconds.
The 12 revocation cases (both routes x disabled/deleted/credentials-rotated x
cookie/bearer) returned 200 where 401 was required. An additional old-token
rotation test failed. The normal `/api/auth/me` endpoint correctly rejected
those same sessions. Thumbnail caches were warmed before revocation.

```sh
python -m pytest -q backend/app/tests/test_static_file_auth.py
```

The test also checks active sessions, invalid/expired/missing credentials,
new-token acceptance after rotation, authentication connection release before
filesystem access, signed model URLs requiring sessions, unchanged sales-link
policy and company-wide access across all three factories.

Database: normal isolated SQLite test fixtures. No PostgreSQL run.
Logs: `/private/tmp/sec04-before-both.log`, `/private/tmp/sec04-after-both.log`.
No production data, migration or deployment.

## Passing results

Fixed code: **24 passed**, 2 warnings, in 26.33 seconds.
Full existing suite: **2,175 passed, 46 skipped**, 3 warnings, in 653.39 seconds.
Both used the normal isolated SQLite fixtures.

The full suite used the same temporary external Arial/Arial Bold font symlinks
as earlier tasks on this Mac; no repository font changes were made:

```sh
cd /private/tmp/s06-suite-env
python -m pytest -q \
  -c /Users/murmurbek/Code/Milana-ERP/pyproject.toml \
  /Users/murmurbek/Code/Milana-ERP/backend/app/tests
```

Full-suite log: `/private/tmp/sec04-suite.log`.
Ruff (`backend/app`), Python compilation and `git diff --check` passed.
No merge or deployment; no production data touched.
