from decimal import Decimal
from typing import Annotated

from pydantic import Field

# Storage bound for purchase and receipt quantities. Matches the bound already
# used by the cutting and passport quantity inputs, so a quantity that is
# individually in range still cannot overflow its column once receipts
# accumulate; the service re-checks the running total against this value.
MAX_PURCHASE_QUANTITY = Decimal("9999999999.9999")

PurchaseQuantity = Annotated[
    Decimal,
    Field(gt=0, le=MAX_PURCHASE_QUANTITY, allow_inf_nan=False),
]
PurchaseReceiptQuantity = Annotated[
    float,
    Field(gt=0, le=float(MAX_PURCHASE_QUANTITY), allow_inf_nan=False),
]
