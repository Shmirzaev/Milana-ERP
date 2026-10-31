# RF-013 single-host rollback rehearsal — 27 October 2026

## Scope and result

Task / state: RF-013 / AI checks recorded, awaiting Mirshoir review. Dilmurod owns the tooling; Mirshoir reviews the rollback procedure and limits. No production host, database, or `/app/storage` was used. The run created and removed a named local Docker network, PostgreSQL 16 database volume, application storage volume with a SQLite shared store, two backend containers, two frontend containers, and one real HAProxy container. Only loopback ports were published.

Old source: `ec02b5f87ea3db9543be389b47d88358232b9a3d` (before the service namespace move). Candidate: `111a05c5fbc4e44790d6d075f8db78adaaffdf9f` from `clone_main`, plus this local rehearsal tool. Both sources used Alembic `0148_second_grade_packages`. This proves compatibility for the tested settings write across these two builds; it does **not** prove compatibility with future RF-005 writes or migrations. The same candidate revision's backend/frontend source was clean during the run.

The technical rehearsal passed. The candidate wrote `financial.default_currency=UZS`; the old backend read `UZS` after rollback and wrote `USD`, which the old backend read back. After a deliberately failed frontend activation, HAProxy routed to the stopped green frontend while frontend `slots.json` still named blue. Manual reconciliation restored both routes and both symlinks to blue/old and cleared rollback pointers because green was unhealthy. The operator must restage a healthy rollback pair before another cutover.

The Sewing 600 → 495 → 105 case was excluded: it requires production order, cutting, bundle and receipt fixtures. A settings write provides the smaller real database write/read compatibility check needed for this rollback mechanism. It does not test Sewing quantities.

## Reproduce locally

Use a disposable old worktree at the old commit and a clean candidate worktree on this branch. Run from the candidate root with a local Docker Unix socket:

```sh
python3 scripts/rf013_local_rehearsal.py \
  --old-source /absolute/path/to/old-worktree \
  --candidate-source /absolute/path/to/candidate-worktree
```

The script refuses a remote Docker endpoint, non-worktree source, dirty tracked backend/frontend files, or an old commit that is not an ancestor of the candidate. It patches `slotctl.py` paths and commands only in memory; actual `stage()` and `activate()` execute. The local HAProxy adapter copies each validated config inside the container before signaling reload to avoid Colima bind-mount propagation races. Run evidence stays in `.codex-work/rf013-runs/`; the generated credentials file is removed during cleanup. Only resources with the run's random `milana-rf013-*` prefix are removed.

## Predetermined §4 workload and bounds

Recorded before execution: GET `/health`, `/ready`, and frontend `/login` every 0.5 seconds through stable HAProxy listeners; three concurrent requests maximum; 2-second probe deadline; 150-second observation window. One candidate PATCH of `financial.default_currency` from USD to UZS, old-version GET and PATCH back to USD, with an 8-second business-action deadline. The business deadline was raised from 2 seconds after early local worker/reload transients, before the final run. Expect old and candidate release headers to match active routing; expect frontend 503s after the deliberate stop and no unexpected steady-state 5xx. Stop for a data mismatch, over 60 PostgreSQL connections, unexpected steady-state 5xx, more than 30 seconds from **manual reconciliation start** to recovered old service, or more than 150 seconds of observation. Memory caps: each backend 1 GiB, each frontend 1 GiB, PostgreSQL 512 MiB, HAProxy 128 MiB. The backend cap was raised from 512 MiB after Uvicorn workers repeatedly restarted in an early attempt. Mirshoir's limit review remains pending.

## Route, state, and database evidence

Timestamps are UTC. `health/ready/login` gives the response code and observed local HAProxy release header. The full state files, symlink targets, HAProxy config hash/path, per-route responses, container states, database readback and PostgreSQL connection count are in [evidence.json](rf013-2026-10-27/evidence.json). Each phase's actual HAProxy config is archived in [the config directory](rf013-2026-10-27/), with [HAProxy logs](rf013-2026-10-27/final-milana-rf013-1_daqqfw-haproxy.log) and backend/frontend/PostgreSQL logs alongside it.

| Phase and time | Backend route | Frontend route | `slots.json` backend/frontend | Symlinks | DB currency |
| --- | --- | --- | --- | --- | --- |
| Old active, 13:02:38 | 200 old / 200 old | 200 old | blue / blue | old / old | default USD |
| Candidate staged, 13:02:55 | 200 old / 200 old | 200 old | blue / blue | old / old | default USD |
| Backend forward, 13:02:56 | 200 candidate / 200 candidate | 200 old | green / blue | old / old | default USD |
| Candidate active, 13:03:00 | 200 candidate / 200 candidate | 200 candidate | green / green | candidate / candidate | default USD |
| Candidate write, 13:03:01 | 200 candidate / 200 candidate | 200 candidate | green / green | candidate / candidate | UZS |
| Backend rollback, 13:03:02 | 200 old / 200 old | 200 candidate | blue / green | candidate / candidate | UZS |
| Old restored, 13:03:05 | 200 old / 200 old | 200 old | blue / blue | old / old | USD after old read and write |
| Backend partial forward, 13:03:06 | 200 candidate / 200 candidate | 200 old | green / blue | old / old | USD |
| Failed frontend switch, 13:03:45 | 200 candidate / 200 candidate | 503, no release | green / blue, but HAProxy frontend green | old / old | USD |
| Reconciled old, 13:03:49 | 200 old / 200 old | 200 old | blue / blue, rollback pointers cleared | old / old | USD |

The generated HAProxy configs agree with the listed routes. At the failure snapshot, [the config](rf013-2026-10-27/haproxy-failed_frontend_switch.cfg) points frontend to green while frontend state remains blue. The [reconciled config](rf013-2026-10-27/haproxy-reconciled_old.cfg) points both roles to blue. All database snapshots remained on Alembic `0148_second_grade_packages`; peak observed client connections were 5 of the 60-connection stop limit.

The candidate frontend was stopped at 13:03:09.507. `slotctl.activate()` waited for its stable-listener health check and raised at 13:03:44.688 without restoring the route. Manual reconciliation then took 3.67 seconds; stop-to-recovered-old time was **41.41 seconds**. This longer outage is the operational risk. The run did not assert a 30-second total outage budget; its predeclared 30-second cap applied only after manual reconciliation started.

## Probe and gate results

The observation ran for about 54 seconds: 99 rounds, 297 GETs, about 5.5 requests/second total. `/health` and `/ready` were 200 in all 99 rounds. Frontend `/login` had 28 responses of 200, 70 of 503 and one 2-second timeout. Before the injected failure, all 21 frontend rounds were 200. The 503s were confined to the deliberately broken phase and the first reconciliation round. HAProxy logged `rf013_frontend_active/<NOSRV>` for the outage; after reload it logged successful old frontend requests. Median/p95/p99 probe latencies were: health 8.3/11.81/54.36 ms; ready 9.4/14.14/64.35 ms; login 2.9/66.09/215.68 ms (including failures). Per-container CPU and actual memory use were not captured; caps were enforced. No production capacity claim follows from this small workload.

| §5 gate | Result and evidence |
| --- | --- |
| Automated | **PASS** for the actual local end-to-end script, syntax and Ruff checks; see the PR check report for commands. Earlier attempts exposed local 512 MiB worker churn, Colima bind-mount config races, copied-config permissions and host disk pressure; they are not counted as passes. |
| Data integrity | **PASS** for the scoped setting: candidate UZS was read by old, then old wrote/read USD; revision unchanged. Sewing and future RF-005 writes remain untested. |
| Visual E2E | **BLOCKED**: stable frontend `/login` was exercised over HTTP but no real browser screenshots were viewed. This tooling rehearsal makes no visual acceptance claim. |
| Bounded stress/recovery | **PASS for the declared local scenario**, subject to Mirshoir's review of limits. Expected frontend failures and the 41.41-second total outage are recorded, not hidden. Host-level failure and dual-host routing remain OPS04 scope. |
| Independent/human review | **PENDING** Mirshoir. No production release or cutover was attempted. |

Human checklist: rerun on a machine with the stated resources; inspect the `candidate_active`, `candidate_write`, `old_restored`, `failed_frontend_switch`, and `reconciled_old` snapshots and matching HAProxy logs; confirm old reads candidate data, backend-first manual rollback restores both routes, and failure leaves routing/state divergent until explicit reconciliation. Decide whether the observed total outage and absence of an automatic compensating switch are acceptable for RF-005 cutover. Operator ownership for a production rollback still needs to be named at deployment time.


## Built release-image HTTP follow-up — 31 October 2026

Follow-up to #324. Dilmurod owns this tooling change; Mirshoir reviews it. User scope: replace the rehearsal's development frontend with built release images, rerun HTTP only, preserve the old evidence, and leave browser/independent/human gates unchanged. Tooling base: `5bffd255981c57e5f356f6f9b7fb568f55d585bf` on `clone_main`. No application, dependency, release Dockerfile or production change.

Both frontend slots now build their source's `frontend/Dockerfile` with repository-root context and backend source available to its build contracts. They inherit the actual release standalone command `node server.js` and `NODE_ENV=production`; the release image does not use a literal `next start` command. The isolated HAProxy API address is supplied at build time because production rewrites are baked; the public API argument is empty. Runtime command overrides are not added. Both backend slots already build their source's `backend/Dockerfile` and retain Alembic/Uvicorn without reload. Image IDs, source paths, entrypoints and commands are captured in [the new evidence](rf013-release-images-2026-10-31/evidence.json). The earlier development Dockerfile is no longer referenced by this runner.

The same historical sources were tested for comparability: old `ec02b5f87ea3db9543be389b47d88358232b9a3d`, candidate `111a05c5fbc4e44790d6d075f8db78adaaffdf9f`; both source trees were clean. Existing workload and bounds above were unchanged and declared before execution. Only run-owned local Docker network, slots, PostgreSQL/storage volumes and loopback listeners were used; all were removed afterward. No production or shared environment was contacted.

| HTTP rehearsal | Earlier development frontend | Built release frontend |
| --- | --- | --- |
| Failure injection to recovered authenticated old readback | 41.41 s | **41.31 s** |
| Manual reconciliation to authenticated old readback | 3.67 s | **3.73 s** |
| HTTP/settings compatibility | PASS | **PASS** |

The total measurement includes the failed activation wait and manual reconciliation; it is not a browser timing or a capacity claim. Sampling is every 0.5 s with a 2 s probe deadline. There were 94 observations per endpoint: `/health` 94 x 200; `/ready` 94 x 200; `/login` 27 x 200, 65 x 503 and two timeouts during the injected fault. Candidate UZS persisted through rollback; old read UZS, wrote USD and read USD; reconciled old read USD. Peak sampled PostgreSQL client connections: six, below the predeclared 60. Manual reconciliation remained below 30 s. Expected route/state mismatch occurred after frontend failure and was reconciled to old/blue for both roles. The detailed timestamps and samples remain in the new evidence; no claim of exact browser outage boundaries is made.

Checks: the two new frontend regressions failed before the change (wrong Dockerfile and missing development-image refusal); all three final unit tests passed, including unchanged backend context. The existing slotctl readiness/liveness contract passed by direct invocation. Ruff with repository config and `git diff --check` passed. Independent Codex review (`/root/review_ops08_hmac_guard`) found no actionable source/test issue; it did not rerun builds or checks. Reviewed script SHA-256 `f9d1dab82fbdd4410397a643fcd1286d09b924388fcd1d9f674a28676a5d3649`, tests `11d22fb0ddef2cd1cffa6d081751d49ab44fd63644e1ab4199e03bcc9357e686`.

**No RF-013 browser session was started.** The connected visual gate, independent rollback execution, human acceptance and Mirshoir's limit review remain pending; none is marked verified or accepted. This rerun tests the mechanism and these two historical revisions, not current production compatibility.


## Connected built-image browser rerun — 31 October 2026 (recorded 1 November)

Follow-up to #324 and #366, tooling `f9e55970`; old `ec02b5f8`, candidate `111a05c5`, both production standalone frontend images plus normal release backend images. Dilmurod owns tooling; Mirshoir reviews. The user supplied [the unchanged connected Chrome report](rf013-browser-2026-10-31/RF013_BROWSER_RERUN_2026-10-31.md). Its seven screenshots were personally inspected and archived next to [actual timed switch logs](rf013-browser-2026-10-31/timed-steps.jsonl), [database currency-change observations](rf013-browser-2026-10-31/currency-changes.jsonl), [complete run/probe/image evidence](rf013-browser-2026-10-31/evidence.json) and [container identities](rf013-browser-2026-10-31/containers-before-handoff.json). No production/shared environment was used.

- Candidate login/Settings displayed [USD initially](rf013-browser-2026-10-31/rf013b_2317_start_USD.jpg). Browser saved UZS and reloaded: [candidate UZS](rf013-browser-2026-10-31/rf013b_2338_baseline_UZS_saved.jpg). PostgreSQL observer recorded UZS at23:38:30.752 Seoul.
- **23:44 rollback switch was NOT WATCHED LIVE IN THE BROWSER**: the reminder arrived late. Controller logs record rollback start23:44:00.008, backend old/blue state23:44:00.943, frontend old/blue state23:44:02.010, completed snapshot23:44:04.657. The browser's after-switch check at23:45:35 showed [UZS without re-login](rf013-browser-2026-10-31/rf013b_2345_after_rollback_UZS.jpg). It saved and reloaded [USD on old](rf013-browser-2026-10-31/rf013b_2345_rollback_USD_saved.jpg); PostgreSQL observer recorded USD at23:45:48.744. This proves the scoped before/after persistence and session checks, not the live visual experience of the switch itself.
- Failed activation displayed [the router's bare503](rf013-browser-2026-10-31/rf013b_2352_failed_activation_503.jpg), with no app styling or Retry. Browser first saw503 at23:52:15, last at23:53:56 and first good reload at23:54:07; backend health remained available in the browser's sampled requests. The checker’s background probe was throttled and cannot rule out short gaps; controller logs are the timing source.
- Controller failure-to-authenticated-old-readback: **121.423s**, manual reconciliation **3.522s**. This run deliberately held recovery until23:54 to allow a two-minute human observation window, unlike the immediate HTTP recovery (**41.31s**, previously41.41s). These timings are separate scenarios, not a performance regression comparison.
- After recovery, browser saw [USD with its existing session](rf013-browser-2026-10-31/rf013b_2354_recovered_USD.jpg), then logged out/in and reopened Settings: [USD still persisted](rf013-browser-2026-10-31/rf013b_2354_relogin_USD.jpg). Controller snapshots also confirm candidate UZS → old UZS → old USD → recovered old USD. Both browser-currency flags are true in the raw evidence.

**Remaining coverage/decisions:** live visual observation of23:44, phone layout and RU/UZ are NOT COVERED. Bare503/no Retry during failed activation remains a Mirshoir decision; no fallback UI was added. The historical login React418 was recorded separately during startup. Independent rollback execution and human approval/production acceptance remain pending. No entire visual gate, independent/human gate, verified or accepted state is marked complete.

At the user's explicit request, the controller stopped only this run's six ownership-labelled containers at06:21:05 Seoul on1November. Images, database/storage volumes and evidence remain for inspection; no other stack or source was changed. Earlier results/failures above are retained.
