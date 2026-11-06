/** Planning-owned vocabularies; keep parity with app.libs.enums.planning. */
export enum BrandedPlanningOrderType {
  CUSTOMER = "customer",
  MILANA = "milana",
  ECO_COTTON = "eco_cotton",
  BESTTEX = "besttex",
}

export enum BrandedPlanningOrderStatus {
  OPEN = "open",
  CLOSED = "closed",
  CANCELLED = "cancelled",
}

/** Derived history progress, distinct from persisted Production/WorkOrder status. */
export enum BrandedCuttingProgress {
  NOT_STARTED = "not_started",
  PARTIAL = "partial",
  COMPLETED = "completed",
}
