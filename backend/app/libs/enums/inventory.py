"""Fixed inventory vocabularies: stock QC states and stock movement kinds.

Every member is the string this tree already stores in the database or returns
over the API. The persisted `String` columns, their rendered CHECK constraints
and the wire format are unchanged, and no migration was made or is needed.

Each class names one concept. A QC state and a movement kind are different
vocabularies and are kept apart.

Membership never grants permission and never authorizes a transition. The
services still own the legal states, the allowed inputs and the errors.
"""

from enum import Enum


class WarehouseType(str, Enum):
    """Source-recognized warehouse kinds; membership does not permit creation.

    RAW_MATERIAL and WAREHOUSE are legacy stock-adjustment lookup values.
    Historical rows may contain other values: unrestricted reads and the String
    mapping remain explicitly pending vocabulary reconciliation.
    """

    FABRIC_STORAGE = "fabric_storage"
    ACCESSORY_STORAGE = "accessory_storage"
    PACKAGING = "packaging"
    CUTTING = "cutting"
    ECO_COTTON_CUTTING = "eco_cotton_cutting"
    PRINTING = "printing"
    SEWING = "sewing"
    BESTTEX_PACKAGING = "besttex_packaging"
    ECO_COTTON_PACKAGING = "eco_cotton_packaging"
    FINISHED_GOODS = "finished_goods"
    WASTE = "waste"
    RAW_MATERIAL = "raw_material"
    WAREHOUSE = "warehouse"


class StockBatchQcStatus(str, Enum):
    """`stock_batches.qc_status` - the quality state of a received batch."""

    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    REJECTED = "rejected"
    HOLD = "hold"

    @classmethod
    def parse(cls, value: object) -> "StockBatchQcStatus | None":
        """Map a raw request value to the canonical member.

        A canonical member is returned unchanged and `None` stays `None`, so an
        explicitly cleared optional field keeps its meaning. Any other value is
        trimmed and lower-cased before the lookup, so a client that sends
        `"PASSED"` still maps to the stored value. An unsupported value raises
        `ValueError`, which the request validator reports as a validation error.
        """
        if value is None or isinstance(value, cls):
            return value
        return cls(str(value).strip().lower())


class StockMovementType(str, Enum):
    """`stock_movements.movement_type` - the kind of stock movement.

    The full lifecycle is defined here so the storage vocabulary has one
    definition. Converting a caller to this enum is a separate operation;
    the other movement kinds keep their literal at their call sites until
    their own operation is converted.
    """

    RECEIVE = "receive"
    TRANSFER = "transfer"
    ISSUE = "issue"
    CONSUME = "consume"
    ADJUSTMENT = "adjustment"
    RETURN = "return"
    PRODUCE = "produce"
    WASTE = "waste"
    SHIPMENT = "shipment"
