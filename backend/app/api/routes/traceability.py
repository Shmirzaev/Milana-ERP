from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import case, or_
from sqlalchemy.orm import load_only
from urllib.parse import parse_qs, unquote, urlparse

from app.core.deps import DbSession, require_permissions
from app.core.order_reference import resolve_order_id
from app.services.bundles import find_bundle_by_scanned_code
from app.models import Bundle, Package, ProductionBatch, ProductionOrder, Shipment
from app.services.traceability import (
    bundle_traceability,
    package_traceability,
    passport_html,
    production_batch_traceability,
    production_order_traceability,
    shipment_traceability,
)

router = APIRouter(prefix="/traceability", tags=["traceability"])


def _package_lookup(db: DbSession):
    return db.query(Package).options(load_only(
        Package.id,
        Package.package_no,
        Package.barcode,
        Package.qr_code_url,
        Package.production_order_id,
        Package.production_batch_id,
        Package.sales_order_id,
        Package.brand_id,
        Package.collection_id,
        Package.model_id,
        Package.color,
        Package.package_type,
        Package.total_quantity,
        Package.capacity,
        Package.weight_kg,
        Package.warehouse_id,
        Package.storage_cell,
        Package.storage_shelf,
        Package.storage_placed_at,
        Package.status,
        Package.packed_at,
        Package.received_at,
        Package.shipped_at,
        Package.created_at,
    ))


def _decode(value: str) -> str:
    return unquote(str(value or "").strip())


def _package_lookup_candidates(raw_code: str) -> list[str]:
    code = _decode(raw_code)
    if not code:
        return []
    candidates = [code]
    if "|" in code:
        candidates.extend([part.strip() for part in code.split("|") if part.strip()])
    if code.upper().startswith("PACKAGE:"):
        payload = code.split(":", 1)[1]
        candidates.extend([part.strip() for part in payload.split("|") if part.strip()])
    return list(dict.fromkeys([candidate for candidate in candidates if candidate]))


def _find_package(db: DbSession, key: str) -> Package | None:
    decoded = _decode(key)
    candidates = _package_lookup_candidates(decoded)
    rank_cases = []
    conditions = []
    if decoded.isdigit():
        package_id = int(decoded)
        conditions.append(Package.id == package_id)
        rank_cases.append((Package.id == package_id, 0))
    for rank, candidate in enumerate(candidates, start=1):
        barcode_match = Package.barcode == candidate
        package_no_match = Package.package_no == candidate
        conditions.extend((barcode_match, package_no_match))
        rank_cases.extend(((barcode_match, rank), (package_no_match, rank)))
    if not conditions:
        return None
    return (
        _package_lookup(db)
        .filter(or_(*conditions))
        .order_by(case(*rank_cases, else_=len(candidates) + 1), Package.id.asc())
        .first()
    )


def _find_bundle(db: DbSession, key: str) -> Bundle | None:
    decoded = _decode(key)
    if decoded.isdigit():
        bundle = db.get(Bundle, int(decoded))
        if bundle:
            return bundle
    return find_bundle_by_scanned_code(db, decoded)


def _find_production_order(db: DbSession, key: str) -> ProductionOrder | None:
    decoded = _decode(key)
    if decoded.isdigit():
        po = db.get(ProductionOrder, int(decoded))
        if po:
            return po
    order_id = resolve_order_id(db, "PO", decoded)
    return db.get(ProductionOrder, order_id) if order_id is not None else None


def _find_production_batch(db: DbSession, key: str) -> ProductionBatch | None:
    decoded = _decode(key)
    if not decoded:
        return None
    try:
        parsed = urlparse(decoded)
        query_batch = (parse_qs(parsed.query).get("batch") or [None])[0]
        if query_batch:
            decoded = str(query_batch).strip()
    except ValueError:
        pass

    candidates = [decoded]
    if "|" in decoded:
        candidates.extend(part.strip() for part in decoded.split("|") if part.strip())
    for candidate in dict.fromkeys(candidates):
        upper = candidate.upper()
        if upper.startswith("BATCH_ID:"):
            candidate = candidate.split(":", 1)[1].strip()
        if candidate.isdigit():
            batch = db.get(ProductionBatch, int(candidate))
            if batch:
                return batch
    for candidate in dict.fromkeys(candidates):
        if candidate.upper().startswith("BATCH:"):
            candidate = candidate.split(":", 1)[1].strip()
        batch = (
            db.query(ProductionBatch)
            .filter(ProductionBatch.batch_no == candidate)
            .order_by(ProductionBatch.id.desc())
            .first()
        )
        if batch:
            return batch
    return None


def _find_shipment(db: DbSession, key: str) -> Shipment | None:
    decoded = _decode(key)
    query = db.query(Shipment).options(load_only(
        Shipment.id,
        Shipment.shipment_no,
        Shipment.status,
        Shipment.sales_order_id,
        Shipment.customer_id,
        Shipment.shipped_at,
        Shipment.delivered_at,
        Shipment.created_at,
        Shipment.notes,
    ))
    if decoded.isdigit():
        shipment = query.filter(Shipment.id == int(decoded)).first()
        if shipment:
            return shipment
    return query.filter(Shipment.shipment_no == decoded).first()


@router.get("/package/barcode/{barcode}")
def get_package_by_barcode(
    barcode: str,
    db: DbSession,
    _: object = Depends(require_permissions("traceability.view", "*")),
):
    pkg = _find_package(db, barcode)
    if not pkg:
        raise HTTPException(404, "Package not found")
    return package_traceability(db, pkg)


@router.get("/package/{package_id}")
def get_package_traceability(
    package_id: str,
    db: DbSession,
    _: object = Depends(require_permissions("traceability.view", "*")),
):
    pkg = _find_package(db, package_id)
    if not pkg:
        raise HTTPException(404, "Package not found")
    return package_traceability(db, pkg)


@router.get("/bundle/{bundle_id}")
def get_bundle_traceability(
    bundle_id: str,
    db: DbSession,
    _: object = Depends(require_permissions("traceability.view", "*")),
):
    bundle = _find_bundle(db, bundle_id)
    if not bundle:
        raise HTTPException(404, "Bundle not found")
    return bundle_traceability(db, bundle)


@router.get("/production-order/{production_order_id}")
def get_production_order_traceability(
    production_order_id: str,
    db: DbSession,
    _: object = Depends(require_permissions("traceability.view", "*")),
):
    po = _find_production_order(db, production_order_id)
    if not po:
        raise HTTPException(404, "Production order not found")
    return production_order_traceability(db, po)


@router.get("/production-batch/{batch_id}")
def get_production_batch_traceability(
    batch_id: str,
    db: DbSession,
    _: object = Depends(require_permissions("traceability.view", "*")),
):
    batch = _find_production_batch(db, batch_id)
    if not batch:
        raise HTTPException(404, "Production batch not found")
    try:
        return production_batch_traceability(db, batch)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@router.get("/shipment/{shipment_id}")
def get_shipment_traceability(
    shipment_id: str,
    db: DbSession,
    _: object = Depends(require_permissions("traceability.view", "*")),
):
    shipment = _find_shipment(db, shipment_id)
    if not shipment:
        raise HTTPException(404, "Shipment not found")
    return shipment_traceability(db, shipment)


@router.get("/export/package/{package_id}", response_class=HTMLResponse)
def export_package_traceability(
    package_id: str,
    db: DbSession,
    _: object = Depends(require_permissions("traceability.export", "*")),
):
    pkg = _find_package(db, package_id)
    if not pkg:
        raise HTTPException(404, "Package not found")
    data = package_traceability(db, pkg)
    return passport_html(data, title=f"Product Passport {pkg.package_no}")


@router.get("/export/shipment/{shipment_id}", response_class=HTMLResponse)
def export_shipment_traceability(
    shipment_id: str,
    db: DbSession,
    _: object = Depends(require_permissions("traceability.export", "*")),
):
    shipment = _find_shipment(db, shipment_id)
    if not shipment:
        raise HTTPException(404, "Shipment not found")
    data = shipment_traceability(db, shipment)
    return passport_html(data, title=f"Shipment Traceability {shipment.shipment_no}")
