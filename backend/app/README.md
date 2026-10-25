# Backend architecture: start here

`HTTP router -> business service -> SQLAlchemy schema + Session -> PostgreSQL`

| Folder | Job |
| --- | --- |
| [api/routes](api/routes/README.md) | HTTP input/context, service call, response/error mapping. |
| [models](models/README.md) | Business services: rules, permissions, queries and coordinated writes. |
| [schemas](schemas/README.md) | SQLAlchemy database definitions, relationships, constraints and defaults. |
| [libs/dto](libs/dto/README.md) | Pydantic create/update/read and action contracts. |
| [libs/enums](libs/enums/README.md) | Fixed vocabulary with unchanged serialized values. |
| [libs/types](libs/types/README.md) | Distinct internal contracts only where needed. |

This follows the mentor's separation: Pizza House's models/ means business services;
its schema models correspond to our SQLAlchemy definitions in schemas/. DTOs validate
and describe data; the service uses mapped classes and a Session to perform CRUD.

The candidate implements business services in models/catalog/, purchasing/, sales/,
inventory/, planning/ and finance/. Shared existing helpers remain directly under
models/ when their current callers need them. The other group directories guide
their owners' later extractions. Database definitions and DTOs live in business-group
packages. Mixed legacy operations outside this batch still need their own review.
The current source map is in docs/REFACTOR_MAP.md; source extraction is separate
from production acceptance. No table or field redesign was made.

For a new feature: find its owner and existing operation, reuse its DTO/database
definition, implement the business operation, then connect the HTTP handler.
Read only the affected group's guide. Do not create a second services/ tree or put
Pydantic contracts back in schemas/. Register new mappings in schemas/__init__.py.

Follow [study -> agree -> protect -> extract -> test -> visual check -> switch -> retire](models/README.md#migration-sequence).
Humans decide business rules/interfaces; AI implements the approved scope.
Use [the plan](../../docs/REFACTOR_PLAN.md), [source map](../../docs/REFACTOR_MAP.md),
[ownership](../../docs/TEAM_OWNERSHIP.md) and [shared skills](../../docs/AGENT_SKILLS.md).
Source publication does not establish production activation or acceptance.
