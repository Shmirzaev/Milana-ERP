# Shavkat acceptance environment and server answers — 4 November 2026

## Scope and source

The owner requested execution of the supplied `For_Shavkat.md` and
`seed_acceptance.py` handoff, following a read-only review. After the initial
drift stop, the owner explicitly approved **verified live commit `11f80a29`** as
the acceptance baseline instead of stale `origin/main`. No application feature,
production release, credential rotation or production-data write was authorized
or performed by this task.

- Worktree: `C:\ERP\.codex-work\acceptance-shavkat-20261104`.
- Branch: `codex/acceptance-shavkat-20261104`, starting at
  `11f80a2995daeeb90b5c01318aec9e9c6a40f1c9`.
- Both live hosts: blue `20261103_094602`; retained running rollback green
  `20261103_112256`.
- Both source manifests:
  `ee765f999e782193878390897873c7b5865749460d4d776cf321fcd28490f8a9`.
- Production and isolated test schema: `0150_package_customer_release`.
- The fetched `origin/clone_main` production-base record matches the verified
  hosts; `origin/main` and the legacy checkout are stale and were preserved.

## Ready for factory acceptance

- Test site: <http://172.16.10.5.sslip.io:18180>.
- Captured test inbox: <http://172.16.10.4:18125>.
- The existing credentials in the supplied handout work; they are not reproduced
  in this report or committed to this branch.
- Updated handout: local worktree `acceptance/For_Shavkat.md`. Only the two URL
  placeholder strings were replaced, everywhere they occurred. Original Downloads
  files were preserved. The fixed historical fixture baseline in the handout
  remains unchanged; the actual current runtime baseline is recorded above.
- Original seed script SHA-256, unchanged locally and on the test backend:
  `51bd8943fb4c0cebb26108f950c5421cb6ea1ab47e798dd2842935e611548862`.

The test hostname resolves to the existing private frontend VM; it uses sslip.io
wildcard DNS. It does not create a public deployment or change corporate DNS.
Access was confirmed from the owner's connected workstation and browser. Each
operator still needs to confirm access from their own factory workstation/tablet.
The site and inbox are private HTTP test services containing synthetic data only.
Camera scanning may require a secure browser origin; the handout permits typing
the test codes. No production data or real credentials should be entered here.

## Isolation and resources

The exact live backend and frontend images were reused, without rebuilding or
editing release source, retained images, live containers, routers or symlinks:

- Backend image:
  `sha256:f7467a79c4b513cc62d11b5106161f21430cf1e1e4bde739949e5bbcecbfa655`.
- Frontend image:
  `sha256:3fabcc509df640f0a183b065d58839a9ef61d73b36c8e4e189c5c825828e4a2a`.
- Backend host lab root:
  `/app/storage/acceptance-shavkat-20261104-r2`.
- Frontend host lab root:
  `/opt/milana-erp/acceptance/shavkat-20261104`.
- Backend container prefix: `acceptance-shavkat-20261104-r2-` for `db`, `mail`,
  `backend`, `gateway`. Frontend prefix: `acceptance-shavkat-20261104-` for
  `frontend`, `gateway`. All are labeled `milana.acceptance=shavkat-20261104`.
- New standalone PostgreSQL cluster and database `acceptance_shavkat_20261104`;
  no production database/storage/configuration was copied or mounted.
- Fresh test database/JWT/file-signing secrets were generated on the backend
  host. Files are mode 0600. Comparison confirmed all differ from production.
- No Resend, real SMTP credentials, attendance integration, Redis or production
  shared-store configuration is inherited. Mailpit is a capture sink.
- Application/database/mail containers use an internal Docker network; only the
  test gateways bridge to the private LAN. Test frontend also uses an internal
  network. Backend probes to production PostgreSQL `172.16.10.3:5432`, production
  API `172.16.10.4:8000`, and external `1.1.1.1:443` were blocked.
- Limits: PostgreSQL 384 MiB/0.5 CPU, mail 128 MiB/0.25 CPU, backend 896 MiB/1 CPU,
  frontend 512 MiB/0.75 CPU, gateways 64 MiB/0.25 CPU each. Auto-restart is enabled.
  No cleanup schedule or future automation was created.

The production image's frontend CSP upgrades HTTP assets to HTTPS. The isolated
HTTP gateway therefore removes that transport-upgrade directive and HSTS and
restricts `connect-src` to the test origin, while preserving the upstream nonce
and remaining directives. This is test-gateway configuration only. It is not
evidence that production TLS/CSP security checks in Part B passed.

Attempt 1 was refused before seeding because the supplied guard rejects the raw
production frontend host IP even with a separate port. The script was not weakened.
Attempt 2 used the distinct test hostname, a fresh cluster/storage and unchanged
script. The exact stopped attempt-1 containers, empty networks and task directory
were inspected and discarded; only the successful r2 backend lab remains.

## Verification and data touched

- Fresh isolated migrations 0001 through 0150 passed. No production migration ran.
- Seed self-check passed: 12 fixed accounts/logins, expected badge/label codes,
  manager selection, period dates, split/returned earnings, pagination positions,
  print fixtures and first-click shortage prerequisites.
- Isolated counts: 502 employees (501 MIL plus one ECO control), 12 users,
  414 payroll records including history/voided records, 401 adjustments,
  6 packages, 2 sales orders, 1 seed-check task and 0 stock reservations.
- Alice is at position 501; `ACCEPTANCE-HISTORY-0001` is at position 404.
- HTTP checks passed for all 12 actual login/cookie sessions, site version v4.2.1,
  `/health`, `/ready`, employee pagination, test CSP/marker, and scanner refusal
  from user administration. Evidence:
  [HTTP checks](acceptance-shavkat-20261104/http-verification.json).
- The browser successfully signed in as HR, opened HR Employees and found Alice
  by 910001 without modifying her profile. The inbox visibly contained two
  captured password-reset emails pointing to the isolated test origin.
  [Browser evidence](acceptance-shavkat-20261104/hr-smoke.png).
- A preliminary smoke assertion incorrectly expected all employee-picker reads
  to be forbidden to scanners. Source inspection confirmed authenticated picker
  access is intentional, with private-field filtering. The assertion was replaced
  with the actual administration boundary (`/api/users` returns 403); this was a
  test-assumption correction, not a production/application fix.
- Both production manifests validated. After setup, both live/rollback containers
  remained running with zero restarts/OOM; both routers remained active. All four
  required internal/public health/login checks returned HTTP 200.
- Production access was read-only: release/image/host metadata, whitelisted
  configuration, targeted employee/audit rows, PostgreSQL protection/role metadata,
  and listing/hash verification of one existing backup. No production business
  data, passwords, secrets, services, migrations or traffic routing were changed.

The initial setup left the A1–A19 human results table unfilled. The owner then
requested agent execution; see [the check results](ACCEPTANCE_CHECK_RESULTS_2026-11-04.md)
for individual coverage, two checklist gaps and remaining screen/print limits.
A16's first-click fixture has now been consumed and A17 completed through fresh
captured test emails. The original handout remains preserved. Part B tests were
not rerun or relabeled as passed.

## A4 production readback

Read-only audit entries 144572 and 144573 point to:

| Audit | Employee | Current manager |
| --- | --- | --- |
| 144572 | Akbaraliyeva Muslima | Akbarova Dilafruz, 321 |
| 144573 | Alixonova Yodgoraxon Durbek qizi | Akbarova Dilafruz, 321 |

Both audit transitions are manager row 129 to row 313. Employee-number lookups
must be factory-scoped: numbers 321 and 503 also exist in another factory.
The two Milana Dilafruz identities must remain separate. This task performed
database readback only; the human live-card/history check remains pending.

## Part C answers and remaining owner input

| Question | Verified answer or remaining information |
| --- | --- |
| 1 JWT algorithm | Exact requested command output: `JWT_ALGORITHM=HS256`. No signing key was read out. |
| 2 VM placement / .100 | Backend/frontend hosts are reachable at the documented addresses. Proxmox VM placement and identity of .100 require Shavkat. |
| 3 PBS placement | Physical placement and independence of .101 / backup-17tb require Shavkat/PBS access. |
| 4 Disks / RAID / cache | Backend `/app/storage` is ext4 on `/dev/vdb1`; local dump directory is on root LVM. Physical disk/controller/cache protection and hypervisor datastore mapping remain unknown. |
| 5 Failure domains | Shared chassis, power, UPS, cooling, building and uplink require physical inventory. |
| 6 Backup success / verification / space | Latest inspected local dump: `milana_erp_pre_bst_assignable_20261104_063301.dump`, 111,682,320 bytes, written 11:33:21 Tashkent on 4 November. `pg_restore --list` succeeded with 1,251 TOC entries. SHA-256 `245525159e41e76e0a06a3e5308ac9c79bb8cdc8060bf73bece4e405471484b8`. This is an archive-list check, not a restore drill or PBS verification. Backend root has about 39 GiB free, storage volume 457 GiB, frontend root 16 GiB. PBS space, backup/sync jobs and alert recipients require Shavkat. No ERP backup timer appeared in the inspected backend systemd timer list; cron/PBS schedules were not fully inspected. |
| 7 Encryption / keys / off-site copy | PBS encryption, independently stored recovery keys and offline/off-site copies are unverified. |
| 8 Independent database protection | Current PostgreSQL `archive_mode=off`; connected replication count 0. This does not prove absence of every external backup mechanism. |
| 9 Files / releases / config backup coverage | Configured upload/QR, model, sales-order, attendance-photo and HR-document directories are under `/app/storage`. Source releases are `/opt/milana-erp/releases`; local dumps are `/opt/milana-erp/shared/backups`. Inclusion in PBS and matching snapshots remains unverified. |
| 10 Oldest restorable point / pairing | Not established by a dump listing. Requires an actual restore chain and matching file/config evidence. |
| 11 Restore destination / owner | Requires Shavkat to identify a surviving machine, storage, network and restore operator. |
| 12 Rollback procedure | Current verified rollback is green `20261103_112256`, not the older blue described by the handout. Do not apply the old warning/procedure blindly. Use current release evidence and DEPLOYMENT.md; no rollback was attempted. |
| 13 DNS / TLS owner | Registrar, DNS and certificate-renewal owners require Shavkat. No DNS or TLS configuration was changed. |
| 14 Emergency access | Proxmox/PBS access independent of firewall/NPM/DNS remains unverified. |
| 15 Attendance Windows connector | Machine, scheduled task, run identity and checkpoint backup require the connector owner. |
| 16 Vault / rotation owners | Business must name the vault owner and backup person and identify the approved vault. No credential rotation was performed. |
| 17 Counter store | SQLite at `/app/storage/shared_store.sqlite3`, not Redis. Tomarix has a separate running Redis container; ERP does not currently point to it. |
| 18 Env consumers / startup seed | Both actual live/rollback backend slots retain database/global-attendance configuration and have startup seed false. Three older stopped containers retain seed true: `milana-backend-green-prequiesce-20260909_082533`, `milana-backend`, `milana-backend-prev-20260827_071634`. They require inventory/retirement or startup controls before rotation; none was restarted or changed. Kept scripts/jobs/env consumers still need a complete inventory. |
| 19 Attendance token / device login | A global attendance token is configured in both running backend slots. Connector-specific usage, per-device tokens and hardware credential reuse were not established. |
| 20 Email sender / mailbox control | Effective live settings have neither Resend nor SMTP configured. Mailbox/provider ownership and any external delivery setup require Shavkat. The acceptance inbox is entirely separate. |
| 21 Shared database roles | All listed roles except `ps_app` exist and can log in. Owners observed: catalog→catalog_user, catalog2→catalog2_user, leadlens→leadlens, milanaweb→milanaweb, kotiba→postgres, an older kotiba database→kotiba; ERP is owned by erp. Authentication method, all application consumers and password reuse were not checked; no passwords were queried. |
| 22 Infrastructure credential ownership | SSH/sudo access for this task uses the existing saved credential reference. Owners of VPN, firewall, NPM, Proxmox/PBS, encryption, DNS/ACME, registry and MFA recovery remain to be named. Do not send credential values. |
| 23 Exposed copies | Existing production env and local dump locations are known; locations of exposed handover copies and old secret-bearing backups require owner inventory. Secret values and old chats were not searched or copied. |
| 24 Rotation window | Owner must choose a quiet window and affected-user communication plan. Signing-key rotation logs users out. No rotation has started. |

## What is needed next

1. Review the [agent check results](ACCEPTANCE_CHECK_RESULTS_2026-11-04.md).
   Operator sign-off, A4 live-card/history and A14 native print-dialog evidence
   remain distinct from the completed browser/API/DB checks. Do not repeat the
   consumed A16 first-click fixture without a fresh disposable seed.
2. Shavkat or the infrastructure owner supplies the unknown physical/PBS/recovery,
   access/vault/credential-ownership and connector details in Part C. Names, IDs,
   locations and a rotation window only; no passwords, tokens or private keys.
3. Keep the test environment synthetic. It is on the existing application VMs,
   with resource caps; it is an acceptance lab, not an independent recovery host.
   Root disks remain near the existing alert/stop thresholds (rounded backend
   80%, frontend 79%). No release pruning or production cleanup was performed.
4. Part B still contains pending #358/#359 and PERF37 approval, despite its heading.
   Those claims need their owners' evidence before acceptance.

No production deployment or source merge occurred. The branch records only
sanitized task documentation/evidence; original credential-bearing handout/seed
copies and task-local administrative helpers are not pushed.
