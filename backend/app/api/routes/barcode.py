from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import load_only

from app.core.deps import DbSession, CurrentUser, PRODUCTION_READ_PERMISSIONS, require_permissions
from app.models import Bundle, Package, User
from app.services.barcode import bundle_qr_image_url, qr_png_bytes
from app.services.bundles import bundle_qr_payload, find_bundle_by_scanned_code

router = APIRouter(prefix="/barcode", tags=["barcode"])


@router.get("/bundle/{bundle_no}")
def bundle_qr(bundle_no: str, db: DbSession, _: CurrentUser):
    b = find_bundle_by_scanned_code(db, bundle_no)
    if not b: raise HTTPException(404, "Bundle not found")
    return {"qr_code_url": bundle_qr_image_url(b.id), "barcode": b.barcode, "bundle_no": b.bundle_no}


@router.get("/bundle-image/{bundle_id}")
def bundle_qr_image(bundle_id: int, db: DbSession, _: CurrentUser):
    """Cookie-authenticated image for the same-origin bundle detail page."""
    if bundle_id > 2_147_483_647:
        raise HTTPException(404, "Bundle not found")
    bundle = db.query(Bundle).options(
        load_only(
            Bundle.id,
            Bundle.bundle_no,
            Bundle.barcode,
            Bundle.production_order_id,
            Bundle.production_batch_id,
        )
    ).filter(Bundle.id == bundle_id).first()
    if bundle is None:
        raise HTTPException(404, "Bundle not found")
    return Response(
        content=qr_png_bytes(bundle_qr_payload(db, bundle)), media_type="image/png",
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/package/{package_no}")
def package_qr(package_no: str, db: DbSession, _: CurrentUser):
    p = db.query(Package.qr_code_url, Package.barcode, Package.package_no).filter(
        Package.package_no == package_no,
    ).first()
    if not p: raise HTTPException(404, "Package not found")
    qr_code_url, barcode, resolved_package_no = p
    return {"qr_code_url": qr_code_url, "barcode": barcode, "package_no": resolved_package_no}


@router.post("/generate-bundle-label/{bundle_id}")
def gen_bundle_label(bundle_id: int, _: User = Depends(require_permissions(*PRODUCTION_READ_PERMISSIONS))):
    return RedirectResponse(url=f"/api/bundles/{bundle_id}/label", status_code=303)


@router.post("/generate-package-label/{package_id}")
def gen_package_label(package_id: int, _: User = Depends(require_permissions(*PRODUCTION_READ_PERMISSIONS))):
    return RedirectResponse(url=f"/api/packages/{package_id}/label", status_code=303)
