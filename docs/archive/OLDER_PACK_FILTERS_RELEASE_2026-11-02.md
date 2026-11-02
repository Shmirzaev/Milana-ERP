# Older physical-pack filters: release record — 2 November 2026

Owner instruction: “now deploy it with recent change about old packs without 30 minute monitoring”.
This authorizes deployment and waives timed observation, without waiving source,
backup, immutable CI, candidate/browser, performance or immediate postflight gates.

Active verified source before work: blue `20261031_092951`, exact runtime
`337ff3c01bb4778232dad9973d7c996396717e14`; both full manifests clean at
`f270b044a9b67069e44e3954f671bd59f9456146afd13221584f12053c2a3a94`.
Compatible rollback before work: green `20261029_111113`. Database revision is
`0149_besttex_cutting_access`. Both live slot state files agree with these identities.

The reviewed feature was merged through PR369 at integration `1ed3c5c7`, but
`clone_main` also carries unrelated un-deployed work. Release worktree
`C:\ERP\.codex-work\older-pack-filters-release-20261102`, branch
`codex/older-pack-filters-release-20261102`, therefore starts at exact active
`337ff3c0` and includes only the reviewed filter runtime/test paths from `f074dab6`,
current production-base metadata and their durable context/evidence documentation.
No other integration runtime, dependency, schema, permission or migration change
is included. Process QR runtime bytes are preserved.

Actual implementation/integration: `/root`; independent review: `/root/review_merge`.
Packaging engineer/reviewer remain Mirshoir/Ismail; business acceptance belongs
to Shavkat/operators. The reviewer independently verified file identity, imports,
unchanged dependencies and rollback compatibility, and passed 50 affected tests.
Integrator passed 61 affected backend cases, repository Ruff/compilation, strict
TypeScript, scoped ESLint and the actual component browser checks in EN/RU/UZ at
desktop/phone widths, including paging, dates, reset and total-shrink recovery.
The complete immutable workflow will revalidate this exact committed release source.

Read-only preflight found approximately 77% used disk on both application VMs:
above the 70% alert but below the hard 80% staging limit. Recheck after image pull.
Installed slot controller hash on both VMs is
`d422ff74b96c92115c3c657a02a1732925df5a3565f81b3f3a00bf0e9a5394a1`;
its exact relationship to the release controller is part of the staging review.
Do not modify active releases, live containers or business rows while preparing
the candidate. Green is the intended inactive slot; keep blue untouched until
every pre-cutover gate passes and retain blue after activation for rollback.

Activation and final release/image/backup/performance/browser/postflight identities
will be appended after their actual results. No timed health observer is to run.
