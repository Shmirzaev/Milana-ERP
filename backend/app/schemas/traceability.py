from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class TraceabilityResponse(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    generated_at: str
    subject_type: str
    subject_id: int | None = None
    company: dict[str, Any]
    production_order: dict[str, Any] | None = None
    production_batch: dict[str, Any] | None = None
    current_process: dict[str, Any] | None = None
    quantity_summary: dict[str, Any] | None = None
    stage_summary: list[dict[str, Any]] = []
    sales_order: dict[str, Any] | None = None
    customer: dict[str, Any] | None = None
    brand: dict[str, Any] | None = None
    collection: dict[str, Any] | None = None
    model: dict[str, Any] | None = None
    color_size_quantities: list[dict[str, Any]] = []
    material_batches: list[dict[str, Any]] = []
    material_usage: list[dict[str, Any]] = []
    accessory_usage: list[dict[str, Any]] = []
    accessory_scope: str | None = None
    cutting_records: list[dict[str, Any]] = []
    bundles: list[dict[str, Any]] = []
    printing_records: list[dict[str, Any]] = []
    sewing_records: list[dict[str, Any]] = []
    quality_checks: list[dict[str, Any]] = []
    packaging_records: list[dict[str, Any]] = []
    waste_summary: list[dict[str, Any]] = []
    package: dict[str, Any] | None = None
    packages: list[dict[str, Any]] = []
    package_items: list[dict[str, Any]] = []
    package_scan_history: list[dict[str, Any]] = []
    warehouse_location: dict[str, Any] | None = None
    shipment: dict[str, Any] | None = None
    shipments: list[dict[str, Any]] = []
    shipment_packages: list[dict[str, Any]] = []
    shipment_package_scan_logs: list[dict[str, Any]] = []
    delivery_status: dict[str, Any] | None = None
    audit_summary: dict[str, Any] | None = None
    gaps: list[str] = []
    trace_gap: bool = False
