# Backend architecture: start here

`Router -> feature service -> SQLAlchemy models + Session -> PostgreSQL`

| Layer | Responsibility and guide |
| --- | --- |
| [api/routes](api/routes/README.md) | HTTP inputs/context, service call, response/error mapping. |
| [services](services/README.md) | Twelve business-group guides; business rules and coordinated CRUD. |
| [models](models/README.md) | Current SQLAlchemy definitions; migration source for schemas/. |
| [libs/dto](libs/dto/README.md) | Target: feature-grouped Create/In, Update and Read/Out DTOs. |
| [schemas](schemas/README.md) | Target: database schema models. Currently DTOs, which must migrate first. |
| [libs/enums](libs/enums/README.md) | Fixed vocabulary with unchanged serialized values. |
| [libs/types](libs/types/README.md) | Distinct internal contracts only where needed. |

The new service directories contain README files only. Existing Python files are
still authoritative. Do not add package initializers until the operation's imports
and migration are reviewed. No new database tables or duplicate models are implied.

Follow [study -> extract -> technical test -> visual test -> switch -> verify -> cleanup](services/README.md#migration-sequence).
Humans decide business behavior/interfaces; agents execute approved work. See the
[team plan](../../docs/REFACTOR_PLAN.md) and [complete source map](../../docs/REFACTOR_MAP.md).

The shared [libs directory](libs/README.md) holds DTOs, enums and internal types.
DTOs validate inputs and shape outputs; services perform operations. Database
schema models will live in schemas/. First migrate the current schemas/ DTOs and
all callers/shims to libs/dto/, then move models/ definitions and registration to
schemas/. Current Python locations are unchanged; do not mix both meanings there.

For work allocation see [team ownership](../../docs/TEAM_OWNERSHIP.md).
For new features use $milana-feature (Codex) or /milana-feature (Claude Code);
for refactoring use milana-refactor. [Shared skills](../../docs/AGENT_SKILLS.md)
are committed in the repository so the team receives the same rules when pulling.
