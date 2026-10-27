"""Material reservation request contracts."""

from typing import Annotated, Literal, Optional
from contextvars import ContextVar

from pydantic import BaseModel, Field, PrivateAttr, model_validator
from pydantic_core import core_schema, to_jsonable_python

from app.libs.enums.inventory import MaterialReservationType
from app.libs.dto.inventory.reservation_type_selection import DeferredReservationType, reservation_type_selection

_capture_type: ContextVar[list[str] | None] = ContextVar("reservation_type_capture", default=None)


def _canonical_type(raw: object) -> MaterialReservationType | None:
    selection = reservation_type_selection(raw)
    return selection if isinstance(selection, MaterialReservationType) else None


def _unvalidated_type(raw: object) -> MaterialReservationType | None:
    # model_copy, model_construct and assignment bypass Pydantic validation.
    # Do not eagerly coerce an arbitrary object before legacy domain checks.
    if type(raw) is str or isinstance(raw, MaterialReservationType):
        return _canonical_type(raw)
    return None


class _DeferredReservationType:
    @classmethod
    def __get_pydantic_core_schema__(cls, source_type, handler):
        def canonical(raw: str) -> MaterialReservationType | None:
            capture = _capture_type.get()
            if capture is not None:
                capture.append(raw)
            return _canonical_type(raw)
        return core_schema.no_info_after_validator_function(canonical, core_schema.str_schema())


class MaterialReservationIn(BaseModel):
    production_order_id: int
    item_id: int
    stock_batch_id: Optional[int] = None
    warehouse_id: Optional[int] = None
    reserved_quantity: float = Field(
        gt=0, le=9_999_999_999.9999, allow_inf_nan=False,
    )
    unit: str
    reservation_type: Annotated[MaterialReservationType | None, _DeferredReservationType] = MaterialReservationType.MATERIAL
    notes: Optional[str] = None
    _raw_reservation_type: object = PrivateAttr(default="material")

    @model_validator(mode="wrap")
    @classmethod
    def _retain_raw_type(cls, values, handler):
        captured: list[str] = []
        token = _capture_type.set(captured)
        try:
            result = handler(values)
            if captured:
                result._raw_reservation_type = captured[-1]
            return result
        finally:
            _capture_type.reset(token)

    def model_post_init(self, context):
        # model_construct deliberately bypasses validation, as it did on the old DTO.
        raw = self.reservation_type if "reservation_type" in self.model_fields_set else "material"
        self._raw_reservation_type = raw
        if "reservation_type" in self.model_fields_set:
            super().__setattr__("reservation_type", _unvalidated_type(raw))

    def __setattr__(self, name, value):
        if name == "reservation_type" and self.__pydantic_private__ is not None:
            super().__setattr__(name, _unvalidated_type(value))
            self._raw_reservation_type = value
        else:
            super().__setattr__(name, value)

    def model_copy(self, *, update=None, deep=False):
        if update is not None and "reservation_type" in update:
            raw = update["reservation_type"]
            update = {**update, "reservation_type": _unvalidated_type(raw)}
            copied = super().model_copy(update=update, deep=deep)
            copied._raw_reservation_type = raw
        else:
            copied = super().model_copy(update=update, deep=deep)
        return copied

    def copy(self, *, include=None, exclude=None, update=None, deep=False):
        copied = super().copy(include=include, exclude=exclude, update=update, deep=deep)
        if "reservation_type" in copied.__dict__:
            raw = (copied.__dict__["reservation_type"] if update is not None and "reservation_type" in update
                   else copied._raw_reservation_type)
            copied.__dict__["reservation_type"] = _unvalidated_type(raw)
            copied._raw_reservation_type = raw
        return copied

    def legacy_request_payload(self, *, mode: Literal["json", "python"] = "python") -> dict:
        payload = self.model_dump(mode=mode)
        raw = self._raw_reservation_type
        if "reservation_type" in payload:
            payload["reservation_type"] = to_jsonable_python(raw) if mode == "json" else raw
        return payload

    def reservation_type_selection(self) -> MaterialReservationType | DeferredReservationType:
        if "reservation_type" not in self.__dict__:
            return DeferredReservationType.FALLBACK
        return reservation_type_selection(self._raw_reservation_type)


class MaterialReservationAutoIn(BaseModel):
    production_order_id: int
    mode: Literal["shortage_only", "full_remaining"] = "full_remaining"
    reserve_accessories: bool = True
    reserve_materials: bool = True
    reserve_packaging: bool = True


class MaterialReservationConsumeIn(BaseModel):
    quantity: float = Field(
        gt=0, le=9_999_999_999.9999, allow_inf_nan=False,
    )
