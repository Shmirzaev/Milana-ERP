from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr, model_validator

from app.libs.enums.catalog import (
    PaidOperationFactory,
    PaidOperationQuantityMode,
    PaidOperationSplitMode,
    PaidProcessSection,
    normalize_paid_operation_factory_value,
)

PaidOperationTextValue = StrictStr | StrictInt | StrictFloat
PaidOperationNumberValue = StrictStr | StrictInt | StrictFloat | Literal[""] | None
PaidOperationBooleanValue = bool | StrictInt | StrictFloat | StrictStr


class PaidOperationIn(BaseModel):
    """Typed request boundary for operation rows stored inside model JSON.

    Unknown keys remain supported because older imports and editor extensions
    carry row metadata that this API does not interpret.
    """

    model_config = ConfigDict(extra="allow")

    id: PaidOperationTextValue | None = None
    selected: PaidOperationBooleanValue | None = None
    section: PaidProcessSection | None = None
    code: PaidOperationTextValue | None = None
    name: PaidOperationTextValue | None = None
    operation_name: PaidOperationTextValue | None = None
    rate: PaidOperationTextValue | None = None
    sewingFactory: PaidOperationFactory | None = None
    legacySourceId: PaidOperationTextValue | None = None
    legacy_source_id: PaidOperationTextValue | None = None
    sourceOrder: PaidOperationNumberValue | None = None
    source_order: PaidOperationNumberValue | None = None
    sequence: PaidOperationNumberValue | None = None
    duration: PaidOperationTextValue | None = None
    operation_duration: PaidOperationTextValue | None = None
    currency: PaidOperationTextValue | None = None
    sourceStage: PaidOperationTextValue | None = None
    source_stage: PaidOperationTextValue | None = None
    originalStage: PaidOperationTextValue | None = None
    original_stage: PaidOperationTextValue | None = None
    stage: PaidOperationTextValue | None = None
    changeDirection: PaidOperationTextValue | None = None
    change_direction: PaidOperationTextValue | None = None
    controlChangeDirection: PaidOperationTextValue | None = None
    control_change_direction: PaidOperationTextValue | None = None
    finalOperation: PaidOperationBooleanValue | None = None
    final_operation: PaidOperationBooleanValue | None = None
    final: PaidOperationBooleanValue | None = None
    quantityMode: PaidOperationQuantityMode | None = None
    quantity_mode: PaidOperationQuantityMode | None = None
    customQuantity: PaidOperationNumberValue | None = None
    custom_quantity: PaidOperationNumberValue | None = None
    copies: PaidOperationNumberValue | None = None
    splitMode: PaidOperationSplitMode | None = None
    split_mode: PaidOperationSplitMode | None = None
    splitQuantities: list[PaidOperationNumberValue] | None = None
    split_quantities: list[PaidOperationNumberValue] | None = None

    @model_validator(mode="before")
    @classmethod
    def accept_known_legacy_spellings(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        row = dict(value)
        factory_source = cls._factory_source_from_raw(row)
        normalized_factory = cls._normalized_factory_value(factory_source)
        # Factory aliases retain their historical typed-field adapter and
        # factory metadata keys. Other recognized aliases are typed fields in
        # their own right and remain byte-for-byte wire keys in the JSON row.
        if "sewingFactory" not in row:
            alias = next((key for key in ("sewing_factory", "factory") if key in row), None)
            if alias is not None:
                row["sewingFactory"] = row[alias]
        factory = row.get("sewingFactory")
        if isinstance(factory, str) and normalized_factory is not None:
            row["sewingFactory"] = normalized_factory.value
        return row

    @staticmethod
    def _factory_source_from_raw(row: dict[str, Any]) -> Any:
        if "sewingFactory" in row:
            return row["sewingFactory"]
        if "sewing_factory" in row:
            return row["sewing_factory"]
        if "factory" in row:
            return row["factory"]
        return row.get("company")

    @staticmethod
    def _normalized_factory_value(value: Any) -> PaidOperationFactory | None:
        return normalize_paid_operation_factory_value(value)

    @property
    def factory_was_explicit(self) -> bool:
        extra = self.__pydantic_extra__ or {}
        values = [self.sewingFactory if "sewingFactory" in self.model_fields_set else None]
        values.extend(extra.get(key) for key in ("sewing_factory", "factory"))
        return any(value not in (None, "") for value in values)

    @property
    def resolved_factory_hint(self) -> PaidOperationFactory | None:
        extra = self.__pydantic_extra__ or {}
        if "sewingFactory" in self.model_fields_set:
            value = self.sewingFactory
            return value if isinstance(value, PaidOperationFactory) else None
        for key in ("sewing_factory", "factory", "company"):
            if key in extra:
                return self._normalized_factory_value(extra[key])
        return None


class ModelIn(BaseModel):
    code: str
    automatic_model_prefix: Optional[str] = Field(default=None, min_length=2, max_length=2)
    name: str
    category: Optional[str] = None
    description: Optional[str] = None
    brand_id: Optional[int] = None
    collection_id: Optional[int] = None
    product_type: Optional[str] = None
    season: Optional[str] = None
    constructor_employee_id: Optional[int] = None
    designer_employee_id: Optional[int] = None
    details_json: Optional[dict] = None
    status: str = "draft"
    sam_minutes: float = 0



class ModelDetailsUpdateIn(BaseModel):
    """PATCH details with typed operation rows and open unrelated metadata."""

    model_config = ConfigDict(extra="allow")

    paid_operations: list[PaidOperationIn] | None = None
    paidOperations: list[PaidOperationIn] | None = None


class ModelUpdateIn(ModelIn):
    """PATCH contract; create remains intentionally opaque for model JSON."""

    details_json: ModelDetailsUpdateIn | None = None

    @property
    def paid_operations_update(self) -> list[PaidOperationIn] | None:
        details = self.details_json
        if details is None:
            return None
        if "paid_operations" in details.model_fields_set:
            return details.paid_operations
        if "paidOperations" in details.model_fields_set:
            return details.paidOperations
        return None


class ModelPaidOperationsIn(BaseModel):
    paid_operations: list[PaidOperationIn] = Field(default_factory=list)
    sewing_factory: PaidOperationFactory | None = None


class ModelVariantCreateIn(BaseModel):
    variant_no: Optional[str] = Field(default=None, min_length=1, max_length=64)
    fabric_item_id: Optional[int] = Field(default=None, gt=0)
    color: Optional[str] = Field(default=None, max_length=128)
    picture_url: Optional[str] = None
    print_picture_url: Optional[str] = None
    # Accepted temporarily so older clients can be normalized to the batch's
    # master fabric item without retaining the physical batch on the model.
    stock_batch_id: Optional[int] = Field(default=None, gt=0)


class ModelVariantUpdateIn(ModelVariantCreateIn):
    variant_no: str = Field(min_length=1, max_length=64)
