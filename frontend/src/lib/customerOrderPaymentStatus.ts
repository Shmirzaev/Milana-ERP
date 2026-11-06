/** Customer-facing order payment projection, matching the backend enum. */
export const CUSTOMER_ORDER_PAYMENT_STATUS = {
  PAID: "paid",
  PARTIAL: "partial",
  UNPAID: "unpaid",
  NO_INVOICE: "no_invoice",
  VOID: "void",
  CANCELLED: "cancelled",
} as const;

export type CustomerOrderPaymentStatus =
  (typeof CUSTOMER_ORDER_PAYMENT_STATUS)[keyof typeof CUSTOMER_ORDER_PAYMENT_STATUS];
