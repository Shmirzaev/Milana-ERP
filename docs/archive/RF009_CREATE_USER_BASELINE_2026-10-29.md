# RF-009 step 1: create_user baseline — 29 October 2026

## Scope, owner and state

Dilmurod owns this baseline; Mirshoir reviews it. The user explicitly authorized
Codex implementation. Source: `clone_main` `4bdddf4f5c3514a6877e936d97dc0ed4ecd4acfc`;
branch/worktree: `codex/rf009-create-user-baseline` / `.codex-work/rf009-create-user-baseline`.
Only characterization tests and this record are proposed. No extraction, service
interface, DTO/schema change, policy change, `update_user` edit or locking change
is included. Human agreement on the extraction remains pending. This is baseline
capture for whichever operation shape Mirshoir later approves, not approval of
all historical behavior or an AI-verified extraction.

## Trace and compatibility promise

The concrete UI caller is `frontend/src/app/(app)/admin/users/page.tsx::create`:
POST `/api/users` with name/email, nullable role/department IDs, factory, active flag
and an empty access-policy object, without a password. Direct API clients may
supply a password, extra permissions and per-factory policy. The existing HTTP
route `api/routes/admin.py::create_user` remains the public operation under test.

`UserIn` in `libs/dto/catalog/catalog.py` binds input; `require_permissions` requires
`admin.users` or `*`. The route normalizes email, validates a supplied password,
checks role and extra grants, checks duplicate email, normalizes/authorizes factory,
checks policy and references, and enforces name/email storage lengths. It inserts
one User, flushes, optionally inserts a setup PasswordResetToken, queues one create
AuditLog, commits once, refreshes User and then schedules the setup email.
`password_reset_service` hashes tokens/builds URLs and wraps delivery; the actual
external setup sender is replaced by a recording fake in these tests. Permission,
validation, ORM, audit and transaction decisions remain real. No business operation
or DB commit is mocked; one test deliberately raises from `before_commit` to
characterize the existing atomic failure/unscheduled-email behavior.

Writes: `users`, optionally `password_reset_tokens`, and `audit_logs`, all in the
supplied transaction. Reads: `roles`, `departments`, and existing `users` by normalized
email. Role/department rows are not changed by creation. Subsequent login/readback
uses the real auth endpoints. The UI-shaped setup case also consumes its real
setup link, verifies credential/token persistence and logs in. Delivery timing is
observed as `before_commit -> after_commit -> scheduled -> delivered`; the external
sender reads the committed user/token/audit from an independent session.

## Privileged-field characterization

| Field | Current behavior retained | Assertions |
| --- | --- | --- |
| `role_id` | Nullable reference. Managers can grant only permissions they hold. Wildcard admins also cannot assign administrator roles. Superadmins may assign them. The trimmed Super Admin role name is privileged even with no permission tokens. | Exact 201/403/404 and detail, UserOut, persisted role, effective login permissions. |
| `extra_permissions` | Normalized list of strings, not role IDs or enums. Managers grant only owned rights; `*`/`admin.super` require superadmin. Factory-scoped grants for another factory require superadmin. Superadmin retains legacy custom strings. | Exact refusals without rows, canonical list persistence/audit, secondary login isolates grants from primary role. |
| `access_policy` | Omitted/null and `{}` are distinct stored/wire values. Known factories/permissions only; no overlapping allow/deny. Non-superadmin changes stay in selected factory and cannot grant absent/admin rights or escape inventory scope. Deny overrides role and extra grants. | Literal validation details, normalized policy body/rows/audit, primary and secondary login permissions. |
| `is_active` | Defaults true. Any actor authorized to create users may explicitly set true or false; this is not superadmin-only. Null is rejected. | All three creator tiers, inactive login refusal, passwordless inactive users create neither token nor setup email. |
| `factory_code` | Normalized MIL/BST/ECO; assigning another factory requires superadmin. Omitted input defaults to MIL even for an ECO manager; explicit empty string uses selected factory. Null is rejected. | Exact body/rows/audit, allowed and forbidden factories, login in the assigned factory. |

Ordinary actors without `admin.users`/`*` cannot set any of the five fields through
creation. Missing authentication and inactive actors are also refused without
user/token/audit writes. The new tests do not call PATCH `/api/users/{id}`.

## Values and outputs retained, not migrated

- Configurable role IDs and grant strings remain existing data types. No enum or
  type conversion is introduced; factory literals and policy validation remain in
  the existing contracts/helpers. Future type adoption needs its own agreed scope.
- Names preserve whitespace and the existing empty-name acceptance. Exactly 128
  ASCII or Unicode characters and normalized 255-character email are accepted;
  129/256 are refused. Email is trimmed/lowercased; duplicate detection is
  case-insensitive through that normalization. No new email-format/minimum-name
  rule is inferred. Department existence and current refusal precedence are pinned.
- UserOut has an independently written literal field map. Only generated ID/time
  vary; timestamps round-trip to persistence, with naive ISO on SQLite and `Z` in
  the deliberately UTC PostgreSQL test session. Credentials, token hashes and raw
  setup tokens are absent from the response.
- The exact create-audit payload is email, setup-email-queued flag, role, factory,
  extra permissions and policy. Name, department and active flag are not added to
  the historical audit payload by these tests. One user/create-audit row is required
  per success, with exactly one token only for active passwordless creation.
- Password minimum is 12 with existing whitespace/shared-default/letter/digit
  checks. Explicit passwords are hashed and support distinct suffixes beyond
  bcrypt's 72-byte boundary. Omitted/null/empty passwords take the setup path.
  Setup tokens are stored only as SHA-256 digests, unused and about 60 minutes from
  expiry. Client-supplied hashes, token cutoffs, login timestamps, IDs and sewing-band
  IDs are ignored by the existing input contract.

## Verification

The 196 cases run the same 98 HTTP characterizations on SQLite and PostgreSQL.
PostgreSQL uses `pg_approved_instance` ownership and connection checks, a new target
DB, and mapped metadata. This operation uses mapped identity columns; migration-only
generated production columns are not exercised. The shared conftest/migration
fixture is unchanged. The owned database is finalized after the module.

Before extraction, the initial 192-case matrix passed on fresh local PostgreSQL 18
and SQLite, with no skips; the client-owned-field case passed on SQLite, and the
final UI-shaped setup case passed on SQLite and the #322 PostgreSQL 17 container.
Early fixture/expected-error calibration is not a fail-first defect demonstration:
no application correction was made. These are passing current-behavior baselines.

Final test-file SHA-256:
`e053b63125ffd67ad3f61ffedb06f35b7bf1634b19b722f19b771f1059f822c2`.
The unchanged #322 runner was temporarily copied from its PR branch into this
worktree so it tested this candidate, not #322's application checkout. Runner
SHA-256: `997dffb345e9ccd9c1067644969529f71eb3828f0c7a66412ba50c26e6389484`.
That temporary tool copy is not part of the PR. Command:
`python3 scripts/run_local_postgres_tests.py`. The full run used PostgreSQL 17 in
#322's disposable container stack. Ruff and whitespace checks pass.

### Final full-run results

- New characterization module: **196 passed / 0 failed / 0 skipped** (98 on SQLite,
  98 on PostgreSQL). [The 196 executed JUnit cases](rf009-2026-10-29/create-user-baseline.xml)
  are filtered directly from the real full-suite report, not a regenerated test run.
- Whole default collection through #322: **5,591 passed / 3 failed / 1 error /
  0 skipped**, 934.36 seconds. The runner aggregates errors with failures as
  **5,591 passed / 4 failed / 0 skipped** and correctly exits unsuccessfully.
- Existing required PostgreSQL operation groups: **171 passed**; Purchasing/Fabric
  supplement: **17 passed**, with no missing or skipped required identities. These
  are subsets of the full collection, not additional totals.
- Full log: `/private/tmp/rf009-full-final.log`; full JUnit:
  `.codex-work/postgres-results-c7a7fc8a/backend.xml`.
- The first full invocation was stopped to add the actual UI-shaped empty-policy
  onboarding case. It is not counted as completed verification. No test code
  changed during the final full invocation.

| Non-passing baseline case | Existing cause / disposition |
| --- | --- |
| `test_reset_token_revocation::test_postgres_concurrent_sibling_resets_only_one_changes_password` | Fixture's explicit table list omits `sewing_flows`; setup error. Fix already belongs to open PR #322. |
| `test_sewing_daily_report_lock_order::test_postgres_report_write_waits_for_work_order_before_parent[create]` | Metadata-only fixture lacks migration-generated `models.is_legacy_import`. Fix already belongs to open PR #322. |
| Same sewing test `[update]` | Same generated-column fixture defect. |
| `test_stock_adjustment_postgres::test_concurrent_stock_adjustments[batch_delta]` | Stale direct test call passes a string to an enum-typed persistence path; Inventory follow-up remains separate. |

These failures were also exposed before this task. The #322 runner was borrowed
without overlaying its two unrelated fixture repairs onto this current-clone_main
baseline. None of the four is in the new characterization module. The full suite
remains **FAIL**, despite the new baseline and required groups passing with zero
skips. The runner's named containers and test image were removed after execution.

Browser and separate live-stress results are not claimed
for this tests-only baseline. No runtime release, production data or serving host
was touched. Human extraction agreement and Mirshoir review remain pending. After
a later approved extraction, run these same tests unchanged and compare persisted
and HTTP results; no after-extraction parity is claimed yet.
