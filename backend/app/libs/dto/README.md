# DTOs: feature input, update and output contracts

**Coordination owner:** Ismail. **Reviewer:** Mirshoir.
Each feature owner migrates its callers and contract tests. See [team ownership](../../../../docs/TEAM_OWNERSHIP.md).

This is the active home for Pydantic data-transfer objects, following Meditech.
The 22 existing DTO files were moved here with their callers, preserving class
names, validators, fields and defaults. Files are grouped by business area;
common.py holds shared bases and validators. Inline route DTOs remain for later
operation-level extraction. The folder move does not certify every contract's design.

## The mentor's actual structure

Inspected local Meditech snapshot b4c646ce471efbf6fe984f3315bba366b197281a:

- [member.input.ts](https://github.com/Ismoiljon1101/meditech-nest/blob/b4c646ce471efbf6fe984f3315bba366b197281a/apps/nestar-api/src/libs/dto/member/member.input.ts): MemberInput, LoginInput and inquiry inputs; GraphQL InputType/Field and class-validator decorators.
- [member.update.ts](https://github.com/Ismoiljon1101/meditech-nest/blob/b4c646ce471efbf6fe984f3315bba366b197281a/apps/nestar-api/src/libs/dto/member/member.update.ts): a separate MemberUpdate with optional editable fields.
- [member.ts](https://github.com/Ismoiljon1101/meditech-nest/blob/b4c646ce471efbf6fe984f3315bba366b197281a/apps/nestar-api/src/libs/dto/member/member.ts): GraphQL ObjectType output definitions, including Member and Members.
- [Member.model.ts](https://github.com/Ismoiljon1101/meditech-nest/blob/b4c646ce471efbf6fe984f3315bba366b197281a/apps/nestar-api/src/schemas/Member.model.ts): the separate Mongoose database schema, with defaults, indexes and persistence fields.
- [member.service.ts](https://github.com/Ismoiljon1101/meditech-nest/blob/b4c646ce471efbf6fe984f3315bba366b197281a/apps/nestar-api/src/components/member/member.service.ts): accepts DTOs and calls the injected Mongoose model for create/update/query.

The resolver also imports DTOs. They describe data at the boundary; they are not
an extra execution layer between service and database. Meditech's schemas/ means
database schemas; Milana now uses the same distinction. SQLAlchemy definitions
are in schemas/ and Pydantic contracts are here. They have different jobs.

## Proposed Python file shape

For an approved user-contract migration, for example:

```text
libs/dto/user/
    user_input.py    # UserIn and relevant creation/action inputs
    user_update.py   # UserUpdate: allowed update fields
    user_output.py   # UserOut and relevant response envelopes
```

Use entity-prefixed filenames and explicit imports, for example:
`from app.libs.dto.user.user_input import UserIn`. Python distinguishes modules
by the full package path; the prefix also makes the file clear in searches and editor tabs.

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
- Ismail's current system-wide target requires enum **field annotations** in input,
  update and output DTOs for known fixed vocabularies, as in the mentor's MemberType,
  MemberStatus and MemberAuthType contracts. `status: str = SomeEnum.VALUE.value`
  does not satisfy this. Neither does `SomeEnum | str` or an `Any` escape.
- Preserve omitted/null semantics and normalization with explicit validators while
  keeping the field enum-typed. Restrict an action's subset without inventing a second
  independent vocabulary or granting new transitions. Record deliberate validation
  and generated OpenAPI differences rather than leaving the field untyped to keep
  an old snapshot green. Recheck frontend serialized values and actual UI behavior.
- Test the runtime type for omitted and explicitly supplied enum fields. Use enum
  members as defaults or explicit default validation; an enum annotation with a
  raw `.value` default can otherwise leave omitted input as an unvalidated string.
  Check consumers using `str(member)` and serialize the actual value deliberately.
- A DTO's accepted fields are not permission grants. Keep ordinary versus privileged
  updates explicit, with service authorization. Borrow structure, not every field
  exposed by the mentor's MemberUpdate.

## Extending or extracting a contract

1. Find the existing definition here or inline in a router. Trace callers, bases,
   validators, aliases, defaults and response serialization before changing it.
2. Agree the feature destination and preserve one definition per contract.
3. Keep existing class names. Split <entity>_input.py/<entity>_update.py/<entity>_output.py only where that
   helps a real feature; the current files already contain distinct contract classes.
4. Update callers and test enum annotations and generated schema, validation,
   omitted/null updates, allowed fields, serialized response values and authorization
   through the consuming service. Compatibility evidence must identify intentional
   typed-contract changes separately from regressions; it cannot redefine the target.
5. Exercise the real screens on isolated data and follow shared release acceptance.

Database mappings are in [schemas/](../../schemas/README.md); business operations
are in [models/](../../models/README.md). DTOs do not execute queries or commits.

Ismail coordinates DTO conventions; each feature owner migrates its callers/tests.
See [the full migration sequence](../../models/README.md#migration-sequence).
