import type { SalesOrderCreateType, SalesOrderItemSourceType, SalesOrderStatus, SalesOrderType } from "./salesOrderEnums";

export type SalesOrderPrintingAttachment = {
  file_url: string;
  file_name?: string | null;
  content_type?: string | null;
};

export type SalesOrderItemInput = {
  model_id: number;
  brand_id?: number | null;
  collection_id?: number | null;
  color: string;
  size: string;
  quantity?: number | null;
  requested_pack_count?: number | null;
  unit_price?: number | null;
  printing_required?: boolean;
  // Omission intentionally preserves the backend's PRODUCE_NEW default.
  source_type?: SalesOrderItemSourceType;
  notes?: string | null;
};

export type SalesOrderCreateInput = {
  customer_id?: number | null;
  order_type: SalesOrderCreateType;
  deadline?: string | null;
  printing_instructions?: string | null;
  printing_attachments?: SalesOrderPrintingAttachment[];
  notes?: string | null;
  items: SalesOrderItemInput[];
};

export type SalesOrderSummary = {
  id: number;
  order_no: string;
  customer_id: number | null;
  customer_name?: string | null;
  order_type: SalesOrderType;
  status: SalesOrderStatus;
  deadline: string | null;
  total_amount: number;
  notes: string | null;
};

export type SalesOrderItem = {
  id: number;
  model_id: number;
  model_code?: string | null;
  model_name?: string | null;
  color: string;
  size: string;
  quantity: number;
  unit_price: number;
  source_type: SalesOrderItemSourceType;
  model?: { id: number; code: string; name: string; translations?: Record<string, string> | null } | null;
};

/** List-only stored piece total; unallocated pack lines contribute zero. */
export type SalesOrderListRow = SalesOrderSummary & { total_quantity: number };

export type SalesOrderDetail = SalesOrderSummary & {
  customer?: { id: number; name: string } | null;
  items: SalesOrderItem[];
  printing_instructions?: string | null;
  printing_attachments?: SalesOrderPrintingAttachment[] | null;
  planning_estimated_material_cost?: number | null;
  planning_estimated_labor_cost?: number | null;
  planning_estimated_electricity_cost?: number | null;
  planning_estimated_other_cost?: number | null;
  planning_estimated_net_cost?: number | null;
  planning_suggested_price_15?: number | null;
  planning_suggested_price_20?: number | null;
  planning_estimated_lead_time_minutes?: number | null;
  planning_estimate_comment?: string | null;
};
