# Backend architecture: start here

`Router -> models/*_service.py -> SQLAlchemy schema + Session -> PostgreSQL`

The models/ folder is the service layer: business rules, authorization and CRUD.
This follows Pizza House's models/*.service.ts convention. It replaces the former
services/ folder; it does not introduce a second business layer.

| Layer | Responsibility and guide |
| --- | --- |
| [api/routes](api/routes/README.md) | HTTP inputs/context, service call, response/error mapping. |
| [models](models/README.md) | Business operations in *_service.py and twelve business-group guides. Existing plain ORM mapping files remain here temporarily. |
| [libs/dto](libs/dto/README.md) | Target: feature-grouped Create/In, Update and Read/Out DTOs. |
| [schemas](schemas/README.md) | Target: database definitions. Currently Pydantic DTOs, which must migrate first. |
| [libs/enums](libs/enums/README.md) | Fixed vocabulary with unchanged serialized values. |
| [libs/types](libs/types/README.md) | Distinct internal contracts only where needed. |

Service files and imports have been relocated; their behavior is unchanged.
Business-group directories remain README-only. Some share names with current ORM
files; adding __init__.py would risk shadowing those mappings. Read the model guide
before turning a guide directory into a package. No new tables are implied.

Follow [study -> extract -> technical test -> visual test -> switch -> verify -> cleanup](models/README.md#migration-sequence).
Humans decide business behavior/interfaces; agents execute approved work. See the
[team plan](../../docs/REFACTOR_PLAN.md) and [complete source map](../../docs/REFACTOR_MAP.md).

DTOs validate inputs and shape outputs; business services perform operations.
First migrate current schemas/ DTOs and all callers/shims to libs/dto/. Then move
only the existing ORM mappings and registration from models/ to schemas/, preserving
one definition per table. Business services stay in models/. This separate future
migration is not part of the service-folder relocation.

For work allocation see [team ownership](../../docs/TEAM_OWNERSHIP.md).
For new features use $milana-feature (Codex) or /milana-feature (Claude Code);
for refactoring use milana-refactor. [Shared skills](../../docs/AGENT_SKILLS.md)
are committed in the repository so the team receives the same rules when pulling.
