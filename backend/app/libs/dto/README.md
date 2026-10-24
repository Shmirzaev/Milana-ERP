# DTOs: feature input, update and output contracts

**Coordination owner:** Ismail. **Reviewer:** Mirshoir.
Each feature owner migrates its callers and contract tests. See [team ownership](../../../../docs/TEAM_OWNERSHIP.md).

The owner chose libs/dto/<feature>/, following Meditech. This is the target home
for Pydantic data-transfer objects. The current app/schemas/ files remain active
until each contract and its callers are migrated. This directory contains only
documentation today; no DTO implementation or import was changed.

## The mentor's actual structure

Inspected local Meditech snapshot b4c646ce471efbf6fe984f3315bba366b197281a:

- [member.input.ts](https://github.com/Ismoiljon1101/meditech-nest/blob/b4c646ce471efbf6fe984f3315bba366b197281a/apps/nestar-api/src/libs/dto/member/member.input.ts): MemberInput, LoginInput and inquiry inputs; GraphQL InputType/Field and class-validator decorators.
- [member.update.ts](https://github.com/Ismoiljon1101/meditech-nest/blob/b4c646ce471efbf6fe984f3315bba366b197281a/apps/nestar-api/src/libs/dto/member/member.update.ts): a separate MemberUpdate with optional editable fields.
- [member.ts](https://github.com/Ismoiljon1101/meditech-nest/blob/b4c646ce471efbf6fe984f3315bba366b197281a/apps/nestar-api/src/libs/dto/member/member.ts): GraphQL ObjectType output definitions, including Member and Members.
- [Member.model.ts](https://github.com/Ismoiljon1101/meditech-nest/blob/b4c646ce471efbf6fe984f3315bba366b197281a/apps/nestar-api/src/schemas/Member.model.ts): the separate Mongoose database schema, with defaults, indexes and persistence fields.
- [member.service.ts](https://github.com/Ismoiljon1101/meditech-nest/blob/b4c646ce471efbf6fe984f3315bba366b197281a/apps/nestar-api/src/components/member/member.service.ts): accepts DTOs and calls the injected Mongoose model for create/update/query.

The resolver also imports DTOs. They describe data at the boundary; they are not
an extra execution layer between service and database. Meditech's schemas/ means
database schemas; Milana's current schemas/ means Pydantic contracts. This naming
difference does not make DTOs and persistence models the same thing.

## Proposed Python file shape

For an approved user-contract migration, for example:

```text
libs/dto/user/
    input.py    # UserIn and relevant creation/action inputs
    update.py   # UserUpdate: allowed update fields
    output.py   # UserOut and relevant response envelopes
```

These are examples, not created files. Group by business feature, not automatically
by every database table or all twelve service groups. Use Python filenames and
Pydantic validation, not TypeScript decorators or a GraphQL framework conversion.
Preserve existing class names unless renaming is separately justified.

## Contract rules

- Create/In: accepted input fields and deliberate defaults. Trusted identity,
  permissions, audit fields and derived amounts are supplied/checked by the service.
- Update: allow-listed fields; preserve omitted versus explicit null using the
  existing partial-update handling, including model_dump(exclude_unset=True).
  Define clearable fields. Creation defaults must not become patch values.
- Read/Out: explicit response fields and filtering; exclude secrets. Preserve the
  current ORMModel/from_attributes behavior and response envelopes where needed.
- Query/action inputs: add only for real operations, such as search or receiving.
- Reuse [enums](../enums/README.md) for fixed values and [types](../types/README.md)
  only for distinct internal contracts. DTOs do not query, commit or import routes.
- A DTO's accepted fields are not permission grants. Keep ordinary versus privileged
  updates explicit, with service authorization. Borrow structure, not every field
  exposed by the mentor's MemberUpdate.

## Migration discipline

1. Locate the existing DTO in app/schemas/ or inline in a router and trace all callers,
   inherited bases, validators, aliases, defaults, enums and response serialization.
2. Agree the feature destination. Capture contract/authorization regression cases.
3. Move the existing definition once and update imports in the approved operation.
   If compatibility imports are needed, re-export the same class; never maintain
   two independent definitions of the same DTO. Track the shim's cleanup condition.
4. Test validation, missing/null updates, OpenAPI/response compatibility and relevant
   workflow behavior; then test the actual screens using isolated data.
5. Follow the shared release/acceptance process, then remove obsolete imports/shims.
   Retire ALL old schemas/ DTO imports and shims before reusing that namespace.
   The next phase moves only existing models/ ORM mappings into schemas/, preserving imports,
   registration and database metadata. Do not mix legacy DTOs and ORM models there.

Database schema mappings temporarily share [models/](../../models/README.md) with
business services, which use *_service.py. Only the mappings target
[schemas/](../../schemas/README.md) after DTO migration; business operations stay
in models/. No persistence migration is implied.
Ismail coordinates DTO conventions; each feature owner migrates its callers/tests.
See [the full migration sequence](../../models/README.md#migration-sequence).
