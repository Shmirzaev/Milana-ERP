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
The complete immutable workflow subsequently passed this exact committed release source.

Read-only preflight found approximately 77% used disk on both application VMs:
above the 70% alert but below the hard 80% staging limit. Recheck after image pull.
Installed slot controller hash on both VMs is
`d422ff74b96c92115c3c657a02a1732925df5a3565f81b3f3a00bf0e9a5394a1`;
its exact relationship to the release controller is part of the staging review.
Do not modify active releases, live containers or business rows while preparing
the candidate. Green is the intended inactive slot; keep blue untouched until
every pre-cutover gate passes and retain blue after activation for rollback.

The following section records actual promotion and closing evidence. No timed health observer ran.


## Final active release and immutable provenance

Active on both roles: **green `20261102_063110`**, runtime `42078704df340558c8a21bf1ef14bf74cc87b222`.
Final activation: 2026-11-02 12:15:43 Tashkent. Compatible running rollback: blue `20261031_092951`,
runtime `337ff3c01bb4778232dad9973d7c996396717e14`. Original blue container IDs/images remain unchanged.
Both active source manifests fully verified clean at `becda671a332afe6fe86857ab948be2d686c984e81d02e6e68053ba83cb7a079`.
Source archive SHA-256 `071ec8447fa902fa8d7407e9ed7a38eee68363b06d12abac6142051fa40cf643`, 4552767 bytes,
1829 files. Deployed source directories were never edited in place.

[Exact-source CI](https://github.com/Shmirzaev/Milana-ERP/actions/runs/41400415478)
passed backend, frontend and immutable-release jobs: 4,886 backend cases with
544 opt-in skips; separately required PostgreSQL suites passed 165 and 176 cases,
with additional 7/11/20-case gates passing. Local strict types, production build,
lint and affected regressions passed as recorded above; existing lint warnings remain.

Backend: `ghcr.io/shmirzaev/milana-erp-backend@sha256:8f849363a05a630fafd7a195bbc4be931f89aae44702b08175ffaca45d817011`.
Frontend: `ghcr.io/shmirzaev/milana-erp-frontend@sha256:68a33dbbd280b294ea138d288d3d1f642ac8efc86161fdbd3858c4873aa1b223`.

Fresh retry backup `/opt/milana-erp/shared/backups/milana_erp_pre_20261102_063110_20261102_071501.dump`: 107604136 bytes, mode 0600,
SHA-256 `2b4f8046bd1a014902f20e817c84e4729b672a9370b9e6388737110b92280b24`. Restore listing: 1246 objects,
89402 bytes, SHA-256 `27169bbadf1d0383f87cb50b6a9d78f8483d7c62cfb83e3c4e36d85ae3f5f4e4`.
The earlier pre-cutover backup remains retained separately in machine evidence.
Alembic upgrade was a no-op; revision remains `0149_besttex_cutting_access`.
No business records, quantities, reservations, receipts, shipments or labels were
created/changed/deleted by this task. QA used GET-only APIs and read-only SQL.

## Browser, authorization and performance

Actual staged and public APIs enumerated 377 active groups in 50-row pages.
Old pack `PKG-2026-000159`, PRN `PRN-2026-000012`, model `BM8010-V-6451`,
and 12 October Tashkent received-date queries returned expected groups.
Candidate/public whole-history fingerprints matched. Existing PKG/BPK actors
saw scoped totals 216/161; a denied actor received 403. Legacy-list and unchanged
paged payloads matched previous blue. No access policy changed.

Connected Chrome inspected the actual staged app and public Uzbek app, including
page3 (101–150), old-pack lookup, date/receipt combinations, clear/reset and
reversed-date rejection. Final public combined lookup returned the same oldest
run with 5 packages / 450 pieces, received at 10:45:25 Tashkent on 12 October.
Console warnings/errors: zero. Final screenshot remains at
`C:\ERP\.codex-work\older-pack-filters-release-20261102\outputs\deployment\public-old-pack-final.jpg`.

Paired old/new performance passed all 7 endpoints, 120 measured samples each,
alternating order from the unchanged blue client. Final public comparison uses
the original pre-cutover baseline, same client/queries and 120 measured samples.
Budgets remain median+10%, p95+15%, payload+15%, identical row counts; no latency
exception was requested or used for this release. Measurements are in the linked
machine record; maximum payload across samples is used conservatively on retry.

### Retained aborted first attempt and reviewed instrumentation retry

The initial closing benchmark exited1 before emitting comparison JSON. Both roles
were immediately restored to original blue and all four health checks passed.
That attempt remains **FAIL, cause unknown**; its suppressed stderr cannot be
recovered, and no latency/result comparison is claimed for it.
Later read-only diagnostics found all 7 endpoints 200, zero candidate tracebacks,
exceptions or 5xx, and live response-size changes during factory activity.
These changes suggest an instrumentation issue but do not prove the original cause.

The harness had required exact byte-count constancy across all live samples,
which DEPLOYMENT.md does not require. Independent review approved one bounded
retry: preserve original baseline/first failure, require constant row counts and
HTTP 200, use maximum payload, retain all thresholds and 120 samples, and capture
progress/stderr. Synthetic varying-payload, changed-row and HTTP-failure checks
passed independently. Same source/images were revalidated; a fresh backup was
taken, both roles reactivated, immediate checks and actual public API/browser
repeated, then the instrumented public comparison passed without an exception.
No failed measurement was erased or relabeled PASS.

## Closing checks, rollback and handoff

Fresh closing checks passed: all four internal/public health endpoints 200, both
source manifests, slot/current/image identities, retained blue IDs, valid active
HAProxy routers, both-slot readiness, exactly 2 backend workers with 8+4 pools
(48/100 overlap ceiling), zero restarts/OOM/log error markers, database headroom
and zero invalid indexes. Schema stays 0149. The shared controller was installed
from exact reviewed release source on both VMs at hash
`13a9e19d5b266c87d138cb2866a185fedf45a089b85534d26fb28667eb95c3f3`.
Previous controller hash `d422ff74` is retained at
`/opt/milana-erp/shared/deploy/controller-backups/slotctl-before-20261102_063110.py`.
Both retained runtimes support readiness; ordinary application rollback uses
blue and does not require restoring the previous controller.

Post-pull staging disk fractions were backend77.35%, frontend77.92%: below 80%
hard limit, still above 70% alert. No release cleanup was performed for this task.
The owner explicitly waived 30-minute monitoring; **no timed observer ran**.
Human factory/operator acceptance remains pending; keep PACK-HISTORY-100 active.

Release worktree: `C:\ERP\.codex-work\older-pack-filters-release-20261102`,
branch `codex/older-pack-filters-release-20261102`, source `42078704df340558c8a21bf1ef14bf74cc87b222`.
Integration record worktree: `C:\ERP\.codex-work\older-pack-filters-record-20261102`,
branch `codex/record-older-pack-filters-20261102`. Its merge includes the exact
release ancestry and metadata/docs only against clone_main; existing pending
integration runtime changes are preserved and were not deployed.

[Structured evidence](OLDER_PACK_FILTERS_RELEASE_2026-11-02.json) preserves both
attempts, artifact/backup/container identities, original and final performance,
readback, authorization, browser and closing results without credentials.
