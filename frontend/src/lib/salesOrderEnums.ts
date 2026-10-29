/** Canonical stored/wire vocabularies from backend app/libs/enums/sales.py. */
export enum SalesOrderStatus {
  DRAFT = "draft",
  PENDING_SALES_APPROVAL = "pending_sales_approval",
  CONFIRMED = "confirmed",
  PLANNING = "planning",
  PLANNING_APPROVED = "planning_approved",
  IN_PRODUCTION = "in_production",
  PRODUCTION = "production",
  CUTTING = "cutting",
  PRINTING = "printing",
  SEWING = "sewing",
  PACKAGING = "packaging",
  STORAGE = "storage",
  READY_TO_SHIP = "ready_to_ship",
  READY = "ready",
  RESERVED = "reserved",
  SHIPPED = "shipped",
  DELIVERED = "delivered",
  CLOSED = "closed",
  CANCELLED = "cancelled",
}

export enum SalesOrderType {
  CLIENT_ORDER = "client_order",
  BRANDED_STOCK_SALE = "branded_stock_sale",
  BRANDED_STOCK = "branded_stock",
}

export enum SalesOrderItemSourceType {
  PRODUCE_NEW = "produce_new",
  FROM_STOCK = "from_stock",
  FIRST_GRADE = "first_grade",
}

// Membership is not action permission. The manual-shipment BRANDED_STOCK type
// exists in stored results, but is not offered by the sales creation screen.
export type SalesOrderCreateType = SalesOrderType.CLIENT_ORDER | SalesOrderType.BRANDED_STOCK_SALE;
export const SALES_ORDER_CREATE_TYPES: readonly SalesOrderCreateType[] = [
  SalesOrderType.CLIENT_ORDER,
  SalesOrderType.BRANDED_STOCK_SALE,
];

export function salesOrderCreateType(value: string): SalesOrderCreateType | null {
  return SALES_ORDER_CREATE_TYPES.find((member) => member === value) ?? null;
}
