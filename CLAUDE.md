# Milana ERP

Read and follow [AGENTS.md](AGENTS.md) for repository instructions.
Read the [engineering workflow](docs/ENGINEERING_WORKFLOW.md) before implementation
or review: route -> dedicated service -> schema-model persistence, canonical
enum-typed contracts, and operation-level tests -> visual checks -> AI review -> human approval.
For refactoring, use /milana-refactor and read the canonical
[shared skill](.agents/skills/milana-refactor/SKILL.md).
The [team plan](docs/REFACTOR_PLAN.md) records decisions and ownership.
Load only the folder guides and evidence relevant to the assigned operation.

For a new or extended feature, use /milana-feature and read the canonical
[feature skill](.agents/skills/milana-feature/SKILL.md). Assign the engineer/reviewer
from [team ownership](docs/TEAM_OWNERSHIP.md). See [shared skills](docs/AGENT_SKILLS.md).
