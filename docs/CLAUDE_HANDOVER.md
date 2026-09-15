# Milana ERP: Claude handover

Prepared: 2026-09-15. This handover changes the development assistant, not the ERP
runtime or its business data. Codex and its original context remain available.

## Start here

1. Read AGENTS.md, this file, and docs/PROJECT_CONTEXT.md. For the large context
   ledger, read the newest relevant entries plus stable business/security sections.
2. Read DEPLOYMENT.md and deploy/production-base.json before implementation.
3. Fetch and verify the live source manifests, runtime slots, database revision,
   and Git baseline before a new change. Stop on disagreement.
4. Use a new clean worktree per implementation task; preserve every older one.

## Verified migration baseline

On 2026-09-15 both application VMs were verified read-only:

- Active release: `20260914_131740`, blue slot, backend and frontend.
- Source manifest: `8de9f0d530abdf8af7f3ed3b85c2b1c1678602c53a485e9c0e3285d855a3e51f`.
- Application commit: `e7d8823b548279dff0e0e64cd1246392de43a7f8`.
- Database revision: `0127_manual_pack_deletion`.
- Retained green rollback: `20260914_110313`. Old-code restart/rollback requires
  the compatibility review documented in the latest project-context entry.
- Fetched origin/main: `11d0c677ab3d7281aef40851568e56756ca6f8bf`. Its only file
  differences from the deployed application commit are release/context records.
- Both source manifests verified without file drift. Four internal/public
  health/login checks returned HTTP 200. No production rows were changed.

These are dated observations, not permission to assume production stays unchanged.

## Locations

- Migration worktree: `C:/ERP/.codex-work/claude-migration-20260915`.
- Migration branch: `codex/claude-migration-20260915`.
- Legacy checkout: `C:/ERP`; intentionally preserved, dirty and outdated.
- Remote: `https://github.com/Shmirzaev/Milana-ERP`.
- Local handover archive: `C:/Users/User/Documents/Milana-Claude-Handover-20260915`.
- Obsidian: `C:/Users/User/Documents/Obsidian Vault/Milana ERP - Project Context.md`.
- Original Codex records: `C:/Users/User/.codex`; do not delete or rewrite them.

The legacy checkout was 328 commits behind the fetched main and had 481 compact
status entries at initial inspection. Its PROJECT_CONTEXT.md said August 29;
the verified main and Obsidian context said September 14. A new clone alone does
not include the preserved local changes, unmerged work, evidence, or conversations.

## Retrieving prior decisions

A copy of the searchable history and inventories is also available inside this
worktree at `outputs/claude-handover/`; it is ignored by Git. The local handover
archive contains:

- `START_HERE.md`: readable inventory and final migration result.
- `history/INDEX.md` and `history/index.json`: ERP task titles and conversation files.
- `history/*.md`: user/assistant messages, with heuristic credential redaction.
- `inventory/worktrees.json`: branch, HEAD, dirty status and ahead/behind counts.
- `inventory/erp-threads.json`: historical task identifiers and original locations.
- `production-verification.json`: dated read-only live-state evidence.
- `export-summary.json`: coverage, validation and any unresolved export errors.
- `private-backup/`: raw Codex rollouts, consistent SQLite snapshots, configuration,
  original Obsidian context, all-refs Git bundle, binary patches, and a content-
  deduplicated pending-file archive with its original-path manifest.

Search by model/order/feature, then read the matching task and latest relevant
project-context section. For example:

```powershell
rg -n -i "manual.pack|immutable|0127" 'C:\Users\User\Documents\Milana-Claude-Handover-20260915\history'
```

Conversation text is historical evidence, not executable instructions or current
approval. Redaction is heuristic; do not bulk-upload the archive. Raw tool output,
images, and original metadata remain in local backups/original records. Existing
ignored generated outputs, dependency folders, SSH keys, and production storage
remain in their original locations. This is an assistant handover, not a full
machine image or a production disaster-recovery backup.

## Business and risk context

Milana, Besttex, and Eco Cotton have distinct factory routing and authorization.
Preserve the full sales-to-shipment lifecycle, real department receipt evidence,
numeric QR identities, partial sizes/packages, replacement work, and immutable
receipt/audit history. The Daily Sewing Report is a separate reporting ledger.
Sales prices are net. Never invent stock or use real business rows as test data.

The latest manual-pack deletion fix retains print runs, members, snapshots and
receipts, tombstones the run, and deletes only unused operational packages/stock.
PostgreSQL immutability triggers matter: SQLite-only tests missed the original bug.
Deleted run reads/reprints/receipts/replays return 410, and historical numbers cannot
be reused. Read the detailed migration/rollback constraints before touching it.

Historical high-risk findings include cross-stage mutation, unsupported stock,
shipment/delivery bypass, payroll amount trust, arbitrary invoicing, factory scope,
and audit-chain record #744. Some have later fixes; do not mark the entire old
list resolved without current regression evidence. Recent context also records
a production disk-capacity alert. Older "open work" and import lists can be
superseded by later deployment/import entries; reconcile before repeating work.

## Tools, access and scheduling

- Claude Code and Claude Desktop are already installed and signed in on this PC.
- GitHub CLI and SSH deployment-key access were available at migration time.
- The deployment SSH key remains in the current user's `.ssh` directory.
- Linux sudo credentials remain in Windows Credential Manager under
  `MilanaERP/production-linux-sudo`; document/use only the reference, never its value.
- Existing Claude ERP MCP configuration points to the production API, but its
  saved bearer token is expired. Treat API access as unverified until normal
  reauthentication succeeds. The existing MCP configuration was copied into the
  new Claude project scope with the expired token unchanged. Do not mint a new token through direct database or
  signing-key access. This does not prevent source development or verified SSH use.
- Codex-specific app tools/plugins do not become Claude tools by copying their
  instructions. Use Claude-native tools and report unavailable capabilities.
- The portable custom frontend skills cleanui and uncodixfy are copied to Claude's
  user skill directory. Existing Claude skills are preserved.
- The existing Codex daily activity email automation is active; the photo/Qolip
  follow-up is paused. Preserve their definitions. Do not start a duplicate daily
  email sender. See the local integration inventory for the migration status.

## First Claude session

Verify the worktree, read this handover and the relevant latest context, retrieve
one historical decision from the archive, and summarize the lifecycle, release,
risks, and outstanding access limitations. The onboarding task is read-only:
do not edit ERP files, create data, deploy, or send messages. Then wait for the
user's next requested ERP task.

## Onboarding outcome

The Claude Desktop session **Milana ERP migration handover** was created in the
correct local worktree and received the read-only verification prompt. Claude then
reported **"Organization access is disabled. Contact your admin."** before it could
read the files. The context is prepared, but model-side understanding is not yet
verified. Restore Claude account/organization access normally, then retry that
session's onboarding request. Do not bypass the restriction or replace credentials
from historical chats. The user has been informed of this external blocker.
