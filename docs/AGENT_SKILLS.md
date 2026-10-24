# Shared skills for the team

These skills are repository files. Pull the latest clone_main and open an agent
session in that checkout. No personal skill copy is required. If a running session
does not list a new skill, reopen it or explicitly ask it to read the path below.

| Work | Codex | Claude Code | Shared instructions |
| --- | --- | --- | --- |
| Refactor existing behavior | $milana-refactor | /milana-refactor | [.agents/skills/milana-refactor/SKILL.md](../.agents/skills/milana-refactor/SKILL.md) |
| Add or extend a feature | $milana-feature | /milana-feature | [.agents/skills/milana-feature/SKILL.md](../.agents/skills/milana-feature/SKILL.md) |

Codex entries are in .agents/skills/; Claude entries in .claude/skills/ forward to
the same canonical instructions. AGENTS.md and CLAUDE.md direct agents to use them.
Any other agent can read those Markdown files explicitly. Skill discovery does not
prove compliance: inspect the diff, tests, review and acceptance evidence.

For a task, include: business group, engineer, reviewer, desired outcome, affected
workflow and whether this is planning or approved implementation. Example:

> Use $milana-feature for the approved purchasing change. Owner Ismail; reviewer
> Mirshoir. Read the purchasing guide, trace the receiving operation and its stock
> handoff, then implement only the recorded acceptance cases and verify both flows.

Use [team ownership](TEAM_OWNERSHIP.md) for exact allocations and
[the backend guide](../backend/app/README.md) for current versus target folders.
The schema/DTO migration is planned; reading these skills does not mean it happened.

## Verification after each change

Follow [the shared verification gates](VERIFICATION.md) for every completed runtime migration,
bug fix and feature: validate AI-written tests, run relevant automated checks,
visually exercise actual end-to-end behavior, then challenge it with bounded
stress and verify data integrity/recovery. Record blocked checks honestly; they
do not count as passes. Documentation-only changes record runtime gates as not applicable.

## Implementation sessions

For the current refactor, MiniMax M3.1-Flash performs implementation. Use two
MiniMax sessions with up to three scoped subagents each (six total), when
supported, in separate work directories with disjoint file ownership. Report
the actual model, workers started, changed paths and checks run.

Codex orchestrates, integrates, independently reviews, visually tests E2E and
runs bounded stress. Human engineering/business review and release gates remain.
Observe model availability, capacity, speed and token cost per run; do not assume
free or unlimited access persists. Report blockers and recover/reassign within
MiniMax; do not silently substitute Codex for implementation.
