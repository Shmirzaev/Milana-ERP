# Milana ERP documentation

Start with the document for your task. Do not load the full history into an agent session.

| Need | Read |
| --- | --- |
| Current decisions and release pointers | [Project context](PROJECT_CONTEXT.md) |
| Required layer responsibilities and work sequence | [Engineering workflow](ENGINEERING_WORKFLOW.md) |
| My refactoring tasks | [Refactor plan](REFACTOR_PLAN.md), [team ownership](TEAM_OWNERSHIP.md) |
| Folder purpose and current/target structure | [Backend guide](../backend/app/README.md), [source map](REFACTOR_MAP.md) |
| AI-assisted implementation | [Shared skills](AGENT_SKILLS.md) |
| Testing, visual checks, stress and review | [Verification](VERIFICATION.md) |
| Production deployment | [DEPLOYMENT.md](../DEPLOYMENT.md) |
| System topology and trust boundaries | [Architecture](ARCHITECTURE.md) |
| Retry and duplicate-write behavior | [Idempotency](idempotency.md) |
| Security and recovery | [Security runbook](SECURITY_RUNBOOK.md), [disaster recovery](DISASTER_RECOVERY.md), [capacity](OPERATIONS_CAPACITY.md) |
| Actual bugs | [Active bugs](../bugs/bugs.md), [verified finished bugs](../bugs/finished_bugs.md) |
| Employee manuals | [Training library](training/README.md) |
| Historical releases/reconciliations | [Archive](archive/README.md) |

Keep current instructions here; dated reports go in archive/. Training sources and
translations remain under training/; their generators live in scripts/training/.
Keep adrs/ decisions and audit-evidence/ records. In particular,
audit-evidence/fresh-migration-schema-drift.json is consumed by a regression test.
An old date does not make a recovery record, decision, fixture or runtime data disposable.

DEVELOPER_GUIDE.md and CODE_REVIEW.md were retired: use the backend/skill guides
and VERIFICATION.md instead. Their old versions remain in Git history. This avoids
conflicting instructions to add route writes or production startup schema patches.
