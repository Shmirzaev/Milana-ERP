from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict

from app.schemas.common import ORMModel


class CuttingPassportIn(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    passport_no: str
    date: datetime
    production_order_id: Optional[int] = None
    operator_id: Optional[int] = None
    model_code: Optional[str] = None
    variant: Optional[str] = None
    mold_no: Optional[str] = None
    image_ref: Optional[str] = None
    operator_name_manual: Optional[str] = None
    fabric_type: Optional[str] = None
    has_print: bool = False
    order_no: Optional[str] = None
    lot_no: Optional[str] = None
    size_range: Optional[str] = None
    rolls_count: Optional[int] = None
    layer_weight_kg: Optional[float] = None
    total_layers: Optional[int] = None
    planned_kg: Optional[float] = None
    pieces: Optional[int] = None
    fabric_width_m: Optional[float] = None
    lay_length_m: Optional[float] = None
    gramage: Optional[float] = None
    waste_pct: Optional[float] = None
    beka_per_piece_kg: Optional[float] = None
    other_beka_per_piece_kg: Optional[float] = None
    scrap_kg: Optional[float] = None
    ribana_per_piece_kg: Optional[float] = None
    notes: Optional[str] = None


class CuttingPassportOut(ORMModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())
    id: int
    passport_no: str
    date: datetime
    created_at: datetime
    updated_at: datetime
    production_order_id: Optional[int] = None
    operator_id: Optional[int] = None
    model_code: Optional[str] = None
    variant: Optional[str] = None
    mold_no: Optional[str] = None
    image_ref: Optional[str] = None
    operator_name_manual: Optional[str] = None
    fabric_type: Optional[str] = None
    has_print: bool
    order_no: Optional[str] = None
    lot_no: Optional[str] = None
    size_range: Optional[str] = None
    rolls_count: Optional[int] = None
    layer_weight_kg: Optional[float] = None
    total_layers: Optional[int] = None
    planned_kg: Optional[float] = None
    pieces: Optional[int] = None
    fabric_width_m: Optional[float] = None
    lay_length_m: Optional[float] = None
    gramage: Optional[float] = None
    waste_pct: Optional[float] = None
    beka_per_piece_kg: Optional[float] = None
    other_beka_per_piece_kg: Optional[float] = None
    scrap_kg: Optional[float] = None
    ribana_per_piece_kg: Optional[float] = None
    notes: Optional[str] = None
    # Computed fields
    total_beka_kg: Optional[float] = None
    other_beka_kg: Optional[float] = None
    total_ribana_kg: Optional[float] = None
    actual_kg: Optional[float] = None
    pieces_per_layer: Optional[float] = None
    size_count: Optional[int] = None
    per_piece_weight_kg: Optional[float] = None
    theoretical_kg: Optional[float] = None
    actual_kg_per_piece: Optional[float] = None
    gross_kg_per_piece: Optional[float] = None
    # Joined fields
    production_order_no: Optional[str] = None
    model_name: Optional[str] = None
    model_image_url: Optional[str] = None
    operator_name: Optional[str] = None
