"""Read-only Besttex cutting history. Never completes Cutting or changes data."""
from fastapi import HTTPException
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, aliased, joinedload, load_only, noload, selectinload

from app.core.deps import user_permissions
from app.schemas.besttex_cutting import BesttexCuttingPageOut, BesttexCuttingRowOut
from app.services.cutting_sheet import render_cutting_sheet_html
from app.services.factory_scope import selected_factory_code
from app.services.model_family_images import family_images_for_models
from app.services.model_identity import model_number_fields
from app.services.model_images import model_preview_image_url, model_variant_picture_url
from app.models import BrandedPlanningOrder, Bundle, CuttingRecord, Department, Model, ModelImage, ProductionBatch, ProductionOrder, SalesOrder, User, WorkOrder

PERMISSION = "besttex.cutting_sheets"


def _authorize(actor: User) -> None:
    permissions = user_permissions(actor)
    if "*" in permissions:
        return
    if PERMISSION not in permissions or selected_factory_code(actor) != "BST":
        raise HTTPException(403, "Besttex cutting-sheet read access required")


def _records(db: Session):
    sewing = aliased(WorkOrder)
    specific = aliased(WorkOrder)
    other_record = aliased(CuttingRecord)
    other_work = aliased(WorkOrder)
    batch_id = CuttingRecord.production_batch_id
    # A batch-specific route wins over historical order-level routing. A null
    # route is a fallback only when no active sewing route exists for that batch.
    has_specific = db.query(specific.id).filter(
        specific.production_order_id == WorkOrder.production_order_id,
        specific.operation == "sewing", specific.status.notin_(["cancelled", "rejected"]),
        specific.production_batch_id == batch_id,
    ).correlate(CuttingRecord, WorkOrder).exists()
    besttex = db.query(sewing.id).join(Department, Department.id == sewing.department_id).filter(
        sewing.production_order_id == WorkOrder.production_order_id,
        sewing.operation == "sewing", sewing.status.notin_(["cancelled", "rejected"]), Department.code == "BST",
        or_(sewing.production_batch_id == batch_id,
            and_(sewing.production_batch_id.is_(None), ~has_specific)),
    ).correlate(CuttingRecord, WorkOrder).exists()
    linked = db.query(Bundle.id).filter(Bundle.cutting_record_id == CuttingRecord.id,
                                       Bundle.status != "cancelled").correlate(CuttingRecord).exists()
    same_batch = Bundle.production_batch_id.is_not_distinct_from(CuttingRecord.production_batch_id)
    unique_legacy_record = db.query(func.count(other_record.id)).join(
        other_work, other_work.id == other_record.work_order_id,
    ).filter(
        other_work.production_order_id == WorkOrder.production_order_id,
        other_record.production_batch_id.is_not_distinct_from(CuttingRecord.production_batch_id),
    ).correlate(CuttingRecord, WorkOrder).scalar_subquery() == 1
    bundle_scope = and_(Bundle.production_order_id == WorkOrder.production_order_id,
                        same_batch,
                        Bundle.status != "cancelled", or_(
                            Bundle.cutting_record_id == CuttingRecord.id,
                            and_(~linked, unique_legacy_record, Bundle.cutting_record_id.is_(None),
                                 or_(Bundle.production_batch_id == CuttingRecord.production_batch_id,
                                     and_(Bundle.production_batch_id.is_(None), CuttingRecord.production_batch_id.is_(None)))),
                        ))
    scoped_bundles = db.query(Bundle.id).filter(bundle_scope).correlate(CuttingRecord, WorkOrder).exists()
    any_batch_bundles = db.query(Bundle.id).filter(
        Bundle.production_order_id == WorkOrder.production_order_id, same_batch,
    ).correlate(CuttingRecord, WorkOrder).exists()
    routed = db.query(Bundle.id).filter(bundle_scope, Bundle.sewing_factory_code.isnot(None)).correlate(
        CuttingRecord, WorkOrder).exists()
    bst_bundle = db.query(Bundle.id).filter(bundle_scope, Bundle.sewing_factory_code == "BST").correlate(
        CuttingRecord, WorkOrder).exists()
    other_bundle = db.query(Bundle.id).filter(bundle_scope, or_(Bundle.sewing_factory_code != "BST",
                                                               Bundle.sewing_factory_code.is_(None))).correlate(
        CuttingRecord, WorkOrder).exists()
    return db.query(CuttingRecord, ProductionOrder, ProductionBatch.batch_no, Model.code, Model.name, SalesOrder.order_no).options(
        noload(ProductionOrder.materials),
    ).join(
        WorkOrder, WorkOrder.id == CuttingRecord.work_order_id,
    ).join(ProductionOrder, ProductionOrder.id == WorkOrder.production_order_id).outerjoin(
        ProductionBatch, ProductionBatch.id == batch_id,
    ).outerjoin(Model, Model.id == ProductionOrder.model_id).outerjoin(
        SalesOrder, SalesOrder.id == ProductionOrder.sales_order_id,
    ).filter(
        # The existing sheet renderer scopes by the record's batch. Do not let
        # an inconsistent legacy WorkOrder batch authorize a different sheet.
        or_(WorkOrder.production_batch_id.is_(None), WorkOrder.production_batch_id == CuttingRecord.production_batch_id),
        WorkOrder.operation == "cutting", WorkOrder.status.notin_(["cancelled", "rejected"]),
        ProductionOrder.status.notin_(["cancelled", "rejected"]),
        CuttingRecord.approval_status == "approved", CuttingRecord.cut_pieces > 0,
        or_(scoped_bundles, and_(~linked, ~any_batch_bundles)),
        or_(and_(routed, bst_bundle, ~other_bundle), and_(~routed, besttex)),
    )


def list_besttex_cutting(db: Session, actor: User, *, page: int, page_size: int, search: str) -> BesttexCuttingPageOut:
    _authorize(actor)
    query = _records(db)
    if search.strip():
        term = search.strip().lower()
        query = query.outerjoin(BrandedPlanningOrder, BrandedPlanningOrder.id == ProductionOrder.planning_order_id)
        query = query.filter(or_(*[func.lower(column).contains(term, autoescape=True) for column in (
            CuttingRecord.cutting_batch_no, ProductionOrder.production_no, SalesOrder.order_no, ProductionBatch.batch_no, Model.code, Model.name,
            BrandedPlanningOrder.order_no, BrandedPlanningOrder.ordered_for_name,
        )]))
    total = query.count()
    rows = query.options(
        joinedload(ProductionOrder.planning_order), selectinload(ProductionOrder.items),
    ).order_by(CuttingRecord.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    # Resolve only this page's models together, without loading image binaries
    # or asking a read-only Besttex account to access the catalog endpoint.
    models = {model.id: model for model in db.query(Model).options(
        load_only(Model.id, Model.code, Model.name, Model.details_json, Model.catalog_scope, Model.factory_code),
        noload(Model.bom), selectinload(Model.images).defer(ModelImage.file_data, raiseload=True),
    ).filter(Model.id.in_({row[1].model_id for row in rows})).all()}
    family_images_for_models(db, models.values())
    presentation = {}
    for _, order, *_ in rows:
        model = models.get(order.model_id)
        planning = order.planning_order
        sizes = list(dict.fromkeys(str(item.size).strip() for item in order.items if str(item.size or "").strip()))
        if sizes and all(size.isdigit() for size in sizes):
            sizes.sort(key=int)
            summary = f"{sizes[0]}–{sizes[-1]} ({len(sizes)})" if len(sizes) > 1 else sizes[0]
        else:
            summary = ", ".join(sizes) or None
        presentation[order.id] = dict(
            planning_order_id=order.planning_order_id,
            planning_order_no=planning.order_no if planning else None,
            planning_order_name=planning.ordered_for_name if planning else None,
            **model_number_fields(model), model_image_url=model_preview_image_url(model),
            variant_image_url=model_variant_picture_url(model),
            size_summary=summary,
            material_label=order.estimated_material_code or order.service_material_description,
            deadline=order.deadline,
        )
    return BesttexCuttingPageOut(items=[BesttexCuttingRowOut(
        cutting_record_id=record.id, cutting_batch_no=record.cutting_batch_no,
        production_no=order.production_no, order_no=sales_no or order.production_no,
        batch_no=batch_no, model_code=code, model_name=name,
        cut_pieces=record.cut_pieces, passed_pieces=record.passed_pieces, created_at=record.created_at,
        **presentation[order.id],
    ) for record, order, batch_no, code, name, sales_no in rows], total=total, page=page, page_size=page_size)


def besttex_cutting_sheet(db: Session, actor: User, record_id: int) -> str:
    _authorize(actor)
    row = _records(db).filter(CuttingRecord.id == record_id).first()
    if row is None:
        raise HTTPException(404, "Cutting sheet not found for Besttex")
    record = row[0]
    work = db.get(WorkOrder, record.work_order_id)
    bundles = db.query(Bundle).filter(Bundle.cutting_record_id == record.id, Bundle.status != "cancelled",
                                     Bundle.production_order_id == work.production_order_id,
                                     Bundle.production_batch_id == record.production_batch_id).all()
    if not bundles:
        bundles = db.query(Bundle).filter(
            Bundle.production_order_id == work.production_order_id, Bundle.cutting_record_id.is_(None),
            Bundle.production_batch_id == record.production_batch_id, Bundle.status != "cancelled",
        ).all()
    ids = [bundle.id for bundle in bundles if bundle.sewing_factory_code in {"BST", None}]
    # With no selected IDs the legacy renderer falls back to whole-batch bundles.
    # Refuse that ambiguous fallback if it could include another record/factory.
    if not ids and db.query(Bundle.id).filter(
        Bundle.production_order_id == work.production_order_id,
        Bundle.production_batch_id == record.production_batch_id,
    ).first():
        raise HTTPException(404, "Cutting sheet has no unambiguous Besttex bundles")
    try:
        return render_cutting_sheet_html(db, record, ids)
    except ValueError as error:
        raise HTTPException(404, str(error)) from error
