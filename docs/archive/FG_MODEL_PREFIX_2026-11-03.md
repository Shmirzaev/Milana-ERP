# FG model-number prefix, 3 November 2026

## Request, ownership and source

- User: "add FG hwere and it should start from 202001 number", referring to
  the model creation prefix selector. Follow-up: "use clone_main" after the
  stale origin/main production baseline was reported. No merge or deployment requested.
- Operation: Catalog automatic base-model numbering. Engineering owner Ismail;
  human reviewer Mirshoir; business acceptance Shavkat/operator remains pending.
- Implementation: coordinating Codex session. Independent AI reviewer:
  `/root/review_fg_prefix`, a separate read-only Codex agent; no actionable findings.
- Base: `77d090f69c293f716adf9e2df6227d9543552442`, fetched `origin/clone_main`.
  Worktree `C:\ERP\.codex-work\fg-model-prefix-20261103`;
  branch `codex/fg-model-prefix-20261103`.
- Both live source symlinks and complete source manifests verified against
  `deploy/production-base.json`: `20261102_063110`, manifest
  `becda671a332afe6fe86857ab948be2d686c984e81d02e6e68053ba83cb7a079`.
  Retained rollback is recorded as blue `20261031_092951`; runtime slot files
  require interactive sudo and were not read. No release or business data changed.

## Studied operation and exact change

`models/[id]/page.tsx` reads the prefix list and number from
`GET /api/models/next-number`; Catalog route ->
`models_service.get_next_model_number` -> `numbering_service.next_model_no` ->
the catalog-numbering JSON configuration. The selector renders the returned
sorted keys, so no frontend change is required.

`POST /api/models` -> `ModelIn` -> `models_service.create_model` reserves the
server number again in its outer transaction, writes `models.code` and
`details_json.general.model_no`, and audits creation. Reservation uses the
existing advisory lock and `SystemSetting.write_model_numbering` with the same
Session and `system_settings.value_json.last_assigned`. The Usluga routes use
these same services, with their existing Eco Cotton authorization.

Only one runtime configuration entry is added: `FG`, last-number floor `202000`,
source ID null. Thus the first available number is `FG202001`, followed by
`FG202002`. Existing occupied-family skipping, stale-preview protection,
deletion continuity, rollback behavior and other streams remain in effect.
Permissions, schema, routes, DTOs and workflow stages are unchanged. No downstream
department handoff changes; the result is a normal Catalog base model.

Vocabulary ledger: `models.code` and general model numbers remain business
identifiers; configured prefix keys remain configuration data, not a new enum.
The counter remains existing JSON with integer values. No new fixed-vocabulary
DTO/internal contract or schema migration is introduced. Existing status/type
refactor debt is outside this configuration change.

Allowed paths: numbering JSON, `test_catalog_numbering.py`, this record,
archive index and the short project-context pointer. Generated Next type files
are excluded from the candidate. Legacy `C:\ERP` work is preserved.

## Verification and limits

- RED: all three FG cases failed on unchanged configuration with unsupported
  prefix HTTP 400; these were behavior failures, not dependency/setup failures.
- PASS: 27 tests across Catalog numbering, numbering persistence and numbering
  performance; Ruff on the changed test and `git diff --check`.
- PASS: independent reviewer ran 35 cases across Catalog numbering, persistence
  and October factory workflows. Config SHA256
  `3ecab633db33d77b150549f2d06dbf7e135097761503a98989d5e384e884db53`;
  test SHA256 `08a8b4d02dc50671484d5879987d2f2fb543f014876c86ef883512bd6248a47b`.
- PASS: actual connected Chrome against an isolated local candidate on
  `http://127.0.0.1:13601`, backend loopback `18601`, disposable SQLite and
  seeded synthetic fixtures. Next 16.3.8 dependencies were reused only after
  confirming an identical package-lock hash. The local origin was configured
  explicitly after the first sign-in was refused by the origin guard.
- PASS: inspected screenshots of FG selected with `FG202001`; created that
  synthetic model via the actual form, reloaded and saw `Edit: FG202001` with its
  saved name, then reopened creation and saw `FG202002`.
- PASS: disposable database readback and bounded API integrity check: 40 previews
  without any table-count changes, 20 sequential creates with distinct IDs and
  exact next codes, 20 model-detail readbacks, three refused variant creates
  without row/counter changes, final counter 202021 / next FG202022, unchanged
  XJ/XD previews and all unrelated table counts. Create/readback phase 0.417 s.
  Local scripts/results are preserved under ignored `outputs/fg-*` in this worktree.
- BLOCKED: real PostgreSQL locking/concurrency/recovery verification. Docker
  Desktop's Linux daemon is unavailable and local PostgreSQL binaries were not
  found. SQLite results are not a PostgreSQL pass. No production test writes used.
- NOT RUN: full release CI/build, merge/deployment gates, human acceptance.

Status: implemented and locally exercised; **not AI_VERIFIED_AWAITING_HUMAN**
because the PostgreSQL gate is blocked. No merge or deployment occurred.

## Next verification and human checklist

Run the focused tests with `C:\ERP\.venv\Scripts\python.exe -m pytest
backend/app/tests/test_catalog_numbering.py
backend/app/tests/test_model_numbering_persistence.py
backend/app/tests/test_numbering_performance.py -q` from this worktree.
Repeat FG reservation/collision/rollback/concurrency against isolated PostgreSQL
before advancing the shared verification gate; never point tests at production.

In a fresh disposable candidate, open Models -> Create model, select FG and
expect FG202001. Save a synthetic model, reload its details, then open Create
model again and expect FG202002. Confirm manual numbering and existing prefixes
still work. Record human technical/business review separately; no synthetic
production model is authorized. Application rollback removes this configuration
entry but must preserve any already issued FG identities/counter.
