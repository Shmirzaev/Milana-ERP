# Stabilization QA

Scope: `feat/ismoiljon`, PR #175. **Local synthetic data only. Never use production URLs, credentials, dumps or devices.** Main findings: [audit](../audit_ismail.md); complete baseline: [backlog](audit_backlog.json).

## Run

Install the pinned backend requirements and frontend lockfile dependencies in a disposable checkout. Commands below start at the repository root. Backend fixtures create and reset a temporary SQLite database; concurrency tests need separate PostgreSQL.

```text
cd backend
python -m pytest -q
cd ..
python -m pytest -q connectors/hikvision_attendance
bun run --cwd frontend test:stabilization
bun run --cwd frontend lint
bun run --cwd frontend typecheck:strict
bun run --cwd frontend build
python scripts/run_isolated_postgres_tests.py --pg-bin "PATH/TO/POSTGRES/bin" -q -k postgres
```

The PostgreSQL launcher creates a fresh loopback-only cluster on an unused port, supplies test-only credentials, and stops it in `finally`. It does not connect to the installed service. Diagnostic files remain in its printed temporary directory. Run database-heavy suites one at a time on memory-limited laptops.

For one regression: `cd backend`, then `python -m pytest -q app/tests/<file>.py`. Add `-s` to see query counts. Do not set a PostgreSQL URL manually unless it points to a verified disposable database.

## Acceptance cases

Each row names a repeatable regression. Browser checks complement these; they do not prove database concurrency.

| Bug | Test / where | Expected result |
| --- | --- | --- |
| ST01 | `test_purchase_receipt_idempotency.py`; Purchasing → Receiving | Receive 5; lose the response; reload and retry the saved request. Still 5, one receipt. Changed payload with the old key rejects. Concurrent same-key submissions replay one result. |
| ST02 | `test_inventory_movement_integrity.py`; inventory movement API | Issue 4 from 10: batch and movement agree at 6. Wrong item/batch, unit, location or invalid amount rejects without writes. |
| ST03 | `test_inventory_movement_integrity.py`; warehouse balances | A W1 movement does not change W2. Transfer changes the two warehouse balances but not the global total. |
| ST11 | `test_material_reservation_concurrency.py`; reservation/Cutting APIs | Concurrent claims cannot exceed stock. Retry/release and sibling-batch contention remain consistent; no lock-order timeout. |
| FN02 | `test_payment_integrity.py`; payment and advance allocation APIs | Concurrent payments leave invoice totals/status matching committed payments. Existing overpayment/advance rules remain valid. |
| FN04 | `test_invoice_creation_integrity.py`; `POST /api/finance/invoices` | Concurrent creation for one order returns one invoice, not duplicate billing. Other entry points are not covered by this fix. |
| SEC04 | `test_static_file_auth.py`; `/model-files/...` | Disabled/revoked account cannot download with its old cookie. Active authorized account still can. |
| SEC05 | `test_reset_token_revocation.py`; password reset | After one reset succeeds, sibling links and pre-reset sessions fail. Concurrent reset requests cannot both win. |
| SEC07 | `test_assignment_delete_scope.py`; assignment DELETE | Wrong factory rejects; right factory deletes only the permitted assignment. This does not cover every factory-scoped endpoint. |
| SEC07 | `test_flow_utilization_scope.py`; `GET /api/sewing-flows/{fid}/utilization` | Wrong selected factory returns 403, including Super Admin sessions. Select the explicitly permitted factory to read its line; missing line remains 404. |
| SEC10 | `test_privileged_user_delete.py`; Users → Delete | Limited administrators cannot delete a privileged administrator, including policy-based privilege variants. |
| UI01 | `test-session-recovery.mjs`; authenticated page | Temporary 503/network failure shows recovery without discarding the session. Bounded retry succeeds; genuine 401 redirects to login. |
| UI02 | `test-api-deadline.mjs`; API client | Hanging JSON/form/error response bodies time out; cancellation works; ordinary responses remain unchanged. |
| PY01 | `test-payroll-scan-order.mjs`; Payroll → Scan | Queue badge A, work A, manual A, badge B, work B. Recorded ownership follows the event sequence, not the latest UI selection. |
| PERF01 | `test_package_query_growth.py`; package list | Same rows/filters/order; no per-package query growth. See complexity table below. |
| AT02 | `connectors/hikvision_attendance/test_event_checkpoint.py` | Mock device advertises 3 events but returns 2 then an empty page. No upload/checkpoint advance. Complete retry imports all 3. HTTP/upload retries keep event identities. |
| SEC02 | `test_user_audit_history.py`; Users → Delete/Edit | Delete an account with authored history: 409 and no cleanup. Edit → deactivate works; old session rejects. A concurrent audit insert also preserves actor/hash and rolls back cleanup. |
| API06 | `test_name_authorization.py`, `test-name-authorization.mjs`; profile/pricing | Rename restricted user to `Abbosbek` or matching email. Same session still gets 403 from pricing GET/PATCH; navigation remains hidden. Explicitly granted users retain access. |
| PERF41 | `test_eco_history_query_growth.py`, `test_eco_transfers.py`; Eco transfer history | Pagination/date/order/roll rows/global totals unchanged. Empty page works; historical snapshot is not rewritten. |
| SEC01 | `test_scoped_permission_grants.py`; Users/roles APIs | Limited admins cannot grant wildcard/admin.super or change foreign-factory grants. Legitimate held permissions work; unchanged grants survive profile edits. |
| SEC07 | `test_passport_get_scope.py`; passport GET | Own-factory linked passport returns unchanged data; wrong factory 403; missing record 404. Manual unlinked passports retain the existing read policy. |
| DB04 | `test_fresh_migration_bootstrap.py`; isolated PostgreSQL | Empty database upgrades to 0131; rerun mutates nothing; 0130 row survives upgrade. Exact reviewed schema-drift baseline must match, not silently regenerate. |
| ST05 | `test_accessory_return_balance.py`; accessory issue/return APIs | Stock issue 8 + manual issue 4 allows returns 3+6+3. Retry changes nothing; excess rejects. Warehouse = 20−8+returns; production net = 12−returns. |

For UI QA, start a separate loopback-only frontend/backend with fresh synthetic accounts and database. Block external browser requests and backend connections. Test both a restricted and explicitly permitted account. Inspect the rendered error/success state and browser errors; screenshots must contain synthetic data only. Attendance connector and backend-only concurrency cases use protocol/transaction tests instead of screenshots.

## Measured complexity

Additional acceptance checks:

| Bug | Test / where | Expected result |
| --- | --- | --- |
| AT03 | Connector `test_sync_stage_isolation.py` | Roster fails but events still upload; job reports roster failure. Failed event windows do not advance; TLS failure stops all work. |
| ST06 | `test_accessory_return_concurrency.py`; return API | Two returns of 7 against 10 cannot both commit. Same-key replay creates one return; rollback frees allowance; unrelated orders do not block each other. |
| WF09 | `test_waste_disposal_integrity.py`; Waste disposal | Received → pending → approved → disposed. Repeat/stale decisions reject without writes. Invalid historical pending records can still be rejected safely. |
| PERF07 | `test_payroll_label_query_growth.py`; payroll QR list | Global counts, page filters, canonical aliases and original payloads remain correct. Ambiguous references still reject. |
| API01 | `test_task_assignment_authorization.py`; task PATCH | Creator without manager permission cannot change another assignee or unassign. Ordinary edits and assignee status-only updates still work. |
| API03 | `test_settings_patch_integrity.py`; Settings | Change phone only: address/logo survive. Invalid fields return 422 without writes. Parallel patches and logo uploads preserve both changes; missing-row creation produces one row. |

`n` = returned parents; `r` = returned child rows; `p` = permissions; `a` = audit rows. Query counts include authentication in these test fixtures.

| Path | Before → after | What remains |
| --- | --- | --- |
| Package list, 50 simple packages | 152 → 5 SELECTs; 1/10/50 = 5/5/5 | O(n) output work. Distinct-model fixture is 9/9/9; order fallback 7/7/7. SQL filtering/counting costs depend on data/plans. |
| Eco history, 50 dispatches | 54 → 5 SELECTs; 1/10/50 = 5/5/5 | O(n+r) grouping/output; O(n+r) memory. Global totals, count, sort and offset still cost database work. Empty page: 4 queries. |
| Attendance download | O(pages) device requests | O(events) processing/memory. Failure must not become a successful checkpoint. |
| Pricing authorization | No added DB queries | O(p) permission evaluation; profile text no longer grants access. |
| Audited account deletion | One additional history-existence lookup | Worst-case O(a) without an actor index. This is an integrity fix, not a speed claim. |
| Payroll label list | 1/10/50 global groups: 9/36/156 → 9/9/9 SELECTs | Alias page fixtures use 14; 401 references use 12. Queries grow by batches of 400, not per label. Global aggregation/output remain proportional to history/groups; not O(1) total work. |
| Return/disposal/settings guards | Bounded added lock/reference queries | Waiting depends on contention; existing audit/database work is not benchmarked. |
| Scoped grants / passport access | No new grant queries; bounded linked-order lookups | Permission-set work grows with permissions. Passport serialization still depends on materials; no speed claim. |
| Accessory return summary | No added queries | O(stock issues + manual issues) grouping; existing O(groups log groups) sorting. This fixes totals, not pagination or concurrent returns. |

**Bounded round trips are not O(1) total work.** Unmeasured APIs remain unknown. Local timings under laptop memory pressure are not a 200–2,000-user capacity claim.

## API coverage ledger

From `backend/`, run a selected test file with HTTP observation:

```text
python scripts/report_api_test_coverage.py run --output ../outputs/api-batch.json -- app/tests/test_flow_utilization_scope.py -q
python scripts/report_api_test_coverage.py merge --output ../outputs/api-merged.json ../outputs/api-batch.json ../outputs/another-batch.json
```

CI runs all `app/tests/test_*.py` files through this observer and uploads `backend-test-evidence`: route/status JSON plus JUnit failures. PostgreSQL concurrency remains a separate job. The inventory currently has **510 HTTP method/route pairs**, excluding docs/static mounts/WebSockets. Statuses separate success, rejection, errors and unobserved routes. A 2xx is not proof of correct stock or permissions; inspect the test assertions too. Direct service calls are not HTTP coverage.

The tool refuses an application `.env`, uses the existing temporary SQLite fixture, clears external-service settings and blocks non-loopback Python sockets. It is not a sandbox for arbitrary tests/native subprocesses. Reports contain route patterns, aggregate outcomes, Git revision and dirty-state flag—not request data or concrete record IDs. Only combine compatible inventories; a merged old run is not proof of the final implementation. Do not interpret instrumented timing as a benchmark.

## Release gates still required

### Latest reviewed fixes — local only

- **FN01:** `test_1c_sync_row_isolation.py` + FN03 → 25 passed including 8 PostgreSQL cases. Import good/bad/good rows: valid rows commit, failed row leaves no partial changes; caller rollback removes accepted rows too. Dialect assertions guard against accidentally testing SQLite as PostgreSQL. O(n) savepoints/writes; no speed claim.

- **FN03:** `test_1c_payment_reassignment.py` → 21 passed (6 PostgreSQL). Move payment A→B: A loses its credit, B gains it; amount edits, retries and rollback preserve totals. Concurrent moves/manual payments serialize. Run with the disposable-cluster command above. Added lock reads are bounded per batch; processing/status aggregation still grows with payment rows—no O(1) claim.
- **FN05:** `test_customer_payment_cents.py` → submit 0.01 advance or 1.01 against a 1.00 invoice; residual credit is retained. Sub-cent, negative and nonfinite amounts reject before writes. Existing invoice settlement tolerance is unchanged.
- **SEC11:** `test_quality_check_factory_scope.py` + `test_production_flow.py` → 93 passed. POST `/api/quality/checks`: six wrong-factory pairs return 403 with no quality/audit inserts; own/explicitly selected factory works, missing work order returns 404. One added department lookup; no throughput claim or visual UI proof.
- **OPS02 partial:** `test_db_pool_configuration.py` → 9 passed without a PostgreSQL connection. Explicit 8/4 and zero-overflow honored; unset values retain 5/10; SQLite unaffected. Maximum configured connections must still be budgeted across every process/slot/client.
- **PERF05:** issuance/list/payroll suites → 64 passed. POST `/api/payroll/qr-labels/issue`: repeated new UID returns issued=2/created=1/existing=1 and one audited creation. Existing ambiguous retries succeed; new ambiguous references reject; wrong-factory references reject without insert; canonical aliases preserve UID/money/manual text. Reference-only SELECTs **8/44/204 → 7/7/7** at 1/10/50; no-reference 4/4/4, retries 3/3/3; 401-reference chunk test passes. Lookup round trips grow by 400-value chunks; writes/output O(n), reference preparation includes sorting. Not O(1) total work or peak-load proof.
- **API02 partial:** `test_task_input_validation.py` + `test_task_assignment_authorization.py` → 56 passed. POST/PATCH `/api/tasks`: invalid states, dates, blank/oversized title/type, int4 overflow and explicit required-field nulls return 422; omitted/nullable fields and legacy orphan edits remain compatible. Target existence/access remains open. Validation adds no database queries; string checks are linear in input length.
- **Scoped API observation:** quality/task/payment regression batch → 83 passed, 6 PostgreSQL-only skipped; 114 requests across 7 routes, no failed tests. This is a dirty-worktree batch, not updated full-suite coverage. Separate PostgreSQL results above remain required.

### Final acceptance

- Run the full suite and all opt-in PostgreSQL cases on the final commit; preserve failures and skips.
- Check success, validation, role/factory denial, missing records and database side effects per changed API. For mutations also check retries, rollback and concurrent writers.
- Use the API ledger to find unexercised operations; a 2xx hit alone is not correctness coverage.
- Test realistic data volumes and an agreed concurrent-user workload on isolated staging. Record p50/p95/p99, errors, SQL counts, CPU/RAM and pool waits.
- Owner-approved policies, device firmware checks, historical-data repair and backup restoration require separate evidence. No production-readiness sign-off until these gates pass.
