"""Schema-owned persistence operations for catalog Models."""

from copy import deepcopy

from sqlalchemy.orm import Session

from app.libs.types.catalog import ModelCreateDetails, ModelInsert
from app.schemas.catalog.catalog import Model


def serialize_model_create_details(details: ModelCreateDetails) -> dict[str, object]:
    """Build the persisted JSON shape from open metadata plus typed rows."""

    serialized = deepcopy(details.metadata)
    if details.has_paid_operations:
        rows = details.paid_operations
        serialized["paid_operations"] = (
            [row.model_dump(mode="json", exclude_unset=True) for row in rows]
            if rows is not None
            else None
        )
    if details.has_paid_operations_alias:
        rows = details.paidOperations
        serialized["paidOperations"] = (
            [row.model_dump(mode="json", exclude_unset=True) for row in rows]
            if rows is not None
            else None
        )
    return serialized


def insert_model(db: Session, command: ModelInsert) -> Model:
    """Insert one decided Model row, including inherited approval fields.

    The caller retains validation, family selection/locking, audit and the outer
    transaction. This operation uses the supplied Session, flushes for the new
    Model ID, and never commits.
    """

    details = serialize_model_create_details(command.details_json)
    model = Model(
        code=command.code,
        name=command.name,
        catalog_scope=command.catalog_scope.value,
        factory_code=command.factory_code.value if command.factory_code else None,
        category=command.category,
        description=command.description,
        brand_id=command.brand_id,
        collection_id=command.collection_id,
        product_type=command.product_type,
        season=command.season,
        constructor_employee_id=command.constructor_employee_id,
        designer_employee_id=command.designer_employee_id,
        details_json=details,
        status=command.status,
        sam_minutes=command.sam_minutes,
        created_by=command.created_by,
    )
    if command.approval_inheritance is not None:
        model.status = "approved"
        model.approved_by = command.approval_inheritance.approved_by
        model.approved_at = command.approval_inheritance.approved_at
    db.add(model)
    db.flush()
    return model
