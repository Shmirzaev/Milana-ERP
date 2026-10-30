"""Typed internal contracts used by production operation persistence."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TypedDict
from app.libs.enums.production import SewingOutputAssignmentTransitionStatus


class SewingSizeQuantity(TypedDict):
    size: str
    quantity: int


@dataclass(frozen=True)
class SewingOutputRecordValues:
    work_order_id: int
    production_batch_id: int | None
    sewing_assignment_id: int | None
    input_qty: int
    sewn_qty: int
    passed_qty: int
    failed_qty: int
    rework_qty: int
    rejected_qty: int
    size_quantities: list[SewingSizeQuantity]
    defect_reason: str | None
    line_name: str | None
    operator_id: int
    notes: str | None


@dataclass(frozen=True)
class SewingOutputAccounting:
    assignment_applied_qty: int
    actual_input_qty: int
    actual_output_qty: int
    passed_qty: int
    failed_qty: int
    rework_qty: int
    assignment_quantity: int | None = None
    assignment_completed_qty: int | None = None
    assignment_status: SewingOutputAssignmentTransitionStatus | None = None
    assignment_actual_start: datetime | None = None
    assignment_actual_end: datetime | None = None
