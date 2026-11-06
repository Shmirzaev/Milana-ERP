"""Purchase request operations: directory, creation, approval, rejection, conversion.

Contract for the purchase request operations:
* input: a validated request DTO, a request id and the acting user; the
  create-from-sales-order operation takes a sales order id instead
* output: the persisted `PurchaseRequest`, or the `PurchaseOrder` a conversion
  produced
* refusals: the 400/404/409 messages the core operations raise, plus 403 when
  the caller may not reach one of the request's items
* records: purchase request rows and their lines, the audit rows and the
  department notifications the core operations write
* transaction owner: each operation below; it commits once, after the
  caller's access to every line has been checked
"""
from fastapi import UploadFile
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.libs.dto.purchasing.purchase_request_input import (
    PurchaseRequestApprovalIn,
    PurchaseRequestIn,
    PurchaseRequestOrderIn,
)
from app.libs.types.purchasing import (
    PurchaseRequestApprovalCommand,
    PurchaseRequestConversionCommand,
    PurchaseRequestCreateCommand,
)
from app.models import inventory_access_service as inventory_access
from app.libs.dto.purchasing.purchase_order_output import PurchaseOrderCreationOut
from app.models import purchasing_service as purchasing_core
from app.models.image_storage_service import store_uploaded_image
from app.schemas import Item, PurchaseRequest, PurchaseRequestLine, User

def list_purchase_requests(db: Session, *, user: User) -> list[PurchaseRequest]:
    """The purchase requests the caller may see, newest first.

    A materials-only caller only sees requests whose lines all belong to
    material items.
    """
    return (
        db.query(PurchaseRequest)
        .filter(~PurchaseRequest.lines.any(PurchaseRequestLine.item_id.in_(
            db.query(Item.id).filter(Item.category.notin_(inventory_access.MATERIAL_CATEGORIES))
        )) if inventory_access.materials_only(user) else True)
        .options(joinedload(PurchaseRequest.lines))
        .order_by(PurchaseRequest.id.desc())
        .all()
    )


def _purchase_request_command(payload: PurchaseRequestIn) -> PurchaseRequestCreateCommand:
    """The HTTP payload as the shared internal create command.

    The command carries the canonical status member, so the core operation
    never has to re-parse a raw string.
    """
    return {
        "status": payload.status,
        "sales_order_id": payload.sales_order_id,
        "production_order_id": payload.production_order_id,
        "notes": payload.notes,
        "lines": [
            {
                "item_id": line.item_id,
                "required_quantity": line.required_quantity,
                "requested_quantity": line.requested_quantity,
                "unit": line.unit,
                "available_quantity": line.available_quantity,
                "shortage_quantity": line.shortage_quantity,
                "preferred_supplier_id": line.preferred_supplier_id,
                "material_name": line.material_name,
                "photo_url": line.photo_url,
                "notes": line.notes,
            }
            for line in payload.lines
        ],
    }


def create_purchase_request(db: Session, *, payload: PurchaseRequestIn, current: User) -> PurchaseRequest:
    """Create a purchase request and commit it once its lines are authorized."""
    request = purchasing_core.create_purchase_request(
        db, data=_purchase_request_command(payload), current=current
    )
    purchasing_core.require_purchase_item_access(db, current, request.lines)
    db.commit()
    db.refresh(request)
    return request


def create_purchase_request_from_sales_order(
    db: Session, *, sales_order_id: int, current: User
) -> PurchaseRequest:
    """Create a purchase request from the shortages of one sales order."""
    request = purchasing_core.create_purchase_request_from_sales_order(
        db, sales_order_id=sales_order_id, current=current
    )
    purchasing_core.require_purchase_item_access(db, current, request.lines)
    db.commit()
    db.refresh(request)
    return request


def _purchase_request_approval_command(payload: PurchaseRequestApprovalIn) -> PurchaseRequestApprovalCommand:
    """Preserve the validated approval fields, including untrimmed text."""
    return {"lines": [
        {
            "purchase_request_line_id": line.purchase_request_line_id,
            "material_name": line.material_name,
            "preferred_supplier_id": line.preferred_supplier_id,
            "photo_url": line.photo_url,
        }
        for line in payload.lines
    ]}


def approve_purchase_request(
    db: Session, *, request_id: int, payload: PurchaseRequestApprovalIn, current: User
) -> PurchaseRequest:
    """Approve a purchase request with the supplier, material name and photo of each line."""
    request = purchasing_core.approve_purchase_request(
        db, request_id=request_id, data=_purchase_request_approval_command(payload), current=current
    )
    purchasing_core.require_purchase_item_access(db, current, request.lines)
    db.commit()
    db.refresh(request)
    return request


def reject_purchase_request(db: Session, *, request_id: int, current: User) -> PurchaseRequest:
    """Reject a purchase request."""
    request = purchasing_core.reject_purchase_request(db, request_id=request_id, current=current)
    purchasing_core.require_purchase_item_access(db, current, request.lines)
    db.commit()
    db.refresh(request)
    return request


def _purchase_request_conversion_command(
    payload: PurchaseRequestOrderIn,
) -> PurchaseRequestConversionCommand:
    """The HTTP payload as the shared internal conversion command.

    The command carries only what the caller decides: the expected date and
    the quantity it orders for each request line.
    """
    return {
        "expected_date": payload.expected_date,
        "lines": [
            {
                "purchase_request_line_id": line.purchase_request_line_id,
                "ordered_quantity": line.ordered_quantity,
            }
            for line in payload.lines
        ],
    }


def convert_purchase_request_to_order(
    db: Session, *, request_id: int, payload: PurchaseRequestOrderIn, current: User
) -> PurchaseOrderCreationOut:
    """Convert an approved purchase request into a purchase order."""
    order = purchasing_core.convert_purchase_request_to_order(
        db, request_id=request_id, data=_purchase_request_conversion_command(payload), current=current
    )
    purchasing_core.require_purchase_item_access(db, current, order.lines)
    db.refresh(order)
    result = PurchaseOrderCreationOut.model_validate(order)
    db.commit()
    return result


async def store_request_photo(file: UploadFile) -> dict[str, str]:
    """Store one purchase request photo and return its public URL."""
    stored = await store_uploaded_image(
        file,
        target_dir=settings.MODEL_FILES_DIR,
        file_url_base="/storage/model-files",
        name_prefix="purchase",
        max_bytes=10 * 1024 * 1024,
        prebuild_thumbnails=True,
    )
    return {"file_url": stored.file_url}
