# CEO dashboard production release â€” 19 November 2026

Status: CEO candidate rejected by closing performance gate; compatibility application restored and healthy.

## Authorization and source reconciliation

The owner requested Ismoiljon's latest ERP change, approved the rollout, then
explicitly said **"Ignore and deploy"** after the disk threshold and failed-worker
blockers were reported. The exact reviewed application candidate is the latest
`clone_main` application/integration head, not the stale `main` production pointer.
No application source was changed or merged for this deployment.

Both initial production sources named `20261116_130518`; their complete manifests
verified with SHA-256 `bc2e0d4bdbb38f6c06b9f3d5c75f3fdaa1fb5087240ca8f7b49d01318908ce40`.
All initial baseline fields matched the candidate's recorded production baseline.
Fresh Git checks found `clone_main` unchanged at the release SHA before cutover.

Backend disk was 88% and frontend 80% in `df`; the owner override was recorded.
No blanket Docker prune, volume deletion, backup deletion or unrelated cleanup ran.
The old fixed worker had failed while preparing unrelated shipment candidate
`20261118_072350_44258533491_1`, before activation or a reservation on either host.
Its installed guarded recovery returned idle without changing live routing; the
worker service was stopped and disabled to prevent a reboot restarting stale
automation. The manual rollout owned the protected reservation on
both hosts. After verified recovery, both matching reservations were released.
The disabled worker has no main process; systemd retains its previous failed
marker (exit status 2), which was preserved in the journal. Failed worker
journals were preserved.

## Immutable identities

| Item | Identity |
| --- | --- |
| Held rejected candidate / slot | `20261119_025033` / green, both VMs |
| Application Git commit | `34727287848116f718a9f455a0484eafb32ed232` |
| Validation/publication run | [44447218793](https://github.com/Shmirzaev/Milana-ERP/actions/runs/44447218793) |
| Source files / archive bytes | 2,624 / 6,772,061 |
| Archive SHA-256 | `6c52ab860a624dde53c83a688febd772a44c03c08205c1b6a809f8b4cf40553f` |
| Source manifest SHA-256 | `da727d295486e47b158e8e4fdb419dd152bc34fe3770f7d06a848e14d89b0ee5` |
| Backend image digest | `sha256:b88f6b5698ee7fadaeddb35488defe2d846d937a04de1381c7aeb76e7c6a2b98` |
| Frontend image digest | `sha256:abe062c8e55aee116cf7149c98834d31169f66b4dd0079a7dbc5a11939ca5798` |
| Current recovered application / slot | `20261119_030500` / blue, both VMs |
| Compatibility commit | `437523dbd2d558a76f1308d8aa2215aee64b86bb` |
| Compatibility build/recovery QA | [44448608202](https://github.com/Shmirzaev/Milana-ERP/actions/runs/44448608202) |
| Compatibility manifest | `b09fc748df6e4da0d00dbabbdd6a38a6b8ce2c38a8c2815cd960eb9e63902fbd` |
| Compatibility archive SHA-256 | `e99b2f22e175e6b19e48e616e86972c0c36148824208ac6ad63e2a9c4c214b79` |
| Compatibility backend digest | `sha256:68fd39736f517de5178734c100386b95efb423edf0a1847bdc19395e9bd6ce0e` |
| Compatibility frontend | Exact original live image `sha256:7fce0d58189fd31e3e2c383c78a9bef8d4c128d544c539ba318009719de1646c` |

Both release archives were verified and extracted identically on both VMs. OCI
source revisions and actual container images were checked. No image was built on
a production VM. The original running backend requires exactly schema0157;
after schema0159 it cannot safely restart. Therefore the two-phase plan first
activated the previous application with the two identical candidate migration
files, then staged/activated the application release in the other slot.

The compatibility image derives from the exact original live immutable backend
digest `sha256:d8feec1bc12fbcac2d084c192a57f360593514e220b4bb9b23dc0acfc90e8c9b`
and changes only those migration files and its source revision label.
Independent source review found and corrected pipeline failure masking before
the compatibility commit was pushed. The owned PostgreSQL16 rehearsal verified
the real default CMD, strict production settings, seeding/bootstrap disabled,
two workers, child replacement, complete restart and persisted shared counters.
Initial worker PIDs46/47 became47/149 after replacement and28/29 after restart.
The migration files are byte-identical to the application candidate.

The compatibility commit is **not** in the already-built application commit's
ancestry. The exact published application artifact was retained; the separate
compatibility identity and intermediate transition are recorded explicitly.
This is a procedural deviation, not an ancestry-compliance claim.

## Backup and migrations

Verified PostgreSQL16 backup:
`/opt/milana-erp/shared/backups/auto_pre_20261119_025033.dump`.

- Dump bytes:131,242,722; mode0600; restore objects:1,400.
- Dump SHA-256: `fdb89d59f259263a0192299301df5ffd8c62d439b65db805d4e37e483dd030a0`.
- Restore-list SHA-256: `b57145d062ff37fb7d22773fcd13424e148d27d8e0efd6543e595b1b16f44515`.
- Pinned client: `postgres@sha256:e013e867e712fec275706a6c51c966f0bb0c93cfa8f51000f85a15f9865a28cb`.

Preflight proved revision0157, no existing CEO role and no snapshot table. Explicit
candidate Alembic migration applied0158/0159 before candidate startup. Revision0158
creates one unassigned empty-permission CEO role;0159 creates the independent
`ceo_balance_snapshots` table. No CEO account assignment, snapshot capture or
capture schedule was created. No operational business form/action was submitted.
Actual live and rollback runtime environments have startup seeding and schema
bootstrap disabled. Application rollback must not downgrade the database.

## Validation and read-only production evidence

Exact application CI passed all backend shards, PostgreSQL/bootstrap/locking,
frontend/build/contracts and security jobs before publication. The derived
compatibility digest was also scanned locally using checksum-verified Trivy0.76.1;
the repository's accepted-findings policy passed with no blocked findings.
This is not a zero-vulnerability claim: pre-existing accepted/unfixed OS findings
remain in the backend scan.

The exact compatibility scan, policy decision, official scanner checksums,
source-image identity and recovery receipt are retained mode0600 under
`/opt/milana-erp/shared/deployment-evidence/20261119_025033/security/`.

The two image versions read one exported PostgreSQL snapshot using read-only
transactions and storage. The dependency write-refusal challenge passed with
SQLSTATE25006. Complete ordered response hashes matched for:

| Workflow | Rows |
| --- | ---: |
| Sales | 100 |
| Production | 738 |
| Material batches | 1,615 |
| Packages | 10,665 |
| Cutting | 878 |
| Work orders | 3,008 |
| Shipments | 289 |

These counts reflect the existing QA reader's real scope; they are not claimed as
company-wide totals. Package probes used read-only storage/transactions so QR
repair GET behavior could not write production files or rows.

The initial installed performance wrapper exited with a generic Docker failure;
the wrapper did not expose the underlying probe reason. That failure is not a pass.
A subsequent explicitly traced diagnostic epoch stored stdout/stderr, passed
all 21 alternating samples per slot, and measured these candidate versus baseline
median/p95 milliseconds:

| API | Baseline median/p95 | Candidate median/p95 |
| --- | ---: | ---: |
| Sales | 33.99 / 38.24 | 35.05 / 40.03 |
| Production | 40.16 / 67.54 | 38.49 / 44.13 |
| Material batches | 57.57 / 69.02 | 58.72 / 67.18 |

A separate search gate passed exact result counts and zero payload growth.
Candidate median changes were global search+0.64%, inventory batches-0.24%,
inventory stock-0.13%, model groups-4.61%, model options+1.62%; all p95 budgets passed.

After cutover the public HTTPS search benchmark completed with medians152â€“229ms
and p95 values160â€“373ms. No pre-cutover public-network benchmark was captured;
these figures establish current operation, not a before/after latency improvement.

Read-only CEO service queries succeeded for ALL/MIL/BST/ECO over seven Tashkent
days, including current balances; runtimes were229â€“391ms. Real candidate HTTP
requests denied anonymous access with401 and the existing non-CEO administrator
with403. CEO assignments and snapshot rows remained zero.

The connected browser inventory was readable, but tab creation/claim/navigation
failed with an adapter `timeoutMs` error through both documented entry points.
No signed-in visual or console pass is claimed. The owner approved deployment;
no separate exact-plan QA-master report was supplied or fabricated.

## Activation, observation and closing

Compatibility activated backend03:09:07 UTC, frontend03:09:26 UTC. Both source
and runtime identities verified before replacing the old inactive slot.
Final application activated backend03:13:46 UTC, frontend03:14:03 UTC.
Both final source manifests/slots agree. The two current and two rollback
containers had zero restarts/OOM; both backends had exactly two workers.
HAProxy validated and both routers were active. All four required internal/public
health/login checks returned200 and health reported the exact release.
Postflight PostgreSQL had35/100 connections, zero invalid indexes, schema0159,
zero CEO assignments and zero snapshots.

The high-risk 30-minute observer started03:14:54.701154 UTC, with earliest completion
03:44:54.701154 UTC. Local evidence:
`C:\ERP\.codex-work\deploy-ismoiljon-20261119\outputs\deployment\20261119_025033-observation.json`.
The observer completed 1800.22 seconds with 61/61 rounds and 244/244 endpoint checks at200.
Its SHA-256 is `692fdc72ff8adb7f69ecc4e563016bf16889f4cbc081fb4dfa98e245df190aa3`.
This is health-only success; closing performance subsequently failed.
The observer and protected closing journals were copied mode0600 on both hosts
to `/opt/milana-erp/shared/deployment-evidence/20261119_025033/closing/`; backend
evidence includes the complete paired timings and migration/phase journal.

Protected raw source/backup/API/phase/performance evidence is under
`/opt/milana-erp/runtime/manual-20261119_025033*` and the migration log under
`/opt/milana-erp/shared/deploy/`. Public-only evidence must not contain credentials,
business payloads or environment contents.

## Failed closing performance and guarded recovery

Fresh closing identities, manifests, proxy validation, two-worker checks,
zero restarts/OOM and recent application logs passed on both slots. The first
21-pair closing epoch failed material-batch p95: 88.30ms versus 75.22ms, despite an
improved candidate median 56.58ms versus 58.42ms. Raw failure evidence was retained.

One predefined diagnostic then used 101 balanced AB/BA pairs per endpoint after
ten warm-up pairs, alternating endpoint order and serial requests, with unchanged
10% median/15% p95/15% payload budgets. It was not repeated until green.

| API | Recovery median/p95 ms | Candidate median/p95 ms | p95 change |
| --- | ---: | ---: | ---: |
| Sales | 33.583 / 40.182 | 34.419 / 72.863 | +81.332% |
| Production | 35.733 / 45.633 | 36.938 / 238.264 | +422.131% |
| Material batches | 56.385 / 67.589 | 57.155 / 95.845 | +41.806% |

All three p95 comparisons failed while medians stayed within budget. Candidate
maxima reached 835–968ms. The candidate was serving real users and recovery was
idle, so load is a confound; no source cause is established. Source review found
no batches-specific query change. Additional authenticated static-file checks are
a possible contention mechanism, not a proven diagnosis.

Closing public medians remained 150–227ms; some public p95 values also varied
above the earlier same-release measurements. Those are not a pre/post application
comparison. Do not claim that all closing performance checks passed.

The deployment procedure's regression guard required recovery. Before switching,
read-only SQL confirmed zero CEO assignments. Backend was restored03:48:40UTC,
frontend 03:48:57 UTC to compatibility 030500, blue. Both complete source/runtime
identities matched the frozen compatibility phase; all four health checks returned
200 and health reported 030500. Database remains 0159; observed recovery check had
39/100 connections, zero invalid indexes, zero CEO assignments and zero snapshots.
No schema downgrade, stamp, account/session mutation or business form was used.

The rejected green candidate remains held, with its source/images and all failed
measurements preserved. Explicit authorization of these newly measured latency
regressions, or a verified fix, is required before another activation. Disk-only
waiver and health success are not claimed as performance acceptance. The automatic
worker remains stopped and disabled. The attempted CEO deployment is not complete.

## Remaining risks and follow-ups

- Disk capacity remains an owner-overridden risk; no protected data was deleted.
- Keep CEO unassigned while depending on this old-application rollback. If CEO
  accounts are later assigned, disable them and invalidate their sessions before
  rolling back to an application without the CEO authorization guard.
- The old application's reviewed catalogue-price import allowlist excludes0159;
  that operation safely returns409 on rollback. The final application explicitly
  accepts0158/0159. Do not claim full write-operation parity for the old rollback.
- Signed-in browser/console verification and separate QA-master acceptance remain
  unrecorded. Historical CI/review evidence does not become live visual evidence.
- The initial performance wrapper failure remains unexplained despite the traced
  paired epoch and independent search pass.
- No pre-cutover public-network benchmark was captured; post-cutover public
  measurements cannot establish a before/after network-latency improvement.
- Closing snapshots need a separately approved 23:59 Asia/Tashkent schedule and
  first-sample reconciliation; missing past samples remain unavailable by design.
- Automatic deployment stays stopped and disabled after guarded recovery. Review its pinned
  recipe policy against the new sharded CI, baseline and owned reservation before
  separately restoring unattended polling. Do not bypass protected journals.

## Worktrees and handoff

The legacy `C:\ERP` checkout and its unrelated local work were preserved.

| Dedicated worktree under `C:\ERP\.codex-work\` | Branch / Git state |
| --- | --- |
| `deploy-ismoiljon-20261119` | `codex/deploy-ismoiljon-20261119`, initial `a46eba5e8`; observation output only, no source commit/merge |
| `ceo-rollback-compat-20261119` | `codex/ceo-rollback-compat-20261119`, `437523dbd`; pushed, not merged; compatibility backend deployed |
| `record-ceo-release-20261119` | `codex/record-ceo-release-20261119`; documentation/baseline record pushed, not merged |

The record worktree is clean after explicit-path commits. The observer's twelve
stdlib tests and `git diff --check` pass. Final fresh internal backend/frontend
and public health/login checks all return200, with health identifying030500.
The Obsidian mirror's current section names the recovery release; surrounding
existing note bytes were preserved. The integration branch still holds the
rejected application source and its earlier baseline until the record is merged;
automation stays disabled and future work must reconcile this explicitly.
