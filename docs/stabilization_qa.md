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
| SEC10 | `test_privileged_user_delete.py`; Users → Delete | Limited administrators cannot delete a privileged administrator, including policy-based privilege variants. |
| UI01 | `test-session-recovery.mjs`; authenticated page | Temporary 503/network failure shows recovery without discarding the session. Bounded retry succeeds; genuine 401 redirects to login. |
| UI02 | `test-api-deadline.mjs`; API client | Hanging JSON/form/error response bodies time out; cancellation works; ordinary responses remain unchanged. |
| PY01 | `test-payroll-scan-order.mjs`; Payroll → Scan | Queue badge A, work A, manual A, badge B, work B. Recorded ownership follows the event sequence, not the latest UI selection. |
| PERF01 | `test_package_query_growth.py`; package list | Same rows/filters/order; no per-package query growth. See complexity table below. |
| AT02 | `connectors/hikvision_attendance/test_event_checkpoint.py` | Mock device advertises 3 events but returns 2 then an empty page. No upload/checkpoint advance. Complete retry imports all 3. HTTP/upload retries keep event identities. |
| SEC02 | `test_user_audit_history.py`; Users → Delete/Edit | Delete an account with authored history: 409 and no cleanup. Edit → deactivate works; old session rejects. A concurrent audit insert also preserves actor/hash and rolls back cleanup. |
| API06 | `test_name_authorization.py`, `test-name-authorization.mjs`; profile/pricing | Rename restricted user to `Abbosbek` or matching email. Same session still gets 403 from pricing GET/PATCH; navigation remains hidden. Explicitly granted users retain access. |
| PERF41 | `test_eco_history_query_growth.py`, `test_eco_transfers.py`; Eco transfer history | Pagination/date/order/roll rows/global totals unchanged. Empty page works; historical snapshot is not rewritten. |

For UI QA, start a separate loopback-only frontend/backend with fresh synthetic accounts and database. Block external browser requests and backend connections. Test both a restricted and explicitly permitted account. Inspect the rendered error/success state and browser errors; screenshots must contain synthetic data only. Attendance connector and backend-only concurrency cases use protocol/transaction tests instead of screenshots.

## Measured complexity

`n` = returned parents; `r` = returned child rows; `p` = permissions; `a` = audit rows. Query counts include authentication in these test fixtures.

| Path | Before → after | What remains |
| --- | --- | --- |
| Package list, 50 simple packages | 152 → 5 SELECTs; 1/10/50 = 5/5/5 | O(n) output work. Distinct-model fixture is 9/9/9; order fallback 7/7/7. SQL filtering/counting costs depend on data/plans. |
| Eco history, 50 dispatches | 54 → 5 SELECTs; 1/10/50 = 5/5/5 | O(n+r) grouping/output; O(n+r) memory. Global totals, count, sort and offset still cost database work. Empty page: 4 queries. |
| Attendance download | O(pages) device requests | O(events) processing/memory. Failure must not become a successful checkpoint. |
| Pricing authorization | No added DB queries | O(p) permission evaluation; profile text no longer grants access. |
| Audited account deletion | One additional history-existence lookup | Worst-case O(a) without an actor index. This is an integrity fix, not a speed claim. |

**Bounded round trips are not O(1) total work.** Unmeasured APIs remain unknown. Local timings under laptop memory pressure are not a 200–2,000-user capacity claim.

## Release gates still required

- Run the full suite and all opt-in PostgreSQL cases on the final commit; preserve failures and skips.
- Check success, validation, role/factory denial, missing records and database side effects per changed API. For mutations also check retries, rollback and concurrent writers.
- Use the API ledger to find unexercised operations; a 2xx hit alone is not correctness coverage.
- Test realistic data volumes and an agreed concurrent-user workload on isolated staging. Record p50/p95/p99, errors, SQL counts, CPU/RAM and pool waits.
- Owner-approved policies, device firmware checks, historical-data repair and backup restoration require separate evidence. No production-readiness sign-off until these gates pass.
