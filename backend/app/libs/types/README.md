# Types: internal contracts

**Coordination owner:** Ismail. **Reviewer:** Dilmurod.
Feature owners maintain their internal contracts. See [team ownership](../../../../docs/TEAM_OWNERSHIP.md).

This folder contains used internal contracts, including
[purchase-request commands](purchasing.py) and
[finished-goods reservation requests/results](stock_reservation.py).
Their presence does not establish complete type coverage; each operation still
needs its producer, consumer and verification evidence.

`stock_reservation.py` also contains typed outcomes for the direct Fulfillment
manual-package and piece-stock reserve operation; the route maps those outcomes
to its existing, branch-specific HTTP response shapes.

`catalog.py` carries the actual Model CREATE command and insert values. The
command keeps known paid-operation rows as `PaidOperationIn` through business
factory-scope checks; the schema operation serializes them at persistence.
Model status remains raw pending the legacy vocabulary census.

The same catalog module carries `ModelImageUploadCommand` from the upload
service to its schema writer. Its `image_type` field uses the multipart
action's `ModelImageUploadType` subset and its primary flag is an explicit
service decision; this does not canonicalize all historical ModelImage rows.

## Purpose

Describe data passed between internal operations when its shape differs from an
HTTP request, HTTP response, or database model. This adapts the mentor's shared
types discipline without duplicating the existing Pydantic schemas.

## What belongs here

- A named internal result or parameter shared by multiple operations.
- A focused `dataclass`, `TypedDict`, or type alias, chosen for the actual use.
- Feature-specific files with an identified owner, rather than one large bag of
  unrelated types. A type used by one feature can stay beside that feature.

## Keep the existing responsibilities

- `app/libs/dto/<feature>/` contains Pydantic input, update and output DTOs.
- `app/schemas/` contains SQLAlchemy definitions, registration and schema-owned
  persistence operations; the outer business service coordinates the transaction.
- `app/libs/enums/` is the home for fixed vocabulary as approved operations adopt it.
- `app/models/<group>/*_service.py` implements business operations and their runtime
  rules; existing shared helpers remain at `app/models/*_service.py`.
  The former `app/services/` layout is historical. New business-service work uses
  the existing `models/` domain, as described in [the service guide](../../models/README.md).

## Rules

- Add an internal type only for a real shared contract; do not mirror every
  schema or database table here.
- Use precise fields instead of arbitrary dictionaries for known data shapes.
- A field representing a known fixed business vocabulary uses its canonical enum
  annotation, including nested command/result types. Repeated string Literals,
  `str`, `Any`, or `Enum | str` do not complete the system-wide enum adoption target.
  Keep action subsets and legitimate optionality explicit without widening values.
- Reuse DTOs or mapped objects where they already express the needed contract;
  introduce a distinct internal command/result when the operation really needs one.
  Add or refine the actual producer and consumer annotations together, not unused
  type declarations that leave the real call boundary as an unstructured dictionary.
- Type annotations alone do not validate external input or enforce permissions.
- Do not put database queries, transaction management, or HTTP handling here.
- Do not create interfaces for every concrete service or a second DTO hierarchy.
- Avoid importing service implementations or routers into shared types.

Extend this folder only when an approved operation needs such a contract.

## How to make an internal type file

Use a feature-named file and a dataclass, TypedDict or alias only when a real
internal input/result differs from the API DTO and ORM object. State its caller
and consumer. Keep a private type beside its service when nothing else uses it.
Do not duplicate Create/Update/Read schemas, add runtime queries, or build an
interface for each service. Prove the contract through the consuming operation's tests.
