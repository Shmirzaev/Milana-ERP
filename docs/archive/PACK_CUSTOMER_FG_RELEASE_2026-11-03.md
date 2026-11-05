# Customer-pack restriction and FG numbering release, 3 November 2026

Owner instruction: "push merge and deploy with recent changes made by me to
without 30 minute monitoring". Clarification: "no only customer shipment pack
and FG model no". This narrows runtime scope to these two patches; HR preview,
pending integration refactors, dependency/platform/security changes are excluded.
Timed monitoring is waived; immediate health, source, database, performance and
browser gates remain required. No production business-data creation is authorized.

Release worktree: C:\ERP\.codex-work\pack-customer-fg-release-20261103.
Branch: codex/pack-customer-fg-release-20261103. Exact base42078704 is the active
green20261102_063110 source; both full manifests were verified against recorded
becda671a332afe6fe86857ab948be2d686c984e81d02e6e68053ba83cb7a079.
Old blue20261031_092951 was replaced only after candidate staging gates. Older
images are NOT restart-compatible with schema0150 because of strict exact-head
startup verification; a separate exact-old-runtime compatibility image is required.
Application rollback removes customer enforcement; it does not undo release history.

Customer patchaf630418 and FG patch936c4601 were ported by exact reviewed
backend/frontend diffs, applying cleanly with three-way verification. Production
QR order sizes and older physical-pack history remain unchanged. Source links,
quantities and existing reservations remain protected; admin release is audited.
FG is configuration-only, using the existing counter/advisory lock; firstFG202001.

Implementation/integration: /root. Independent review: /root/customer_guard_review.
PostgreSQL verification: /root/customer_guard_tests. Human domain owners/reviewers
remain Mirshoir/Ismail and Ismail/Mirshoir; operator acceptance belongs to Shavkat.
User authorization permits merge/deployment, without inventing technical acceptance.

Initial narrow-candidate verification:92 focused cases passed, including46 actual
customer API cases, three PostgreSQL release races/rollback,16 shipment query/lock
budgets and27 numbering/persistence/performance cases. Five additional real
PostgreSQL FG cases passed with zero skips: first/readonly preview, blocking
concurrent unique allocation, occupied/stale families and rollback with absent or
existing settings. Each used a fresh migrated identity-pinned disposable database.

The broader clone_main build was cancelled after the owner's clarification; it
is not release evidence. Narrow exact-source CI41613691672 and integration PR376
CI passed. PR376 merged at54a51d79, preserving bothfeature commit ancestries.
At initial staging, narrow runtime11f80a29 was blue20261103_094602 and not yet
serving public traffic. Verified backup preceded additive schema0150. No business
forms were submitted in production; the later automated seed effect is recorded below.

Candidate actual connected Chrome and GET-only readback passed. Native Chrome
capture began working after the user opened a new window. Isolated denial/admin
release/warehouse role/FG save+reload proof and database quantity/source/ledger
readback were inspected. Production FG202001 already exists since October28;
readonly preview202002 correctly avoids occupied identity. Candidate console:0.
Seven paired endpoints passed120 samples each, median/p95/payload/result-count gates.

The original old-green zero-OOM precheck remains recorded FAIL: a November3
03:19:14UTC historical OOM killed one child. Independent review accepted ONLY
unchanged container, worker PID pair, cgroup/kernel event counters and adequate
memory; no new event occurred during baseline, pairing or staging. Candidate
containers have zero OOM/restarts. Historical evidence is never reset or erased.

A recovery audit caught the old image's strict head0149 startup rejection after
schema0150. Existing green workers remain healthy, but must not be restarted.
Final compatibility37337ea6 contains exact old420 app plus identical0150 migration only.
Immutable image defaultCMD, strict production security, two freshworkers, child
replacement and full restart must pass in isolated CI before cutover. Compatible
green staging and rollback-state registration will preserve activeblue routing,
source, image IDs, schema and all business ledger rows, with bothhost ownedlocks.
No production worker kill/restart or schema/security bypass is permitted.

## First activation, retained failure and credential reversal

Feature11f80a29 first activated on both hosts at 11:54UTC. All four health checks,
public Chrome FG/admin-dialog checks, full-history GET readback and the original
seven-endpoint closing performance comparison passed without threshold exceptions.
The subsequent inactive compatibility-backend verification failed: Docker image
metadata omitted the unset Entrypoint key, and the inherited production environment
had RUN_SEED_ON_STARTUP=true. The first recovery attempt restored only the frontend;
both roles remained healthy but temporarily served different source releases.
Neither failed verification nor the partial recovery is relabeled PASS.

The one-shot verification helper now accepts an omitted/null default entrypoint
and continues to reject command/entrypoint overrides. Its no-seed guard remains
strict. Under both owned deployment locks, a mode0600 backup and exact byte/state/
container CAS changed only RUN_SEED_ON_STARTUP from true to false. Other configuration
bytes were preserved. The inactive compatible backend was recreated from its exact
CI image with seed disabled, then both roles were restored to green20261103_112256 /
37337ea6. Default command, strict0150 startup, two workers, no OOM/restarts and all
four health checks passed. Earlier historical-continuity diagnostics remain retained.

Memory-only, read-only comparison of the original10:19 backup, final11:43 backup and
live database proved that initial startup seed at10:20:31 reset one configured admin
password hash. Departments21, roles22, warehouses11, sewing flows76 and user count39
were unchanged; optional sample/demo/import flags were false. No access/profile field
differences were found. Other user differences were login/seen/update timestamps.

After a fresh verified full backup at12:11:17UTC, a separately reviewed single-account
SERIALIZABLE/row-lock/parameterized-CAS transaction restored only the exact original
password hash. All other columns were compared before commit. Independent readback
confirmed the original hash was restored, the reset value was gone, protected fields
were unchanged, and startup seeding remained disabled. No identity, secret, password
or stored hash is published. Four actual isolated PostgreSQL cases exercised success,
intervening credential refusal, missing-acknowledgement rollback and trigger-change
rollback. The original incident assessment and separate restoration readback are kept.

## Explicit resumption phase

The inactive feature backend was recreated from the same reviewed11f80a29 image
with seed disabled. Original container IDs, failed outcomes and old performance
measurements are preserved. Separate phase IDs and resource pins cover the new
backend and both verified compatible greens. Fresh public baseline and paired
120-sample fixed-query measurements use the same recovered green client throughout
this phase. Forward checks retain memory headroom above1.5GB, zero OOM/restarts,
strict schema/no-seed/default command, source/state/proxy/image CAS, pool budget,
and independent recovery of both roles to the already verified green containers.
Fresh baseline and paired checks passed all7endpoints. The resumed cutover and
public Chrome/readback checks passed. Final public closing failed Model Options
p95:162.26 ->193.23ms (+19.09%); median153.52 ->153.81ms (+0.19%); rows1/payload261
unchanged. Other6endpoints passed. This failed result is retained without resampling.
Cause is unproven; endpoint code is unchanged, which does not rule out indirect
runtime/workload/transport effects. The15% automatic-stop rule was honored.

Both hosts were restored to compatible green37337ea6 at12:27UTC. At that checkpoint the active release
20261103_112256, full source manifest8c5521db580320842925229aff26e659202b4beef6752afa82d7b480dc677bbf,
schema0150; inactive blue11f80a29 retained but reactivation requires an explicit
owner exception for this specific p95 failure. All4health checks200, defaultCMD,
strictstartup/no-seed/two-worker/log/source/proxy/readiness/pool checks passed;
DB24/100connections and0invalidindexes. Both backend slots have0OOM/oom_kill and
no container restarts; original historical OOM evidence is retained. Disk78.66%
backend/78.54%frontend remains above70%alert/below80%stop. Both owned locks released;
task-owned local backend/frontend/proxy/PostgreSQL QA services stopped. No30-minute
monitor ran. The exact verified pre-release admin credential remains restored.

The earlier wider affected race failure remains in the feature packet; it is not
relabeled PASS. Human acceptance remains separate.


## Owner-approved p95 exception and final active release

At12:35UTC the owner explicitly answered **"Re-deploy with this specific p95
exception"** for exact11f80a29 and the retained Model Options p95 failure above.
This is not a blanket threshold waiver. That comparison stays FAIL; no repeat
measurement was used to hide it. Other six endpoints, all medians, rows and payload
passed. The cause remains unproven. The separate30-minute waiver remains in effect.

Integration was re-fetched and pinned to own incident-record PR383 merge10c525c2.
Its baseline37337ea6 matched both live hosts. Under newly acquired owned locks,
source/controller/state/proxy/both-container IDs, no-seed/default-command/stricthead,
two-worker continuity, readiness/pool48/100, memory, logs, database and disks passed.
A fresh root0600 full PostgreSQL backup at12:37:20UTC contained1251restoreobjects,
111104711bytes, dumpSHAf8b8a5dd976f678e9794b26fb3d0a18b366420bb519864b47b726e2998a87fb9,
and restore-list89845bytes/SHA61f81fd598b9845687d34bb5a42272eb2c7f89f85ce40f454e9dec74d9eb9e50.
Its path is /opt/milana-erp/shared/backups/milana_erp_pre_exception_20261103_094602_20261103_123720.dump.
The backup follows verified credential restoration; no new migration or data repair ran.

The same reviewed immutable11f80a29 images were reactivated on BOTH hosts at
12:38:09UTC /17:38:09Tashkent. Final activeblue20261103_094602 has source manifest
ee765f999e782193878390897873c7b5865749460d4d776cf321fcd28490f8a9 and schema0150.
Compatiblegreen20261103_112256 /37337ea6 remains live and ready for rollback.
Neither image was rebuilt or replaced in this exception phase; no HR source deployed.

Fresh immediate and final postflights passed all fourhealth200, full source/image
provenance, exact routing, strict defaultCMD/no-seed/head0150, ready/pool, logs and
resource continuity. Connected public Chrome showed FG202002 (FG202001 already
exists) and the exact selected pack/reason-required/disabled-empty-submit release
dialog, cancelled without submitting; warnings/errors0. GET-only full-history
readback found437groups, PKG241/BPK196, denied403, and matching old-run/pack/model/
date-receipt filters. Actual isolated and PostgreSQL tests provide the customer-bound
scan/admin-release persistence proof; no bound production test data was created.

Final12:39:18UTC: DB24/100connections, invalidindexes0; both backend slots two
unchangedworkers, cgroupOOM/oom_kill0 and zero container restarts. Release ledger
remains0rows with unchanged hash. Disk78.72%backend/78.54%frontend stays below80%
hardstop, above70%alert. Both owned leases released, task QA services stopped.
Independent reviewer /root/customer_guard_review found no blocker in the scoped
exception, preserved history, source/image pins and fresh public evidence. Earlier
failed measurements and incident outcomes remain unchanged above and in JSON.
No timed30-minute monitoring ran; human operator acceptance remains separate.
