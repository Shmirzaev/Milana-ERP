/**
 * Persisted invoice states, mirroring the backend `InvoiceStatus` enum.
 *
 * These are the stored `invoices.status` strings: unpaid, partially_paid,
 * paid, void and cancelled. The customer order-level payment summary is a
 * different projection (`partial`, `no_invoice`, ...) and is deliberately not
 * modelled here.
 */
export const INVOICE_STATUS = {
  UNPAID: "unpaid",
  PARTIALLY_PAID: "partially_paid",
  PAID: "paid",
  VOID: "void",
  CANCELLED: "cancelled",
} as const;

export type InvoiceStatus = (typeof INVOICE_STATUS)[keyof typeof INVOICE_STATUS];
