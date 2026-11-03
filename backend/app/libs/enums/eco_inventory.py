"""Fixed vocabulary of the separately balanced Eco Cotton material ledger."""
from enum import Enum


class EcoMaterialKind(str, Enum):
    FABRIC = "fabric"
    ACCESSORY = "accessory"


class EcoMaterialMovementKind(str, Enum):
    RECEIVE = "receive"
    TRANSFER_RECEIPT = "transfer_receipt"
    CONSUME = "consume"
    ISSUE = "issue"


class FactoryFabricTransferStatus(str, Enum):
    IN_TRANSIT = "in_transit"
    PARTIALLY_RECEIVED = "partially_received"
    RECEIVED = "received"
