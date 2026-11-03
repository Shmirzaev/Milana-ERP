# RF-009 step 2: create_user extraction candidate — 3 November 2026

## Decision, source and boundary

Dilmurod approved every recommended decision in the local
`RF009_EXTRACTION_PROPOSAL.md` on 3 November under Mirshoir's delegation.
Ismail is the requested independent human reviewer; Shavkat and operators retain
the business/visual acceptance gate. The candidate branch
`codex/dilmurod-rf009-create-user-20261103` starts at the access-policy split
`32c97e09` (#371). That prerequisite has already merged into `clone_main`.
No production data, release or slot is touched.

The only operation moved is `POST /api/users`. The route retains `UserIn`, the
active-user and effective `admin.users`/`*` dependency, 201/`UserOut`, and
post-commit background scheduling. `models/identity/users_service.py::create_user`
retains the exact ordered checks, hashing, token/URL orchestration and audit
payload, then commits once and refreshes before returning `(User, setup_url)`.
It repeats the effective creation grant check for direct service callers.
`models/identity/access_service.py` holds the unchanged grant and policy checks
used by create, PATCH, preview and role creation. The separate policy leaf from
#371 remains below it; neither lower helper imports `access_service`.

## Operation and type ledger

| Step | Read, decision or write | Owner |
| --- | --- | --- |
| Bind and authorize | `UserIn`, active actor, effective permission | route/dependency |
| Check in historical order | normalized email and password, role and extra grants, duplicate email, factory, policy, role/department, lengths | Identity service and shared access helpers |
| Insert/flush | `users`; ID before dependent rows | `schemas/identity/user_persistence.py` in supplied Session |
| Optional insert | `password_reset_tokens` only for active passwordless account; digest and expiry, never raw URL | existing reset service delegates to Identity schema writer |
| Audit/commit/refresh | one create/User audit with unchanged fields and audit-chain hooks; one creation commit | Identity service and existing audit schema writers |
| Delivery failure | setup email scheduled after commit and refresh; sanitized admin `notifications` in a separate Session and transaction | existing reset service delegates row adds to `core_persistence.add_notification_row` |

Role and department are reads, not mutations. Existing configurable role IDs,
grant strings, access-policy maps, and factory codes are intentionally retained;
no enum or DTO/API-schema change is part of this parity extraction. System-wide
canonical type adoption remains an unresolved separately owned rollout. No
idempotency record is added. Existing refresh failure leaves committed rows
without scheduling email; a process crash in that window still needs an
outbox/reliability decision outside RF-009.

## Evidence and gates

The unchanged #345 characterization file has SHA-256
`e053b63125ffd67ad3f61ffedb06f35b7bf1634b19b722f19b771f1059f822c2`.
Using #322's disposable PostgreSQL 17 runner, the exact split parent and the
extracted candidate each passed **196/196** (98 SQLite + 98 PostgreSQL), with
zero skips. Local logs and JUnit reports are in the branch worktree's excluded
`.codex-work/rf009-evidence/`.

Separate gap tests cover delivery false/exception, notification recipients and
redaction/rollback, refresh/scheduling failure, direct-service refusal,
PostgreSQL role deletion after validation, and bounded duplicate/concurrent
audit submissions. Adjacent caller tests cover PATCH, access preview, role creation
and forgot password. The final focused gap/adjacent run passed **92/92, zero
skips** on the approved disposable stack. Independent read-only AI review found
no actionable source issue; the reviewer did not rerun tests or perform a
browser check. Ruff passes. The exact-source #322 full suite finished with
**5,810 passed, 1 failed, 0 skipped and 36 subtests passed**. Its required
PostgreSQL groups and 17-case supplement both passed. The sole failure is the
unchanged S06 direct test `test_concurrent_stock_adjustments[batch_delta]`:
it supplies `movement_type="adjustment"` as a string while the Inventory
schema writer reads `.value`. The [#322 clean-base evidence](LOCAL_POSTGRES_RUNNER_2026-10-29.md)
already reproduced this same test-contract failure; no Inventory source or
test is changed here. Ismail owns Inventory. The full-suite gate is **FAIL**
for this pre-existing external test; zero-skip target is met.

The exact-branch frontend production image built with Next 16.3.8, including
its build contract tests and TypeScript. In an isolated local stack (PostgreSQL
17, built backend/frontend, Mailpit, local internal TLS proxy), Chromium used
the real Admin Users form to create an active Sales test account without a
password (201). Mailpit captured its setup email. The reset page accepted the
link and new password (200); the new account logged in, opened Profile, and the
admin reopened Users. The agent inspected desktop Users/setup and phone
Profile/Users screenshots at the excluded worktree evidence path; the account,
role and email were visible without a reported page error on the admin page.
Direct database readback found exactly one pilot user, one **used** setup token,
one create audit and one reset-password audit. The first local pilot was
blocked by a reserved `example.test` fixture address; a second run identified
the production reset proxy's HTTPS-only API URL requirement. Both were fixed
only in the isolated stack (valid `example.com` test address and internal TLS),
then the same workflow passed. The earlier failed pilot accounts remain only
in that disposable database.

After the visual pilot, the predeclared bounded localhost run completed in
1.18 seconds: four unique creates returned 201; two same-email requests
returned 201 and the historical uncaught 500; a Sales-role create returned
403. The largest observed request latency was 0.315 seconds, under the
10-second bound. Direct PostgreSQL readback found five distinct stress users,
five create audits, zero setup tokens and no denied user; audit-chain verify
returned valid, and the site remained healthy. This proves local integrity
under this seven-request bound, not a production capacity target.

**Bounded integrity scenario declared before the full-suite repetition:** on a
fresh disposable PostgreSQL database, hold two same-email requests after both
duplicate checks and before either insert; then hold four unique-email requests
after their user flushes and before audit, all with an authorized test actor.
The running local-stack follow-up also sends one denied-role request.
Concurrency peaks at four; seven request attempts create at most five users and
five create-audit rows. The two waves have a 60-second combined stop limit,
with a 30-second deadline for any request and 10-second target for observed
per-request latency. The four unique requests must all return 201; the
duplicate wave must produce one 201 and one historical uncaught database-race
500. Stop on any unexpected error, extra/partial row or broken audit chain.
The denied request must return 403 without a row.
Environment: disposable local Docker PostgreSQL 17, one app process and at most
four concurrent sessions; no production or shared database. This is a local
integrity check, not a production capacity or latency service-level claim.

**Current gate status:** baseline, focused, lint, required PostgreSQL groups,
exact-image build, local visual/SMTP/database readback and bounded local
integrity PASS. Full suite FAIL on the unchanged S06 test. Connected-browser
human review and business acceptance remain pending; this is not AI_VERIFIED.

**Rollback:** revert this one operation PR on the integration branch if needed;
the old route body is preserved at parent `32c97e09`. Do not run both paths for
one request. No schema migration or data backfill is required.
