"""Stock batch receipt request contract."""

from decimal import Decimal
from typing import Annotated, Any, Optional

from pydantic import BaseModel, BeforeValidator, Field, PrivateAttr, field_serializer, model_validator

from app.libs.dto.common import StoredUnitCost
from app.libs.enums.inventory import StockBatchQcStatus


class StockBatchIn(BaseModel):
    roll_lengths_m: list[Annotated[float, Field(ge=0.001, lt=100000000000, allow_inf_nan=False)] | None] = Field(default_factory=list, max_length=1000)
    length_m: Optional[float] = Field(default=None, gt=0, lt=100000000000, allow_inf_nan=False)
    item_id: int
    batch_no: str
    supplier_id: Optional[int] = None
    color: Optional[str] = None
    old_code: Optional[str] = None
    color_code: Optional[str] = None
    color_status: Optional[str] = None
    order_no: Optional[str] = None
    width: Optional[float] = None
    gsm: Optional[float] = None
    quantity: float = Field(
        gt=0, le=9_999_999_999.9999, allow_inf_nan=False,
    )
    piece_count: Optional[int] = None
    roll_weights_kg: list[float] = Field(default_factory=list)
    processes: Optional[str] = None
    unit: str
    cost_per_unit: StoredUnitCost = Decimal("0")
    image_url: Optional[str] = None
    warehouse_id: int
    qc_status: Annotated[StockBatchQcStatus, BeforeValidator(StockBatchQcStatus.parse)] = StockBatchQcStatus.PENDING

    _raw_qc_status: Optional[str] = PrivateAttr(default=None)

    @model_validator(mode="wrap")
    @classmethod
    def _keep_raw_qc_status(cls, data: Any, handler) -> "StockBatchIn":
        """Keep the `qc_status` request text next to the normalized member.

        `qc_status` was a free-form string before this field became an enum, so
        the recorded idempotency hashes were built from the text the client
        sent. The text is read here, before the field validator normalizes it,
        so a retry of such a request can still reproduce its recorded hash.
        The contract itself keeps exposing the canonical value.
        """
        raw = data.get("qc_status") if isinstance(data, dict) else None
        model = handler(data)
        if isinstance(raw, StockBatchQcStatus):
            model._raw_qc_status = raw.value
        elif isinstance(raw, str):
            model._raw_qc_status = raw
        return model

    @property
    def raw_qc_status(self) -> Optional[str]:
        """The `qc_status` text exactly as it was received, or None if omitted."""
        return self._raw_qc_status

    @field_serializer("cost_per_unit", when_used="json")
    def serialize_cost_per_unit(self, value: Decimal) -> float | int:
        # Existing receipt idempotency records fingerprint float request costs,
        # including integer zero when the original float default was omitted.
        return float(value) if "cost_per_unit" in self.model_fields_set else 0
