"""Authoritative paid Control classification, shared by scanning and correction."""
from collections.abc import Mapping

from app.schemas import PayrollQrLabel


def is_control_operation(value: PayrollQrLabel | Mapping[str, object]) -> bool:
    # Qualified names remain ordinary paid work even when a legacy code says QC.
    def field(name: str):
        return value.get(name) if isinstance(value, Mapping) else getattr(value, name, None)

    name = str(field("operation_name") or "").strip().casefold()
    code = str(field("operation_code") or "").strip().casefold()
    return (name or code) in {"control", "kontrol", "контроль", "nazorat", "qc"}
