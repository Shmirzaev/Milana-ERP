# Shared definitions: libs

**Coordination owner:** Ismail. **Reviewer:** Dilmurod.
Feature owners maintain their definitions. See [team ownership](../../../docs/TEAM_OWNERSHIP.md).

The owner chose libs/ as the shared home for DTOs, enums and internal types.

| Folder | Contents |
| --- | --- |
| [dto](dto/README.md) | Feature-grouped input, update and output contracts. |
| [enums](enums/README.md) | Fixed business values shared by schemas and services. |
| [types](types/README.md) | Internal contracts when they differ from API DTOs and ORM models. |

[dto/](dto/README.md) contains the existing Pydantic Create/In, Update and Read/Out
contracts. [schemas/](../schemas/README.md) contains SQLAlchemy database definitions.
[models/](../models/README.md) contains business services (*_service.py).
Keep these responsibilities separate when extending a feature.

## Making a file

1. Find an existing definition and its actual callers first.
2. Use a feature-named snake_case file, such as enums/production.py. Group related
   definitions; no file per enum member, table or endpoint.
3. Preserve stored/serialized values and public contracts. Read the child guide
   for enum or type conventions and coordinate with the feature owner.
4. Keep definitions independent of routers, service implementations and database
   sessions. No queries, commits, permission decisions or workflow orchestration here.
5. Update callers and relevant tests in the agreed incremental refactor. Follow
   [the migration sequence](../models/README.md#migration-sequence).

DTO, enum and internal-type packages contain contracts used by implemented
operations. Their presence does not establish system-wide adoption: track each
operation's actual producers, consumers and remaining coverage. Add definitions
only for an approved operation that uses them. Keep assets in their existing home
and avoid turning libs into a general-purpose miscellaneous folder.
