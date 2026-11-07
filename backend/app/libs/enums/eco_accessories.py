"""Approval lifecycle for ECO production accessory requirements."""
from enum import StrEnum


class EcoAccessoryStatus(StrEnum):
    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    ISSUED = "issued"
