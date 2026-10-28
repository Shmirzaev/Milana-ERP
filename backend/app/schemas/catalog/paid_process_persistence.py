"""Schema-owned persistence for the paid-process catalogue tables.

These operations own the mapped construction, the insert and the post-insert
identity-code update for `paid_processes` and `usluga_paid_processes`. They use
the supplied Session and never commit, begin a transaction, swallow errors or
import services or routes; the calling service owns the transaction, the
business rules and the audit row.
"""

from uuid import uuid4

from sqlalchemy.orm import Session

from app.libs.enums.catalog import PaidProcessSection
from app.schemas.catalog.paid_process import PaidProcess, UslugaPaidProcess

PaidProcessRow = PaidProcess | UslugaPaidProcess
PaidProcessModel = type[PaidProcess] | type[UslugaPaidProcess]


def build_paid_process(
    model: PaidProcessModel,
    *,
    factory_code: str,
    normalized_key: str,
    section: PaidProcessSection,
    normalized_name: str,
    name: str,
    prefix: str,
) -> PaidProcessRow:
    """Build the mapped row with the provisional unique identity code.

    The section arrives as its canonical enum member and is serialized only at
    the mapped assignment, so the member travels member-typed to the column.
    """
    return model(
        factory_code=factory_code,
        normalized_key=normalized_key,
        section=section.value,
        normalized_name=normalized_name,
        name=name,
        code=f"{prefix}-{uuid4().hex[:12].upper()}",
    )


def insert_paid_process(db: Session, row: PaidProcessRow) -> PaidProcessRow:
    """Add the row and flush it so the generated id is available."""
    db.add(row)
    db.flush()
    return row


def assign_paid_process_code(row: PaidProcessRow, prefix: str) -> PaidProcessRow:
    """Replace the provisional code with the final short code from the row id."""
    row.code = f"{prefix}-{row.id:04d}"
    return row
