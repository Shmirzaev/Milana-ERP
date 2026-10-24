# Types: internal contracts

**Coordination owner:** Ismail. **Reviewer:** Dilmurod.
Feature owners maintain their internal contracts. See [team ownership](../../../../docs/TEAM_OWNERSHIP.md).

This folder documents the intended home for shared internal contracts when a
concrete need is established. No Python types have been introduced yet.

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
- `app/schemas/` contains SQLAlchemy database definitions and registration.
- `app/libs/enums/` is the home for fixed vocabulary as approved operations adopt it.
- `app/models/*_service.py` implements business operations and their runtime rules.

## Rules

- Add an internal type only for a real shared contract; do not mirror every
  schema or database table here.
- Use precise fields instead of arbitrary dictionaries for known data shapes.
- Type annotations alone do not validate external input or enforce permissions.
- Do not put database queries, transaction management, or HTTP handling here.
- Do not create interfaces for every concrete service or a second DTO hierarchy.
- Avoid importing service implementations or routers into shared types.

Populate this folder only when an approved operation needs such a contract.

## How to make an internal type file

Use a feature-named file and a dataclass, TypedDict or alias only when a real
internal input/result differs from the API DTO and ORM object. State its caller
and consumer. Keep a private type beside its service when nothing else uses it.
Do not duplicate Create/Update/Read schemas, add runtime queries, or build an
interface for each service. Prove the contract through the consuming operation's tests.
