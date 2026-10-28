import type { InvoiceStatus } from "./invoiceStatus";

/** POST /api/finance/invoices: the existing InvoiceOut JSON response. */
export type InvoiceIssueResponse = {
  id: number;
  sales_order_id: number;
  invoice_no: string;
  amount: number;
  status: InvoiceStatus;
  issued_at: string | null;
  due_date: string | null;
};
