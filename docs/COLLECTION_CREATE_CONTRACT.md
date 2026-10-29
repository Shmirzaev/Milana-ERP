# Collection creation contract

CAT-COLLECTION-CREATE, 27 October 2026. Engineer: Ismail; human reviewer: Mirshoir.

POST `/api/collections` uses `CollectionCreateIn` and `CollectionCreateOut` with
the canonical `CollectionStatus`: draft, approved, archived. Omitted status is
the enum member DRAFT. Invalid values deliberately return DTO validation **422**
instead of the previous service **400**, and OpenAPI exposes the enum. JSON
responses retain the same string values and fields. Year coercion, brand FK,
permissions and free-data fields retain their existing behavior.

The existing Catalog service calls `schemas/catalog/collection_persistence.py`
with the same Session and enum member. That helper constructs/adds/flushes the
row, serializing status.value only at storage. The service owns the real audit,
one outer commit and refresh. No migration, helper commit or new Session is used.

| Surface | State and reason |
|---|---|
| POST DTO, service input/result, persistence status | Canonical enum annotations; runtime/default/OpenAPI/JSON checks required |
| ORM default | Canonical draft value; column remains String to read legacy states |
| Frontend create request/result | Dedicated typed contracts; form still omits status to use backend default |
| PATCH CollectionIn and list/get/PATCH CollectionOut | Explicitly retained string compatibility; unchanged unknown historical status must survive an unrelated edit |
| Frontend list/edit and ORM mapped status | Pending historical vocabulary reconciliation; not counted as completed enum coverage |
| Seeds/imports and other Catalog operations | Separate remaining operations; this insert does not migrate them |

No full collection-status inventory is established by synthetic fixtures.
Before closing the remaining types, reconcile authorized stored values with the
domain owner. Keep existing compatibility re-exports for CollectionIn/Out.

Verification must preserve real PostgreSQL FK and audit rollback assertions,
including failure after audit hashes are flushed, and detect bypassed schema
writes/helper commits. Independent reviewer validation and actual connected
browser create/reopen/default/audit readback plus legacy-edit checks remain
pending for this candidate. No AI_VERIFIED_AWAITING_HUMAN or human acceptance is
implied by this document or by automated results alone.
