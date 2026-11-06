/**
 * Canonical stock batch QC vocabulary.
 *
 * The five values are exactly what the backend `StockBatchQcStatus` enum
 * stores and returns. Membership is not a UI policy: a screen may offer a
 * subset of these values and keeps its own subset and its own default.
 */

export enum InventoryQcStatus {
  PENDING = "pending",
  PASSED = "passed",
  FAILED = "failed",
  REJECTED = "rejected",
  HOLD = "hold",
}

/** Every canonical QC value, in the backend's order. */
export const INVENTORY_QC_STATUSES: readonly InventoryQcStatus[] = [
  InventoryQcStatus.PENDING,
  InventoryQcStatus.PASSED,
  InventoryQcStatus.FAILED,
  InventoryQcStatus.REJECTED,
  InventoryQcStatus.HOLD,
];

/**
 * The canonical value a select event carries, or `null` when the event value
 * is not one of them. A select offers a fixed set of options, so an
 * unexpected value leaves the form unchanged instead of entering it.
 */
export function inventoryQcStatus(value: string): InventoryQcStatus | null {
  const match = INVENTORY_QC_STATUSES.find((status) => String(status) === value);
  return match ?? null;
}
