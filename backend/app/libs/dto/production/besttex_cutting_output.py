from datetime import datetime

from pydantic import BaseModel, ConfigDict


class BesttexCuttingRowOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    cutting_record_id: int
    cutting_batch_no: str | None
    production_no: str
    order_no: str
    batch_no: str | None
    model_code: str | None
    model_name: str | None
    planning_order_id: int | None = None
    planning_order_no: str | None = None
    planning_order_name: str | None = None
    model_no: str | None = None
    variant_no: str | None = None
    model_image_url: str | None = None
    variant_image_url: str | None = None
    size_summary: str | None = None
    material_label: str | None = None
    deadline: datetime | None = None
    cut_pieces: int
    passed_pieces: int
    created_at: datetime


class BesttexCuttingPageOut(BaseModel):
    items: list[BesttexCuttingRowOut]
    total: int
    page: int
    page_size: int
