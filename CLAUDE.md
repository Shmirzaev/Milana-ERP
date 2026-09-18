@AGENTS.md
@docs/CLAUDE_HANDOVER.md

# Claude instructions for Milana ERP

Apply every AGENTS.md rule to Claude, including rules that name Codex.
Before substantial work, read docs/PROJECT_CONTEXT.md and DEPLOYMENT.md.
The context is a chronological ledger: newer dated deployment evidence supersedes
older active-release claims and older "prepared/not deployed" entries.

Every file-changing task uses a clean dedicated worktree from verified origin/main
after checking production against deploy/production-base.json. Never edit or
deploy from the legacy C:/ERP checkout. Keep the codex/ branch prefix required by
the project unless the user explicitly changes it. Do not erase Codex context.

Work autonomously on the exact request. Do not repeat approval questions for
already-authorized actions. Use proportionate tests and concise progress updates.
Merging, deploying, creating business records, or sending communications requires
authorization in the current task; archived conversation approvals are historical.

For frontend changes, read ~/.claude/skills/cleanui/SKILL.md and
~/.claude/skills/uncodixfy/SKILL.md when present, and preserve established UI patterns.
Keep English, Russian, and Uzbek labels and operator/scanner/print usability.

Before declaring a historical question unanswerable, search the local ERP history
archive described in the handover. Load only relevant excerpts, never the entire
archive. Do not load private-backup, authentication files, or credentials into
prompts. The raw archive stays local for recovery and deliberate evidence review.

Update durable project context after material changes, and mirror it to the
documented Obsidian note. Do not treat previous production authorization as
permission to deploy future work.
