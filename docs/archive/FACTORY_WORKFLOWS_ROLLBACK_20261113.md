# Owner rollback of factory workflows — 13 November 2026

Final state: **both hosts serve blue `20261111_115200`**, exact source
`46ddd5c7864f0a68bd9a3c884d835a2a5dbf9bfb`, manifest
`db9df64cbcf57e4ab93ac83ef677d7d394b07652a1a4cf3fe1815abc92adac28`.
The owner instructed **"return the last deployment there are bugs"** after saying
the Packaging change was missing overall, not only for one order. The request
supersedes earlier deployment authorization. The factory feature release is
withdrawn; this rollback does not claim those reported bugs were diagnosed/fixed.

The prior [deployment record](FACTORY_WORKFLOWS_RELEASE_20261113.md), original
failed paired measurements, owner exception and passing automated/public checks
are preserved as historical evidence. They are not human production acceptance.
Packaging diagnosis stopped when rollback was requested; no business record was
changed to make the new workflow appear functional.

## Restored runtime

Backend activated blue at **11:21:38.647020 UTC**, frontend at
**11:21:43.605890 UTC** (16:21 Tashkent). Both source symlinks were atomically
restored after activation. Actual containers were the retained, already-running
old application; no build, dependency install, image relabel or active-container
replacement occurred.

| Active role | Immutable image digest |
| --- | --- |
| Backend | `sha256:dd92999c50d53047168f2643610aafd25d6296976680567a5bcb41fa54d9aacf` |
| Frontend | `sha256:a2af00dc27bcdbca246c2a88fb9a058b2747b94d4dd047627bf71c90b082a6a8` |

Both inactive green containers still contain `20261113_094409` / sourcee5383f250,
manifest4696c973. Controller metadata calls this the rollback release, but it is
**withdrawn after user-reported bugs and is not a known-good fallback**. Do not
activate or redeploy it on the strength of the earlier approval. Keep its source,
images and evidence for investigation; any future release requires fresh owner
authorization and complete bug verification. Older052632 source/images remain
retained; this operation did not stage an extra standby or touch current traffic
after successful restoration.

## Backup and execution

Both deployment locks were exclusively held. Fresh source/manifest/container,
controller/environment/routing checks matched the verified state before mutation.
Git clone_main was fetched again and remained3053788f2e17bd5585bccf8cd4547a62cc297516.
Separate independent review verified exact CAS phase bodies before execution.

Fresh current-data backup:
`/opt/milana-erp/shared/backups/milana_erp_pre_owner_rollback_20261113_094409_20261113_112059.dump`.
Mode0600,123,661,339bytes,1,400 restore-list objects; dump SHA256
`5da6b689935d6d430784018c0ed64b2b7145a7835f93aa9512dee496b073d82d`.
Restore-list101,509bytes, SHA256
`608d36728eadcdfa8762be9e0176b30adb3061023939e9991114dc7898cd8002`.

Reviewed installed controller13a9e19d switched backend first, proved stable health
and readiness115200, then switched frontend. Independently reviewed atomic links
changed only `current`, with ending guards preserving containers/state/proxy.
Database stays at `0156_variant_price_workflow`: **no downgrade, dump restore,
schema change, business-data deletion or production fixture creation**. Business
activity since cutover is preserved. No observer/substitute monitor was started.

## Closing verification

Existing reviewed `check_runtime.py rollback --label owner-rollback-closing`
passed for both roles, and a different agent independently verified its reports:

- All four supported public/internal health/login endpoints returned200 and exact
  restored release where applicable; stable and slot readiness passed.
- Both source manifests, slot states, current links, immutable images/revisions,
  unchanged default commands and exact retained container IDs agree.
- Both frontends forward health to restored backend115200; routing matches state,
  HAProxy validates and both routers are active.
- Two strict-schema workers per backend, disabled seeding, zero restarts/OOM/log
  error markers, database headroom below80/100 and zero invalid indexes.
- Disk78.55% backend/78.08% frontend remains above70% alert and below80% stop.
  No source/image cleanup was introduced for rollback.

These are rollback health/identity checks, not a new feature/performance epoch or
proof of human acceptance. Connected Chrome inspection during the preceding
Packaging diagnosis failed in its control bridge; no successful fresh Chrome
visual inspection is claimed. The owner may need to refresh the open browser to
discard new-release assets held in memory.

Both owned locks were released after closing. Runtime source remains46ddd5c7;
later commits only record this state. Worktree:
`C:/ERP/.codex-work/factory-workflows-20261113`, branch
`codex/factory-workflows-20261113`, preserved and pushed without clone_main/main
merge. Legacy checkout remains untouched. Private phase/runtime/backup evidence
is under `outputs/factory-deploy/owner-rollback-*`. Current production-base,
project context and the isolated factory section of the Obsidian note were updated.
