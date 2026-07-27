from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import RedirectResponse

from app.core.deps import DbSession, CurrentUser, PRODUCTION_READ_PERMISSIONS, require_permissions
from app.models import Bundle, Package, User

router = APIRouter(prefix="/barcode", tags=["barcode"])


@router.get("/bundle/{bundle_no}")
def bundle_qr(bundle_no: str, db: DbSession, _: CurrentUser):
    b = db.query(Bundle).filter(Bundle.bundle_no == bundle_no).first()
    if not b: raise HTTPException(404, "Bundle not found")
    return {"qr_code_url": b.qr_code_url, "barcode": b.barcode, "bundle_no": b.bundle_no}


@router.get("/package/{package_no}")
def package_qr(package_no: str, db: DbSession, _: CurrentUser):
    p = db.query(Package).filter(Package.package_no == package_no).first()
    if not p: raise HTTPException(404, "Package not found")
    return {"qr_code_url": p.qr_code_url, "barcode": p.barcode, "package_no": p.package_no}


@router.post("/generate-bundle-label/{bundle_id}")
def gen_bundle_label(bundle_id: int, _: User = Depends(require_permissions(*PRODUCTION_READ_PERMISSIONS))):
    return RedirectResponse(url=f"/api/bundles/{bundle_id}/label", status_code=303)


@router.post("/generate-package-label/{package_id}")
def gen_package_label(package_id: int, _: User = Depends(require_permissions(*PRODUCTION_READ_PERMISSIONS))):
    return RedirectResponse(url=f"/api/packages/{package_id}/label", status_code=303)
