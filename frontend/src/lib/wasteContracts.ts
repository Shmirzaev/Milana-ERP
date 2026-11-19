/** Waste response vocabulary; free-form classifications and units remain data. */
export const WASTE_STATUSES = [
  "recorded", "received_by_waste_department", "pending_disposal_approval",
  "disposal_approved", "sold", "disposed",
] as const;

export type WasteStatus = (typeof WASTE_STATUSES)[number];

export type WasteRecord = {
  id: number;
  production_order_id: number | null;
  work_order_id: number | null;
  source_department_id: number | null;
  item_id: number | null;
  batch_id: number | null;
  waste_type: string;
  quantity: number;
  remaining_quantity: number | null;
  unit: string;
  reason: string | null;
  sellable: boolean;
  estimated_value: number;
  status: WasteStatus;
  created_at: string;
};
