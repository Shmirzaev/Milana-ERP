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
| WF03 | `test_package_evidence_integrity.py`; single/bulk package APIs | Missing/zero output returns409, 7 available cannot create two5-piece packages, and failure leaves no package/item/stock. Output10 permits two5-piece packages. Uses existing aggregate query; no speed claim. |
| UI04 | `frontend/scripts/test-dashboard-live-data.mjs`; management dashboard | With management permission, request live overview; finance requires its own permission. Synthetic live values appear; loading/error never falls back to demo figures.15 actual React render cases; manual browser check remains. |
| UI05 | `frontend/scripts/test-home-stage-kpi.mjs`; Home | Four stages of100 display400 as stage activity, with an explicit unique-output warning in EN/RU/UZ. Actual React render; browser layout still needs verification. No query/arithmetic change. |
| AT06 (partial) | `test_attendance_import_races.py`; roster/events imports | Run on disposable PostgreSQL: duplicate device/person/event imports serialize; newer overlapping roster wins; older response says ignored. Five cases pass. O(n) payload/writes, per-device contention; late-uploaded old source snapshots remain unresolved. |
| PERF28 (partial) | `test_purchasing_query_growth.py`; receipt service | Catalog/reference SELECTs stay4 at1/10/50 lines. Reference-only401 values use2 chunks; aliases/ambiguity match scalar behavior. Lookup reads O(ceil(n/400)); preparation includes O(n log n) sorting. Writes/audit-head reads still grow per line. |
| WF04 (partial) | `test_packaging_quantity_validation.py`; packaging records | Negative, int4 overflow or output above input returns422 and preserves real work-order counters/records. Partial/zero reports still validate. Constant-time numeric validation; other stages are not covered. |
| WF05 | `test_package_model_integrity.py`; single/bulk package APIs | Wrong header/item model rejects with 400 and creates no stock graph, even with admin override. Matching package still succeeds. Adds no queries; existing item validation remains O(n). |
| WF06 | `test_packaging_stale_counters.py`; packaging receive/record APIs | Cached counters refresh before increment. Disposable PostgreSQL forces both receipt writers to wait: 5+3+4 ends at12 with two receipts. Adds one target lock/read; no full-path complexity claim. |
| AT01 | `test_attendance_event_results.py`; attendance overview, XLSX and HR | Failed/unknown scans remain raw but do not create attendance/hours. Success and legacy NULL results count. Check used/not-used filters and exports. Adds a SQL predicate, not per-row queries. |
| PERF42 | `test_sewing_line_context_query_growth.py`; line context | 1/12 assignments:2/2 capacity queries, previously5/60. Same order/batch/assignment limits, top/bottom values and legacy fallback. Python aggregation is O(grouped history + displayed rows), not O(1) total work. |
| AT04 | `test_attendance_historical_profiles.py`; Attendance overview/daily XLSX | Import a profile and two scans, remove profile through a full snapshot, then reopen that date: hours still appear once in overview/export. Other dates and factories remain excluded. Query round trips remain bounded; database aggregation still grows with matching history. |
| AT05 | `test_hr_attendance_validation.py`; HR attendance/settings | UTC events on either side of Tashkent midnight appear on the correct day. Invalid legacy hours fall back safely; nonfinite input returns 422. Factory settings read once. |
| PERF34 | `test_shipment_document_query_growth.py`; shipment documents | 1/20 manual packages use 4 SELECTs. Exact/wildcard/ambiguous prices, line order, basis hash and frozen document remain unchanged. Inputs indexed once: O(P+I+L+output) processing, not constant total work. |
| ST09 (partial) | `test_finished_goods_damage_integrity.py`, `test_finished_goods_reserve_integrity.py` | Mark synthetic package damaged, then reserve: 409 and no balance change. Re-run 3 PostgreSQL reserve races. Reverse damage-after-reserve is still unresolved. |
| ST10 | `test_purchase_conversion_integrity.py`, `test_purchasing.py`; request conversion API | Two simultaneous conversions create one order; losing request returns 409. Conversion racing rejection preserves one valid final state. Rollback allows later conversion; cached old approval does not bypass state checks. |
| ST07 | `test_finished_goods_reserve_integrity.py`; finished-goods reserve API | Two reserves of 6 against 10: one succeeds, one rejects; stock stays 4 available/6 reserved. Reserve racing release preserves the other order; reserve racing dispatch never restores sold stock. |
| API04 | `test_hr_workspace_validation.py`; HR organization/positions/recruitment/calendar/uploads | Wrong-factory links reject; salary/date inversions, nonfinite/oversized input and blank titles reject without writes. Valid scoped workflow and explicit optional clearing still work. |
| PERF31 | `test_attendance_people_query_growth.py`, `test_attendance.py`; integration people API | Create/update 1/10/50 people with 3 SELECTs; 401 with 4. Duplicate snapshot rolls back; partial snapshot keeps absent people; full snapshot affects only its device. |
| WF08 (partial) | `test_waste_sale_integrity.py`; waste sale API | Sell 4 then 6 of 10: stays received then sold. Overage rejects. Same user/record/key replays one sale; changed payload conflicts. Concurrent oversales reject, and disposal cannot consume sold portions. Current UI does not send retained keys. |
| ST08 | `test_finished_goods_release_integrity.py`; finished-goods release API | Shipped/consumed/nonpositive reservations return 409 without changing stock. Intact sibling reservations release correctly. Two simultaneous releases restore once; release racing dispatch never restores sold goods. Run the two `postgres` cases on disposable PostgreSQL. |
| PERF11 | `test_print_run_query_growth.py`, `test_package_workflows.py`; GET `/api/packages/print-runs` | 1/10/50 runs use 3 SELECTs. Manifest corruption rejects; deleted members stay hidden; factory filtering, original payload and 100-run cap remain intact. |
| SEC06 | `test_admin_membership_delete_race.py`, `test_user_audit_history.py`; isolated PostgreSQL | Concurrent deletes of the last two wildcard admins: one succeeds, one rejects, one admin remains. Concurrent audit insertion must still complete and preserve history. |
| WF10 | `test_waste_readonly.py`; GET `/api/waste` | Change a synthetic batch cost, then read waste. Live response estimate changes; persisted historical value and finance totals do not. GET never commits. |
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

SEC06 locks/scans active users: O(u) membership work, intentionally serialized; not O(1). WF10 removes writes, not read-query growth: per-row cost lookups and unbounded listing remain. Live waste estimates versus stored accounting snapshots (including automatically created zero values) still need an agreed FN08 valuation policy.

PERF11: 1/10/50 runs fell from 3/12/52 to 3/3/3 SELECTs (100 returned runs: 102 → 3). Bounded database round trips for the existing 100-run page; O(n+r) Python work/memory for runs and members. Individual member counts and total database work are not constant.

ST08 uses a bounded number of reads but locks/scans all r reservations for the selected stock: O(r) Python work/memory. Inconsistent historical balances reject rather than auto-repair. ST07 locks the same package/stock before reserving, adding a bounded number of reads; it does not establish constant total SQL/audit cost.

PERF31 lookup round trips are O(ceil(n/400)); payload, processing and writes remain O(n). WF08 scans s prior sales for one record: O(s) work/memory, a fixed number of lookup queries, not constant total database work. API04 adds at most a few reference lookups per command; no per-list optimization claim.

ST10 replaces an unlocked parent read with one locked/refreshed read. Conversion still processes n request lines and retains per-line reads/writes: O(n); no N+1 optimization claim.

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
