"""Canonical finished-goods status, in the existing database CHECK order."""
from enum import Enum


class FinishedGoodsStatus(str, Enum):
    AVAILABLE = "available"
    RESERVED = "reserved"
    SOLD = "sold"
    DAMAGED = "damaged"


class ShipmentStatus(str, Enum):
    DRAFT = "draft"
    CREATED = "created"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
