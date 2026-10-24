# Shared definitions: libs

**Coordination owner:** Ismail. **Reviewer:** Dilmurod.
Feature owners maintain their definitions. See [team ownership](../../../docs/TEAM_OWNERSHIP.md).

The owner chose libs/ as the shared home for DTOs, enums and internal types.

| Folder | Contents |
| --- | --- |
| [dto](dto/README.md) | Feature-grouped input, update and output contracts. |
| [enums](enums/README.md) | Fixed business values shared by schemas and services. |
| [types](types/README.md) | Internal contracts when they differ from API DTOs and ORM models. |

[dto/](dto/README.md) is the target home for Pydantic Create/In, Update and Read/Out
DTOs. Migrate existing [schemas/](../schemas/README.md) definitions with their callers. [models/](../models/README.md) currently contains SQLAlchemy database
schema models; they move to [schemas/](../schemas/README.md) only after the old
DTO namespace and its callers/shims are fully retired. [services/](../services/README.md) contains business operations.
Schemas and models are separate responsibilities, not additional service layers.

## Making a file

1. Find an existing definition and its actual callers first.
2. Use a feature-named snake_case file, such as enums/production.py. Group related
   definitions; no file per enum member, table or endpoint.
3. Preserve stored/serialized values and public contracts. Read the child guide
   for enum or type conventions and coordinate with the feature owner.
4. Keep definitions independent of routers, service implementations and database
   sessions. No queries, commits, permission decisions or workflow orchestration here.
5. Update callers and relevant tests in the agreed incremental refactor. Follow
   [the migration sequence](../services/README.md#migration-sequence).

These folders contain documentation only for now. Add Python package files and
definitions with their approved callers, then verify imports. Keep assets in their
existing home and avoid turning libs into a general-purpose miscellaneous folder.
