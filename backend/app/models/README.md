# Current database schema models: migration source

**Coordination owner:** Mirshoir. **Reviewer:** Ismail.
Feature owners handle their mappings; Mirshoir coordinates registration and migration. See [team ownership](../../../docs/TEAM_OWNERSHIP.md).

Target location: [schemas/](../schemas/README.md), matching the mentor's naming.
The existing Python mappings still live here. First migrate ALL current schemas/
DTOs/callers and retire compatibility imports; only then relocate these database
definitions with their imports and Alembic metadata registration. Do not duplicate
mapped classes or change table names. Naming cleanup should produce no schema diff.
The conventions below apply to the current files and their future schemas/ home.

These existing SQLAlchemy models are the counterpart of the mentor's Mongoose
schema models: table names, columns, relationships, constraints and storage defaults.
Keep each table's authoritative mapping here; do not create a second schema tree.

Services use these models plus SQLAlchemy Session to read/write PostgreSQL. Models
do not replace request DTOs, authorize callers or own an HTTP response. Avoid
workflow orchestration hidden in model hooks or imports from routers/services.

A Python file move does not itself need an Alembic migration. Preserve metadata
registration and imports. Changing columns, constraints, default behavior or enum
storage is a separate persistence change: inspect actual data, get technical review,
rehearse on isolated PostgreSQL and establish old/new application compatibility.
Alembic autogeneration is a draft to review, not permission to apply it to production.

Python Enum and PostgreSQL ENUM are different choices. Keep existing stored values
through this refactor. Do not assume rolling back an image reverses a migration or
restores business data. See the [team plan](../../../docs/REFACTOR_PLAN.md).

## How to make or reorganize a model file

1. Search for the existing mapped class and table first. Most work here moves or
   clarifies an existing definition; it does not create another table.
2. Group related mapped classes in a domain-named snake_case file. Keep the existing
   Base, table name, primary/foreign keys, precision, defaults and relationships.
3. Preserve model registration and callers, including models/__init__.py and Alembic
   metadata discovery. Do not register the same table through two different classes.
4. Do not move business workflow, permissions or commits into a mapped class.
5. Review any actual database-schema change separately. A source move should have
   no schema diff. Validate metadata/imports and relevant PostgreSQL constraints.

See [the complete model ownership proposal](../../../docs/REFACTOR_MAP.md#existing-database-models).
It maps existing classes to business groups; it creates no new model directories
or tables. Models may stay as focused files while services use group directories.
