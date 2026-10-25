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
The schema/DTO namespace migration is implemented. The six Ismail service groups
are implemented in draft PR #308; other group extractions follow their own approval.
Read [the current context](PROJECT_CONTEXT.md) before assuming production activation.

## Verification after each change

Follow [the shared verification gates](VERIFICATION.md) for every completed runtime migration,
bug fix and feature: validate AI-written tests, run relevant automated checks,
visually exercise actual end-to-end behavior, then challenge it with bounded
stress and verify data integrity/recovery. Record blocked checks honestly; they
do not count as passes. Documentation-only changes record runtime gates as not applicable.

## Implementation sessions

MiniMax M3.1-Flash performs implementation; Codex orchestrates, integrates,
independently reviews and tests visually. Run two MiniMax sessions and
request up to three scoped subagents per session (six total) when the runtime
supports it, with separate work directories and disjoint file ownership. A
session reports its actual model, the workers it started, the changed paths
and the checks it ran.

Codex owns integration, independent review, visual E2E and bounded stress;
human engineering and business review, and the deployment gates in
[DEPLOYMENT.md](../DEPLOYMENT.md), remain. Session capacity, speed and token
cost (free or unlimited tokens) are not permanently verified facts; observe
them per run. If MiniMax is unavailable or a worker is stuck, report the
blocker and recover or reassign inside MiniMax. Do not silently substitute
Codex for implementation.

The owner authorized all six Ismail areas—catalog, purchasing, sales, inventory,
planning and finance—as parallel candidate work. This authorization covers
implementation and review in isolated work directories. Human review,
production acceptance and release gates remain separate.
