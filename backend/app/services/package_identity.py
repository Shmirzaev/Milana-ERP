"""Warehouse and dispatch resolve physical packages, not receiving groups."""

import re

from sqlalchemy import or_

from app.models import Package, PackageBarcodeAlias


def scan_candidates(code):
    code = code.strip()
    payload = code.split(":", 1)[1] if code.upper().startswith("PACKAGE:") else code
    return list(dict.fromkeys([code, *(part.strip() for part in payload.split("|") if part.strip())]))


def physical_legacy_qr(code):
    return re.fullmatch(r"uzerp_ii_\d+_\d+", code) is not None


def resolve_warehouse_package(db, code):
    candidates = scan_candidates(code)
    direct_rows = db.query(Package.id, Package.barcode).filter(
        or_(Package.barcode.in_(candidates), Package.package_no.in_(candidates)),
    ).all()
    direct = {pid for pid, _ in direct_rows}
    physical = {candidate for candidate in candidates if physical_legacy_qr(candidate)}
    if physical - {barcode for _, barcode in direct_rows}:
        return None, bool(direct)
    # A suffix identifies a physical sticker. Consolidation aliases must never
    # substitute a different package, even if it is attached to the shipment.
    alias_codes = [candidate for candidate in candidates if not physical_legacy_qr(candidate)]
    aliases = {
        pid for (pid,) in db.query(PackageBarcodeAlias.package_id)
        .join(Package, Package.id == PackageBarcodeAlias.package_id)
        .filter(PackageBarcodeAlias.code.in_(alias_codes)).all()
    } if alias_codes else set()
    matches = direct | aliases
    return (next(iter(matches)) if len(matches) == 1 else None), len(matches) > 1
