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
    cut_pieces: int
    passed_pieces: int
    created_at: datetime


class BesttexCuttingPageOut(BaseModel):
    items: list[BesttexCuttingRowOut]
    total: int
    page: int
    page_size: int
