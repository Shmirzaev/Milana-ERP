# Factory workflows release — 13 November 2026

Deployed **green `20261113_094409`** on both hosts, exact runtime source
`e5383f2509ceef4eb20f73f34dc0beba64fcea19`. Healthy rollback is blue
`20261111_115200` / `46ddd5c7864f0a68bd9a3c884d835a2a5dbf9bfb`.
Backend activated 10:57:27.943321 UTC and frontend 10:57:31.728765 UTC
(15:57 Tashkent). Both `current` symlinks, manifests, runtime slots and served
release identities agree. Final public performance and closing checks passed.
Timed observation was explicitly waived; no observer or substitute monitor ran.

## Delivered behavior

1. New Nastil references use the public Order No and a unique Nastil suffix.
   Historical batch names and exact batch QR identities remain stable; ambiguous
   unscoped historical serials are rejected instead of selecting another batch.
2. Passed Sewing output appears in Packaging automatically. The receive navigation
   is removed, while historical receipt APIs remain. Operators choose Nastils and
   a bounded pack count (default one); full, partial and merged source quantities
   respect real saved Packaging evidence. Queue visibility does not mint stock.
3. Cutting passport Open resolves the authorized CUT/ECT work-order Cutting page.
4. Cutting boards reconcile true bundle origin, first physical downstream receipt,
   current inventory and real orders/work orders. Passport dashboards aggregate
   every saved fabric row, correct pieces/Tepa treatment, dates and separate units.
5. Invoice XLSX table/signature font is 10pt. Package rows share the maximum height
   required by wrapping, preserving numeric facts, merges, pictures and totals.
6. Restricted Milana Planning can select genuine Eco Cotton fabric and route the
   resulting production order to ECT using the scoped lookup.
7. Direct/transferred ECO receipt identity is carried through selection, QC,
   reservation and passport debit/reopen. A required central bridge has zero
   quantity and is created only on authorized writes; physical stock stays ECO
   owned. No GET backfill, migration, inventory fabrication or central double debit.

Operation ledger, isolated persisted browser checks and human checklist:
[task packet](../FACTORY_WORKFLOWS_20261113.md). Repository domain assignments
remain Mirshoir/Ismail; these are not claims of human participation. Codex agents
`/root/packaging`, `/root/cutting_reports` and `/root/eco_fabric` supplied separate
implementation, artifact, SQL-oracle and independent review evidence. Human
domain/operator/QA-master acceptance remains unrecorded.

## Exact source and artifacts

Worktree: `C:/ERP/.codex-work/factory-workflows-20261113`.
Branch: `codex/factory-workflows-20261113`, pushed; no clone_main/main merge.
Fresh clone_main fetch immediately before activation remained
`3053788f2e17bd5585bccf8cd4547a62cc297516`. The candidate includes reconciled
deployed source46ddd; all 2,495 original deployed files had matched Git blobs.
Legacy `C:/ERP` work was preserved. Only reviewed clean Git source was released;
the later production-base/context commit changes metadata, not runtime images.

All **2,528** source files in the immutable release archive match canonical Git
blobs, manifest, modes and deterministic archive metadata. Archive size6,537,268;
SHA256 `47ac482ef34b3a4f383edc9dd376ee2b058e53d9227ef9f8e353e922f1bd290f`.
Source manifest SHA256:
`4696c9736e3561610dbf92a98888cd2cb2cc7eca1911d668e51b7a8d2496a821`.

| Role | Published and scanned immutable image digest |
| --- | --- |
| Backend | `ghcr.io/shmirzaev/milana-erp-backend@sha256:47f28dc3a4ef25c7ede2ecc12d0d01d3d169aded882b341a09e9a63f7aad936b` |
| Frontend | `ghcr.io/shmirzaev/milana-erp-frontend@sha256:1205058f5d45fc14b55a3faa15eef09712b51029094f9b50dee75945c71fc154` |

Both installed controller hashes remained
`13a9e19d5b266c87d138cb2866a185fedf45a089b85534d26fb28667eb95c3f3`.
The candidate controller has unrelated routing changes, so the runbook's narrowly
reviewed staging adapter was used: real installed `stage()`, exact Docker arguments,
only `RELEASE_ID` added. Adapter hash
`ea22df43b2dea7f6ddad2baabae901e9e1fe22382218afcb2add1ac0930fbe4f`.
Shared environment and default image commands were unchanged. Both deployment
locks were owned; phase programs compared complete source/runtime/config state
before each mutation. Backend activation/health preceded frontend activation and
independently reviewed atomic source links. No production build/dependency install.

## Verification

- Exact-source [CI43403793296](https://github.com/Shmirzaev/Milana-ERP/actions/runs/43403793296)
  passed: backend6,808 cases,1,596 reported optional skips,36 subtests; P2 207,
  Forecast20 and Ismail185 passes/17 baseline skips. Frontend lint0 errors/14
  existing warnings, scoped strict check, optimized build and17 applicable browser
  scripts passed. Node117 pass,5 known QUARANTINE_FAIL,34 NEEDS_APP and1
  QUARANTINE_PASS remain disclosed; quarantine/NEEDS_APP are not claimed as passes.
  Security scans passed and the same scanned images were published.
- Exact-source [PG43403798457](https://github.com/Shmirzaev/Milana-ERP/actions/runs/43403798457)
  passed5 numbering,649 mandatory,17 supplemental and84 shared contract cases,
  with no required skips. Local final affected145, workflow/PG113, stock races2,
  real HAProxy4 and JWT171 checks also passed on their recorded source snapshots.
- `npm run typecheck:strict` uses a scoped `tsconfig.strict.json` with stricttrue.
  The separate optional whole-app strict audit retains16 unchanged baseline
  diagnostics. This release does not claim global strict adoption or global
  schema-owned-write/refactor acceptance.
- Staged and actual public connected Edge exercised automatic Packaging arrival,
  selected Nastil/pack counts, partial/merged caps, CUT/ECT Open, November cutting
  totals, real ECO fabric picker and restricted Planning. Five real ECO choices
  showed900/200/436/552.4/151.8kg. PO0714 showed612 sewn/552 packed/60 available,
  default Copies1 and saved source label balances12/0. No form was saved, label
  generated or production fixture created. Planning had zero eligible confirmed
  orders; full create→ECT passport→physical9kg debit/reopen/central-zero effects
  were verified in isolated same-source infrastructure, not claimed as live writes.
- Full read-only SQL facts and independent oracles passed26 checks: all complete
  protected responses, both Cutting departments/boards/passports, all three
  Packaging queues, complete material metadata and balances, Planning denial403,
  invoice facts and XLSX values/merges/fonts/heights. Shipment44 has100 packages
  grouped into57 invoice rows; all57 rows were checked.
- Public browser console errors were zero in all three contexts. One private MIL
  viewing-proxy SSL EOF event is preserved separately; pages loaded and all final
  public functional/timing calls passed. Earlier staged external-extension errors
  remain in raw evidence. No ERP console error is concealed as a pass.

## Performance decision and live data activity

The original single810-GET paired epoch is immutable and **remains FAIL**:
only Sales Order7 median17.070448→18.953587ms (+11.0316%, cap10%) and
p9519.853693→25.093177ms (+26.3905%, cap15%). All810 responses were200 with correct
complete facts; other nine paths and byte limits passed. Cause is unproven; the
Sales implementation/configuration was unchanged. No retiming or source rebuild.

After disclosure, the owner answered **"Deploy with this specific exception"** to
the question explicitly naming both failures. Root decision SHA256
`d41de2d885c74ff058e4c560d65e845abc20db57cecc94744357ff06a8a269f0` binds exacte538,
release094409 and failed paired artifact
`6d2376746274032eee37786c43634066a0da2484fcc258b63f5874f5aac407f4`.
While approval was pending, the original inactive green052632 was safely restored;
after approval the identical scanned images were restaged under fresh CAS checks.
Active blue115200 did not change until the authorized cutover.

Factory staff continued working. Earlier complete snapshots failed because of
operator3 cutting190/50kg, operator4 Sewing600 pieces, later44.8kg consumption
(Stock720223.6→178.8, movement4555/CR1328 at10:36:47 UTC), subsequent Cutting/Sewing
records and six physical Sewing receipts. Full current old-active/candidate
responses, ledger rows and audit timestamps independently proved natural activity.
The six receipts are scans38002–38007/user4/audits250294–250299 at10:53:38 UTC,
bundles22495–22500,74pieces each: exactly6bundles/444pieces leaving ECT inventory.
The failed first public data report is preserved; this was not waived or silently
patched. No QA actor1/18 business writes were introduced.

Separate, complete current-facts cohorts retained every original fixture/path/field,
all SQL/metadata/reservations/references and independent26-check oracle. The final
public cohort used one54-GET/four-worker collection immediately after full SQL
snapshot11:03:19–11:03:21 UTC; its HTTPSpublic half was used directly, without a
second capture. Reviewer reproduced all26 results and verified all17 cohort files.
New root facts approval changed only complete expected bodies; original paired
failure, owner exception, V4 lock and original PUBLIC timing baseline stayed fixed.
Minimal helper and nine offline guard tests passed independent review.

**One final strict public epoch passed all270 GETs** (60 warmups+210 timed,
21 samples/path,10 paths). Every complete ordered body matched the approved public
facts; before/after runtime identity was stable. The original same-public-network
baseline and median10%/p9515%/bytes15% caps were retained for every path, including
Sales. Largest increases: median+1.404%,p95+12.046%,bytes+1.475%, all within budget.
Public Sales median117.555258→116.882198ms; p95130.943401→119.974558ms.
This public pass does not relabel the accepted failed paired gate.

| Closing evidence | SHA256 |
| --- | --- |
| Final complete public cohort | `2a6dab67c08d068410962be389e3e88aa72af112cd29cad7fca879294900e7c5` |
| Actual public capture | `d63741f691743fd081d67c2b80946cbdb8c7069395dc2dc5779a49aa0dc475fd` |
| Full26-check public semantic result | `89ad484ba876564417d73c949e44c6c7625e841ed8d3a1531bd587007780fffe` |
| Root final facts approval | `55d15392b2577b715b5eea33713ae1b0c14306e0d40d26185afc9a24ac1f2d74` |
| Final benchmark helper | `dde1b022d849dce8d8a6b2dbeb7f15fc69199e04410457068423afbd0aaa20ca` |
| Strict public timing result | `0f77241823efbfea8305700d1fe860f46203e88457f6aab5f8ba303be1ca6d7b` |

## Backup, closing state and limits

Fresh promotion backup:
`/opt/milana-erp/shared/backups/milana_erp_pre_factory_20261113_094409_20261113_104518.dump`.
Mode0600;123,607,735bytes;1,400 `pg_restore --list` objects; dump SHA256
`3d040802df4913895175ec8ea9ad3c35d0572f10ba734c071d88f0f992e684ba`.
Restore-list101,509bytes, SHA256
`31437c3de24e28e5750825c6a653963bfb1ff6d9aa7c22588df28500ceef38bb`.
The earlier pre-migration backup was also verified. Head before/after no-op upgrade
and both retained applications remains `0156_variant_price_workflow`.

After the public epoch, fresh closing checks passed all four supported health/login
endpoints, stable/slot readiness, frontend health forwarding, both source manifests
and scanned image identities, exact default commands, active/rollback routing,
HAProxy validity, two strict-schema workers per backend, disabled seeding,
zero restarts/OOM/log errors, database40–41/100 connections and zero invalid indexes.
Backend/frontend disk78.53%/78.08% remains above the70% alert but below80% stop.
Only supported reviewed retention of an older source release was used before
staging, with active and rollback releases protected; no blanket cleanup.

Production mutations were release/slot/proxy/symlink metadata, inactive container
replacement, verified backups and a no-op migration. This task created no business
orders, models, stock, packages, labels, shipments, payroll or user records. Operator
activity is documented rather than falsely claiming the whole live database stayed
unchanged. Independent closing review found no remaining gate issue. Deployment
locks were released after closing; no timed observation was claimed. Historical
authorization/audit/refactor risks in current project context remain outside scope.

Private evidence is under the task worktree's `outputs/factory-deploy/`, independent
CI worktree `factory-ci-triage-20261113/outputs/factory-ci/`, and read-only QA worktree
`factory-release-readonly-20261113/outputs/factory-release-readonly/`. Failed captures,
original timings, decisions, proof packets and screenshots remain preserved.
