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
Narrow runtime11f80a29 is staged blue20261103_094602, not yet serving public traffic.
Verified backup preceded additive schema0150; no production business writes.

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
Compatibility ef5f8091 contains exact old420 app plus identical0150 migration only.
Immutable image defaultCMD, strict production security, two freshworkers, child
replacement and full restart must pass in isolated CI before cutover. Compatible
green staging and rollback-state registration will preserve activeblue routing,
source, image IDs, schema and all business ledger rows, with bothhost ownedlocks.
No production worker kill/restart or schema/security bypass is permitted.

Final public closing checks/cutover/compatible rollback record remain pending.
The earlier wider affected race failure remains in the feature packet; it is not
relabeled PASS. Human acceptance remains separate.
