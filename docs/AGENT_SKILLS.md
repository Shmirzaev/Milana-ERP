# Shared skills for the team

These skills are repository files. Pull the latest clone_main and open an agent
session in that checkout. No personal skill copy is required. If a running session
does not list a new skill, reopen it or explicitly ask it to read the path below.
Engineering guidance was published on clone_main at b92ee8f without integrating
the runtime refactor. Later candidate application changes have separate evidence
and acceptance gates. Pulling rules or seeing a draft PR is not verification of
the checkout being tested; inspect its exact source and operation ledger.
Start with [AGENTS.md](../AGENTS.md) and the [engineering workflow](ENGINEERING_WORKFLOW.md).
For another AI tool, explicitly provide those paths and require it to state the
operation, layer responsibilities and evidence gates before implementation.

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
The schema/DTO namespace migration and six grouped-service extractions exist in
draft PR #308. Schema-owned writers and system-wide enum-typed contracts remain
unfinished; the folder structure is not completion evidence. Other domain work
retains its named owner and pending coverage.
Read [the current context](PROJECT_CONTEXT.md) before assuming production activation.

## Verification after each change

Follow [the shared verification gates](VERIFICATION.md) for every completed runtime migration,
bug fix and feature: validate AI-written tests, run relevant automated checks,
visually exercise actual end-to-end behavior, then challenge it with bounded
stress and verify data integrity/recovery. Record blocked checks honestly; they
do not count as passes. Documentation-only changes record runtime gates as not applicable.

## Implementation sessions

The current remaining refactor uses **Codex subagents**, explicitly requested by
Ismail on 26 October 2026. This supersedes the former MiniMax-only restriction for
this task; use [the execution agreement](../AGENTS.md#implementation-execution).
It grants no new MiniMax credit, paid-usage or release authorization. Preserve
existing worker checkouts and immutable evidence during the handoff.

Each worker receives the old-operation trace, named human owner/reviewer, exact
source, isolated checkout, allowed files, typed public seam and success/refusal
examples. Require its handoff to show mentor-reference-to-Milana call/type mappings,
all direct/indirect writers and enum/DTO/internal/frontend consumers. The reference
is separation and discipline, not permission to copy another product's policies.

One integrator reconciles overlapping files and freezes the combined revision.
A different agent independently challenges the implementation/tests. The actual
connected-browser visual checks, saved-data readback and applicable integrity,
recovery and concurrency checks still precede `AI_VERIFIED_AWAITING_HUMAN`.
Named human visual/technical approval remains separately pending.

The [whole-system ledger](REFACTOR_COVERAGE.md) includes all 13 discovered domains
and non-persisted contracts. Six-area pilots are incremental steps, not the scope
limit. Owners and public-interface decisions in [team ownership](TEAM_OWNERSHIP.md)
remain in force; record unresolved decisions without blocking independent work.
