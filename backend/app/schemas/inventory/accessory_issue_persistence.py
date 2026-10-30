"""Schema-owned writes for accessory issue rows."""

from sqlalchemy.orm import Session

from app.libs.types.inventory import AccessoryIssueLineCommand
from app.schemas.inventory.inventory import ManualAccessoryIssue


def add_manual_accessory_issue(
    db: Session,
    *,
    production_order_id: int,
    item_id: int | None,
    line: AccessoryIssueLineCommand,
    item_sku: str | None,
    item_name: str,
    unit: str,
    created_by: int | None,
) -> ManualAccessoryIssue:
    """Insert a service-normalized manual issue on the caller's Session."""
    issue = ManualAccessoryIssue(
        production_order_id=production_order_id,
        item_id=item_id,
        item_sku=item_sku,
        item_name=item_name,
        quantity=line.quantity,
        unit=unit,
        notes=line.notes,
        created_by=created_by,
    )
    db.add(issue)
    return issue
