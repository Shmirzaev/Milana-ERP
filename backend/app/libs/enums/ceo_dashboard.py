from enum import Enum


class ReportGrouping(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class FactoryFilter(str, Enum):
    ALL = "ALL"
    MIL = "MIL"
    BST = "BST"
    ECO = "ECO"


class ProductionStage(str, Enum):
    CUTTING = "cutting"
    PRINTING = "printing"
    SEWING = "sewing"
    PACKAGING = "packaging"


class BalanceStatus(str, Enum):
    CURRENT = "current"
    SNAPSHOT = "snapshot"
    UNAVAILABLE = "unavailable"
