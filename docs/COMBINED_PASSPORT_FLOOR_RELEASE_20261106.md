# Combined Cutting/passport/fabric release — 6 November 2026

User explicitly authorized deploying today's three passport fixes together with
yesterday's seven fixes: search icon padding, reason-required Cutting rejection,
blank Planning piece defaults, model/variant shipment package identities,
Milana-style Eco fabric inventory, GEM/GEMX Qolip attachments, and one shared
100 + 200 = 300 kg passport calculation. Use connected Edge visual QA. The user
explicitly waived the 30-minute timed observation; do not start a substitute
timed monitor. All immediate health, backup, source/image, migration, QA and
performance gates remain required.

Clean dedicated worktree: `C:/ERP/.codex-work/deploy-passport-floor-20261106`.
Branch: `codex/deploy-passport-floor-20261106`. Both sources descend from exact
live `488f3d654` / release `20261105_065721`, manifest
`e6c603d4c1954c64a75962cf189427eb5e316c039ea23de4699b9bd4f3112095`.
Backend and frontend pointers were freshly reverified; baseline matches.
Today's parent is `4ed5063c4`; yesterday's parent is `ca022ca0f` (including
`ac3d6e041` and `88f1d06c6`). No unrelated clone_main runtime work is included.

Root Codex integrates and deploys; independent `passport_review` reviews the
combined operations. `ect_fabric` owns the narrowly assigned grouped-transfer
integration and tests, and `qa_environment` owns isolated QA infrastructure and
fixtures. Human engineering owners remain Mirshoir/Ismail by domain. This request
supersedes the earlier no-deployment instruction for these exact changes.

## Integration and acceptance

- Count pieces per logical saved material row, never per batch allocation.
  Two old parents/four 600-piece rows total 2,400. One 600-piece calculation
  allocated 100/200 kg remains 600 pieces, one set of rolls and 300 kg.
- Keep both Excel model/variant pictures and precise source allocation labels.
- Mapped ECT transfers use authoritative Eco physical balances for each grouped
  source, including depleted/archived Milana source identities. No guessed ID
  mapping, second Milana debit, QC bypass or cross-factory access.
- Preserve used grouped calculations and permit notes-only changes without
  treating exhausted archived stock as newly available for another cut.
- Rejection must require/save reason and refuse existing execution or stale
  mutation attempts. Plans, reservations and downstream facts remain preserved.
- CAD files remain opaque authenticated attachments, not image previews. All
  layout/identity/default changes preserve established business operations.

## Gates and release state

Integration and combined verification are in progress. Record exact commit,
CI/image/archive digests, fresh verified backup, staging slot, no-op migration,
performance, Edge visual/readback and immediate postflight evidence before
claiming Live. Retain all prior failures and actual skips as such. No production
mutation has occurred at packet creation. No production business test rows may
be created. Existing detailed source evidence remains in the three yesterday
packets and `PASSPORT_TOTALS_ECT_20261106.md`; prior passes do not verify the new
combined source.
