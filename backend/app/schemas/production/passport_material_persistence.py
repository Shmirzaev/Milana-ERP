"""Grouped passport JSON replacement in the caller's supplied transaction."""
from app.schemas.production.cutting_passport import CuttingPassport


def replace_grouped_passport_materials(passport: CuttingPassport, rows: list[dict], *, primary_changed: bool) -> None:
    passport.materials = rows
    if primary_changed:
        passport.lot_no = rows[0].get("lot_no")
        passport.fabric_type = rows[0].get("fabric_type")
