"""Read-only Cutting balances; unknown physical identities are never fabricated."""
from dataclasses import dataclass
from typing import Literal

from app.libs.enums.production import CuttingDepartmentCode, SewingFactoryCode


@dataclass(frozen=True)
class CuttingBalanceGroup:
    key: str
    order_id: int
    batch_id: int | None
    factory: SewingFactoryCode | Literal["UNASSIGNED"]
    department: CuttingDepartmentCode
    bundle_quantities: dict[int, int]
    work_order_ids: frozenset[int]
    pieces_min: int
    pieces_max: int
    bundles_min: int
    bundles_max: int
    batch_pieces_min: int
    batch_pieces_max: int
    partition_bounds: dict[str, tuple[int, int]]

    @property
    def pieces(self) -> int | None:
        return self.pieces_min if self.pieces_min == self.pieces_max else None

    @property
    def bundles(self) -> int | None:
        return self.bundles_min if self.bundles_min == self.bundles_max else None

    @property
    def adjusted(self) -> bool:
        return self.pieces_min != sum(self.bundle_quantities.values())

    def payload(self) -> dict:
        return {"key": self.key, "pieces": self.pieces, "pieces_min": self.pieces_min,
                "pieces_max": self.pieces_max, "bundles": self.bundles,
                "bundles_min": self.bundles_min, "bundles_max": self.bundles_max,
                "adjusted": self.adjusted, "source_bundles": len(self.bundle_quantities)}
