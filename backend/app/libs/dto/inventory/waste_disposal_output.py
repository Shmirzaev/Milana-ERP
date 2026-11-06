"""Waste disposal response contract."""

from datetime import datetime
from typing import Optional

from app.libs.dto.common import ORMModel
from app.libs.enums.inventory import WasteDisposalRequestStatus


class WasteDisposalOut(ORMModel):
    id: int
    waste_record_id: int
    reason: Optional[str] = None
    status: WasteDisposalRequestStatus
    requested_by: Optional[int] = None
    approved_by: Optional[int] = None
    approved_at: Optional[datetime] = None
    proof_file_url: Optional[str] = None
