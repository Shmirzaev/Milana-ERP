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
Retained blue20261031_092951 remains compatible with additive migration0150.
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

The earlier broader clone_main build was cancelled after the owner's clarification;
it is not release evidence. Full exact-source release CI, candidate/read-only
browser, backup/migration, performance and immediate cutover checks are pending.
Production remains unchanged until those gates pass. The earlier wider affected
test race failure remains recorded in the feature packet; it is not relabeled PASS.
