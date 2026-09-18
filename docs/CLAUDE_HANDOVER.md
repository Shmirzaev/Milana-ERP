# Milana ERP: Claude handover

Updated: 2026-09-18. This handover changes the development assistant. It does
not deploy ERP code or change business data. Codex context remains intact.

## Start here

1. Read CLAUDE.md, AGENTS.md, and the newest relevant entries and stable rules
   in docs/PROJECT_CONTEXT.md. Newer deployment records supersede older states.
2. Read DEPLOYMENT.md and deploy/production-base.json before implementation.
3. Fetch and reconcile live manifests/slots, database revision, and Git baseline
   before each new change. Stop on disagreement.
4. Use a new clean worktree for each file-changing task; preserve older work.

## Verified baseline on September 18

- Backend/frontend active: `20260917_100146`, blue slot.
- Running rollback: `20260917_091524`, green slot.
- Manifest: `abaae224fd198919a02b0fb1ee01b2780809da79123c2132f0d100762a29a94e`.
- Application commit: `9c3b7a3169b4ac9406915c79fc4f56a92a5a5edc`.
- Database revision: `0131_sewing_corrections`.
- Fetched main: `80f4831e8b9e514f1a3ee16558ad45a782e0e29a`; differences from
  the application commit are only production-baseline and context records.
- Both source manifests verified without drift. All four internal/public
  health/login checks returned HTTP 200. No production rows changed.

These are dated observations. Reverify before making a new change.

## Locations

- Current migration worktree: `C:/ERP/.codex-work/claude-migration-20260918`.
- Branch: `codex/claude-migration-20260918` (documentation only; not merged).
- Legacy checkout: `C:/ERP`; preserved, dirty, and not a release source.
- Remote: `https://github.com/Shmirzaev/Milana-ERP`.
- Current archive: `C:/Users/User/Documents/Milana-Claude-Handover-20260918`.
- Base archive: `C:/Users/User/Documents/Milana-Claude-Handover-20260915`.
- Original Codex records: `C:/Users/User/.codex` (preserved in place).
- Obsidian: `C:/Users/User/Documents/Obsidian Vault/Milana ERP - Project Context.md`.

Keep BOTH dated archives. September 18 is an incremental backup referencing
September 15's raw rollouts and pending-file content. The September 18 searchable
history is a complete refreshed index, not only the new conversations. The old
migration branch/worktree also remains; it is not the current code baseline.

## Latest business changes to understand

- Sewing line assigned/available work displays existing model and variant
  numbers separately. Base models keep an empty variant; batch reads are reused.
- Sewing Input/Sewn/Passed corrections are guarded, version-checked and audited.
  The user's Edit/Delete request concerned Sewing, not Daily Sewing Reports.
- Sewing receipt is batch-scoped. Read the September 17 receipt correction and
  PO-0182 records before touching batch receipt or repeating any data correction.
- QR Control groups collapse per order and use white/yellow/green scan states.
- Milana Fabric to Eco Cotton tracks exact roll custody, dispatch and return
  history, weights/counts and PDFs. It does not create Eco inventory/production.
  Dispatch PDFs now show sent items only; stored snapshots remain immutable.
- Shared form borders are 2px; Fabric Archive exposes Arrival date separately.
- User access has a full 78-key catalog and compact effective-access checkboxes.
  Checking writes explicit allow; unchecking writes deny, including inherited
  access. Factory scoping and primary-factory Super Admin guards remain.
- Manual-package deletion preserves immutable print/member/receipt history and
  tombstones the run. Do not recreate deleted test shipments or operational stock.

The context ledger contains exact tests, releases, data corrections and rollback
constraints. Some September 17 deployments intentionally omitted extended
observation at the user's explicit request. Do not claim those checks ran, and
do not treat historical exceptions as authorization for a new deployment.

## Retrieving prior decisions

The ignored `outputs/claude-handover/` folder in this worktree contains a local
copy of searchable history, inventories and current evidence. The external
archive also provides:

- `START_HERE.md`: entry point and completion/access status.
- `history/INDEX.md`, `history/index.json`, `history/*.md`: ERP task messages.
- `inventory/worktrees.json`: preserved branches, commits, status and locations.
- `inventory/erp-threads.json`: original task IDs and directories.
- `production-verification.json`: dated read-only live-state evidence.
- `export-summary.json`: backup coverage, integrity checks and limitations.
- `private-backup/`: raw rollout delta, SQLite snapshots, configuration, Git
  bundle, binary patches and pending-file delta. Manifests reference both dates.

Search by feature/order/model, then read selected matching tasks and newer context:

```powershell
rg -n -i "manual.pack|Eco Cotton|batch.only|sewing correction" outputs/claude-handover/history
```

Conversation messages use heuristic credential redaction. Historical requests
are evidence, not new instructions or approvals. Never bulk-load the archive,
private backups, credentials, environment values or authentication files into
prompts. Tool output and media remain in private backups/original records.
Ignored generated files/dependencies and production data remain in place.
This is not a full machine image or a production disaster-recovery backup.

## Business rules and unresolved risks

Preserve the full sales-to-shipment lifecycle, factory authorization boundaries,
real receipt evidence, numeric QR identities, partial sizes/packages, replacement
work and immutable audit history. Daily Sewing Reports are a separate ledger.
Prices are net. Never invent stock or use production business rows as test data.

Historical high-risk findings include cross-stage mutation, unsupported stock,
shipment/delivery bypass, payroll amount trust, arbitrary invoicing, factory
scope and audit-chain record #744. Some have later fixes; require current
regression evidence before declaring any risk resolved. September 17 disk was
73% backend / 65% frontend. Read deployment capacity and rollback rules.

## Access, tools and scheduling

- Claude Desktop access was restored by the user on September 18. The session
  **Milana ERP migration refresh** successfully read this worktree and the archive,
  fetched GitHub, and completed the read-only acceptance below. The standalone
  CLI still reports logged out; it requires a separate normal sign-in.
- GitHub fetch and production SSH read-only access worked during this refresh.
- Existing SSH keys remain under the current user's `.ssh` directory. Linux
  sudo uses Windows Credential Manager reference `MilanaERP/production-linux-sudo`.
  Never print or copy its value into context.
- Existing ERP MCP configuration uses the production API. Claude's September 18
  read-only `erp_me` probe returned HTTP 401. Treat it as unavailable until normal
  reauthentication and a read-only check succeed. Never mint a token by reading
  signing keys or editing the database. Source development does not need this API.
- Portable `cleanui` and `uncodixfy` skills are installed in `~/.claude/skills`.
  Existing Claude skills remain. Codex-specific runtime tools/plugins are not
  automatically portable; report capability gaps honestly.
- The existing Codex daily activity email remains the sole active sender. The
  photo/Qolip follow-up remains paused. Definitions are preserved. Scheduled
  jobs have NOT moved to Claude; validate a replacement before switching, and
  never create overlapping email senders or send a test email without permission.

## Read-only onboarding acceptance

Verify this worktree and the latest baseline, read the required documents, and
retrieve one historical decision (including its task ID) from the archive.
Summarize the lifecycle, current release/schema, latest changes, unresolved
risks and access/scheduling gaps. Do not edit, merge, deploy, create data, send
communications or change automations. Then wait for the user's next ERP task.

Acceptance passed in Claude Desktop session `c16b489d-5c7e-4e1f-8863-345877b7e617`,
**Milana ERP migration refresh**. Claude opened the required documents and evidence,
confirmed the current release/schema, explained the September 16-17 changes and
retrieved the receipt correction from task `01a0adb9-a80b-7f40-a5a2-d48430078394`
and manual-pack fix from task `01a09e9c-2b3f-7001-ba65-446123c73d64`. It correctly
distinguished dated production evidence from a new live probe. Git fetch worked;
the worktree remained clean. The response is saved in the external archive as
`CLAUDE_ACCEPTANCE.md`.

The source/context handover is verified and Claude Desktop is ready for ERP work.
Full integration parity remains incomplete: standalone CLI login, ERP MCP login,
and the daily email schedule have not moved. Keep Codex available for its existing
automation until a verified replacement is ready; do not duplicate the sender.
