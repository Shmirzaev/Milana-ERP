# BST current-master handoff, 4 November 2026

Status: implementation prepared; production identity confirmation and execution
remain held. No migration, production mutation, account grant or deployment has
been performed by this operation.

Engineering owners: People Dilmurod, reviewer Mirshoir; Production Mirshoir,
reviewer Ismail. Codex `bst_handoff` implements this bounded maintenance action;
root integrates and arranges independent review/QA. No human acceptance is claimed.
Scope is preserved in the coordinator's `PLANNING_FLOORS_BST_20261104.md` packet.

## Read-only production findings

Inspected current source symlink `/opt/milana-erp/releases/20261104_080711` and
`milana-backend-blue` using explicit `SET TRANSACTION READ ONLY`. Queries were
SELECT only, then rollback. Live `alembic_version` readback is exactly
`0154_eco_receipt_details`. All 83 currently connected workers have null `user_id`.
No environment, credentials or private profile fields
are recorded here.

| Current master | Current direct workers | Physical sewing flow | Proposed replacement |
| --- | ---: | --- | --- |
| Employee 882, Oydinoy Mamadaliyeva | 42, all active | 96 / BST-BAND-01 / Oydinoy Mamadaliyeva | Owner requested Yoldashova Dilfuza; no exact stored name found. Closest record 620, Yo'ldasheva Dilfuzaxon, is currently a Band 4 worker under 885. Identity confirmation is REQUIRED. |
| Employee 885, Maxsimova Shaxnoza | 41, all active, including 620 | 99 / BST-BAND-04 / Shaxnoza Maxsimova | Employee 515, Axunova Xayotxon, unique exact name, currently Band 2 worker under 883. |

Neither proposed replacement currently has direct workers. All four employee
`user_id` links and both `sewing_flows.supervisor_id` links are null. The flow
supervisor is a **users** FK, not an employee FK: never place an employee ID there.
No user account has `sewing_band_id` 96/99. No HR organization unit references the
four leaders. Thus the prepared operation changes no accounts or permissions.

If 620 is confirmed, both incoming masters become root leaders; promote 620
before counting the transfer from 885. Expected resulting direct workers are
620 → 42 and 515 → 40. The incoming leaders cannot report to one another. Do not
copy 620 into 515's worker set and create a cyclic master relationship.

The reviewed current worker IDs are:

- 882: 477, 478, 479, 480, 481, 482, 483, 484, 486, 487, 488, 489, 490, 491,
  492, 493, 494, 495, 496, 497, 498, 499, 500, 501, 502, 503, 504, 505, 506,
  507, 508, 509, 510, 511, 512, 513, 1547, 1548, 1552, 1574, 1583, 1584.
- 885: 589, 590, 591, 592, 593, 594, 595, 596, 597, 598, 599, 600, 601, 602,
  603, 604, 605, 606, 607, 608, 609, 610, 611, 612, 613, 614, 615, 616, 617,
  618, 619, 620, 621, 622, 623, 624, 625, 1553, 1555, 1556, 1586.

## Exact allowed changes and preserved evidence

The operator supplies and reviews a frozen before-state plan. The service changes
only current `employees.manager_employee_id`, the incoming masters' current band
position/section/workplace labels, exact old-master labels in connected workers'
`position` and profile `workplace`, and `sewing_flows.name` for the two existing
flows. Old leaders' identities and profile/position records remain intact. Free
or inconsistent worker role labels are retained; no broad text replacement runs.
Unrelated profile fields remain server-side: exported plans and audit contain
only section/workplace and a hash of all remaining profile content for CAS.

Employee IDs, legal names, numbers, statuses, pay values, accounts, attendance,
documents and every historical evidence row remain unchanged. Existing physical
flow IDs/codes, supervisor, description, capacity and activation stay unchanged.
No employee merge, rename, deletion, archive, payroll transfer or output rewrite
is part of this operation. One audit receipt records before/after and backup
reference using the existing hash-chain service in the same outer transaction.

Live evidence to preserve:

| Evidence | Flow 96 | Flow 99 |
| --- | ---: | ---: |
| Work orders | 4 | 0 |
| Sewing assignments | 6 | 0 |
| Daily reports | 2 | 3 |
| Payroll QR labels | 11,679 | 14,344 |

Both incoming masters have existing payroll records. All retain their original
employee linkage and amounts; individual pay totals are excluded from this source
packet. Historical
QR `sewing_line_name` and daily-report `line_name` snapshots remain unchanged.

**Report limitation:** existing salary reports use current employee manager links
for every selected period (`payroll.py` manager filter and salary projection).
The existing behavior therefore regroups previous periods under new masters after
this handoff. Original payroll rows/amounts and saved QR/daily-report line labels
remain intact. Preserving prior-period master grouping would need separately
approved report/history behavior; this script does not silently invent it.

## Execution contract and recovery

Files: business coordinator `models/people/bst_master_handoff_service.py`, narrow
People/Production schema persistence companions and operator runner
`backend/scripts/bst_master_handoff.py`. There is no HTTP endpoint or migration.
The operator is the transaction owner; helpers never commit or roll back.

1. Confirm the exact replacement identities with the owner. Create an explicit
   two-item specification of old_master_id/new_master_id/flow_id/new_display_name.
   No production specification or executable plan is checked in while 620 is
   unconfirmed. The test specification is synthetic and is not execution approval.
2. From the exact reviewed runtime source, `capture` uses a PostgreSQL repeatable
   read, read-only transaction and outputs an envelope with `plan`, digest and
   proposed after-state. Save its `plan` object to a separate JSON review artifact.
   `check` reads that plan and verifies all frozen before-values and membership,
   then prints the pure proposed after-state without writes.
3. Complete independent source review, actual isolated UI/readback and human QA.
   Coordinate with the root's separate migration/release approval. Verify a fresh
   production backup; supply its reference. Backup existence/restore validity is
   an operator gate, not something a string argument can prove.
4. Only with execution authorization, `apply <plan.json> --reviewed-sha256 <hash>
   --backup-reference <verified-reference>` begins one caller-owned transaction.
   It refuses dirty Sessions/non-PostgreSQL engines; takes table locks in fixed
   order (employees, sewing_flows), then sorted row locks; revalidates the complete
   before-state and membership, applies the exact reviewed patch, flushes, refreshes
   every affected row and compares actual state with the preview; adds audit then
   commits once. Locks prevent concurrent roster phantoms. Lock timeout is 5s;
   per-statement timeout 15s. All other operations should remain brief.
5. The same plan can be retried after a lost response: an existing matching receipt
   permits a no-write success only when current roster/flows still match its saved
   after-state. Any later roster/profile/flow drift is a refusal requiring review.
   Changed specifications/before-state need a new reviewed digest, never a forced
   retry. Unexpected commit errors report **outcome unknown**, not assumed rollback.
6. Independently read back exact counts, two root leaders, unchanged old IDs,
   accounts and all protected history; inspect current employee/flow pages and
   report-group labels. If a correction is needed, stop and review a narrow inverse
   using the receipt's exact before/after CAS and current data. An application
   rollback alone cannot undo a committed roster transfer. Do not restore an old
   whole database over later business activity.

Operational field/type ledger: factory and flow/employee names are configurable
records/labels. Employee `status` is captured unchanged and only the existing
`active` leader precondition is used; broader HR canonical status-enum adoption
remains outside this maintenance operation. No new stored vocabulary is introduced.

## Evidence on this candidate

Disposable Docker PostgreSQL: `milana-bst-handoff-test-20261104`, PostgreSQL 16
Alpine, loopback `127.0.0.1:25464`, database `bst_handoff_test`. No other database,
container or production credential is used. Each run creates/drops its own
`bst_handoff_<uuid>` schema via metadata; **no Alembic migration is applied**.

`BST_HANDOFF_TEST_URL=postgresql+psycopg2://postgres@127.0.0.1:25464/bst_handoff_test`
and `PYTHONPATH=backend`, run:
`C:/ERP/.venv/Scripts/python.exe -m pytest -q backend/tests/test_bst_master_handoff_postgres.py`.

Latest full run: **27 passed in 19.96s**, zero skips; strengthened concurrent
insert-attempt instrumentation then passed its targeted check in 2.42s. Includes exact 42/40 synthetic
handoff, identity/pay/entire other-table byte-value preservation (nonempty payroll,
QR labels and daily reports), root-leader cycle avoidance, actual account/supervisor
guards, nine stale-state cases, invalid specifications, read-only dry run,
private-profile redaction/preservation, injected audit rollback, current-state
receipt drift refusal, dirty-session refusal, exact-label-only changes, two concurrent
retries (one write), blocked concurrent roster insertion and 5s lock-timeout recovery.
Earlier candidate runs: 14 passed / 8.67s, 22 passed / 19.12s and 27 passed / 20.62s, superseded by the
expanded suite. Compileall and `git diff --check` passed. Test-owned UUID schema
cleanup completed; final namespace query returned zero owned schemas and the
owned container was removed after verification. No other container was changed.

Independent root review requested profile minimization and receipt drift checks;
both are implemented and have PostgreSQL regressions. Full independent review,
actual connected-browser verification and human QA remain pending. Do not mark
AI_VERIFIED_AWAITING_HUMAN or claim production completion from these tests alone.
