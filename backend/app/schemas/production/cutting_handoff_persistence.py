"""Persist a dispatch without assigning the bundles to the receiving department."""
from sqlalchemy.orm import Session

from app.libs.enums.production import CuttingHandoffFactory
from app.schemas.production.tracking import Bundle, BundleScanLog


def record_cutting_dispatch(db: Session, bundles: list[Bundle], *, origin_id: int,
                            destination_id: int, factory: CuttingHandoffFactory, actor_id: int) -> None:
    scans = []
    for bundle in bundles:
        bundle.status = "sent_to_sewing"
        bundle.current_department_id = None
        bundle.next_department_id = destination_id
        bundle.sewing_factory_code = factory.value
        scans.append(BundleScanLog(
            bundle_id=bundle.id, scan_type="sent_sewing",
            from_department_id=origin_id, to_department_id=destination_id, scanned_by=actor_id,
        ))
    db.add_all(scans)
    db.flush()
