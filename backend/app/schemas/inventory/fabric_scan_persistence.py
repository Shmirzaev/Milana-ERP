"""Schema-owned persistence for the daily fabric scan register."""

from sqlalchemy.orm import Session

from app.libs.types.inventory import FabricScanCreateCommand
from app.schemas.inventory.fabric_scan import FabricScan


def add_fabric_scan(db: Session, command: FabricScanCreateCommand) -> FabricScan:
    """Attach one server-built snapshot row to the caller's Session.

    The caller owns duplicate handling, commit and the IntegrityError recovery
    path. This writer intentionally does not flush or manage transactions.
    """
    row = FabricScan(
        department=command.department.value,
        report_date=command.report_date,
        batch_id=command.batch_id,
        roll_number=command.roll_number,
        direction=command.direction.value,
        fabric_name=command.fabric_name,
        batch_no=command.batch_no,
        color=command.color,
        operator_id=command.operator_id,
        operator_name=command.operator_name,
        scanned_at=command.scanned_at,
    )
    db.add(row)
    return row
