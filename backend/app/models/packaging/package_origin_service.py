"""Read-only package business identity and evidenced sewing origin.

Packaging location and current production routing are deliberately not origin
evidence. A positive sewing record identifies its actual line (or historical
sewing department when no assignment exists), at the package's batch grain.
"""

from collections.abc import Iterable

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Query, Session

from app.libs.enums.production import SewingFactoryCode
from app.libs.types.package_origin import PackageNumbers, PackageSewingOrigin
from app.models.model_identity_service import model_number_fields
from app.schemas import (
    Department, LegacyStockReceipt, Model, Package, PackageBatchAllocation, SewingAssignment,
    SewingFlow, SewingRecord, WorkOrder,
)


def package_number_fields(model: Model | None, receipt: LegacyStockReceipt | None = None) -> PackageNumbers:
    identity = model_number_fields(model)
    if model and str(model.code or "").strip().upper().startswith("LEGACY-"):
        # v3 imports retain an unresolved sticker under LEGACY-STICKER-<hash>.
        # Its internal key is not a business model/variant number. Only explicit
        # original/configured identity may fill gaps in the receipt evidence.
        details = model.details_json if isinstance(model.details_json, dict) else {}
        general = details.get("general") if isinstance(details.get("general"), dict) else {}
        identity = {
            "model_no": general.get("model_no") or general.get("modelNo") or details.get("legacy_original_model_no"),
            "variant_no": general.get("variant_no") or general.get("variantNo") or details.get("legacy_original_variant_no"),
        }
    source = receipt.source_payload if receipt and isinstance(receipt.source_payload, dict) else {}
    # The scanned legacy sticker is more specific than a subsequently edited
    # catalog model. Preserve its literal article; never infer from QR digits.
    return {
        "model_no": str(source.get("model_number") or identity["model_no"] or "").strip() or None,
        "variant_no": str(source.get("variant_number") or source.get("article") or identity["variant_no"] or "").strip() or None,
    }


def _origin_rows():
    factory = func.coalesce(
        SewingFlow.factory_code,
        case(
            (Department.code.in_(["MIL", "SEW"]), SewingFactoryCode.MILANA.value),
            (Department.code == "BST", SewingFactoryCode.BESTTEX.value),
            (Department.code == "ECO", SewingFactoryCode.ECO_COTTON.value),
        ),
    )
    # Allocations are authoritative for mixed-batch packages. Only fall back
    # to the primary batch when the package has no allocation rows.
    allocated_batch = select(PackageBatchAllocation.id).where(
        PackageBatchAllocation.package_id == Package.id,
        PackageBatchAllocation.production_batch_id == SewingRecord.production_batch_id,
        PackageBatchAllocation.quantity > 0,
    ).correlate(Package, SewingRecord).exists()
    any_allocations = select(PackageBatchAllocation.id).where(
        PackageBatchAllocation.package_id == Package.id,
    ).correlate(Package).exists()
    batch_matches = or_(
        allocated_batch,
        and_(~any_allocations, or_(
            Package.production_batch_id == SewingRecord.production_batch_id,
            and_(Package.production_batch_id.is_(None), SewingRecord.production_batch_id.is_(None)),
        )),
    )
    return (
        select(Package.id.label("package_id"), factory.label("factory_code"))
        .select_from(Package)
        .join(WorkOrder, WorkOrder.production_order_id == Package.production_order_id)
        .join(SewingRecord, SewingRecord.work_order_id == WorkOrder.id)
        .join(Department, Department.id == WorkOrder.department_id)
        .outerjoin(SewingAssignment, SewingAssignment.id == SewingRecord.sewing_assignment_id)
        .outerjoin(SewingFlow, SewingFlow.id == SewingAssignment.sewing_flow_id)
        .where(SewingRecord.sewn_qty > 0, batch_matches, factory.isnot(None))
        .distinct()
    )


def filter_sewing_factory(query: Query, factory: SewingFactoryCode | None) -> Query:
    if factory is None:
        return query
    origins = _origin_rows().subquery()
    return query.filter(Package.id.in_(select(origins.c.package_id).where(origins.c.factory_code == factory.value)))


def package_sewing_origins(db: Session, package_ids: Iterable[int]) -> dict[int, PackageSewingOrigin]:
    ids = sorted({int(value) for value in package_ids})
    codes: dict[int, set[SewingFactoryCode]] = {package_id: set() for package_id in ids}
    for offset in range(0, len(ids), 400):
        for package_id, factory in db.execute(_origin_rows().where(Package.id.in_(ids[offset:offset + 400]))):
            codes[package_id].add(SewingFactoryCode(factory))
    return {
        package_id: {"sewing_factory_codes": sorted(values),
                     "sewing_factory_code": next(iter(values)) if len(values) == 1 else None}
        for package_id, values in codes.items()
    }
