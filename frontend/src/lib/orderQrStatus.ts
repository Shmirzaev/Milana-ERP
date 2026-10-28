export type OrderQrStatusOrderOption = {
  order_no: string;
  sales_order_nos: string[];
  production_nos: string[];
  model_codes: string[];
  label_count: number;
};

export type OrderQrStatusCell = {
  size: string;
  issued_labels: number;
  scanned_labels: number;
  available_labels: number;
  issued_quantity: number | string;
  scanned_quantity: number | string;
  available_quantity: number | string;
};

export type OrderQrStatusOperation = {
  operation_section: string | null;
  operation_code: string | null;
  operation_name: string;
  cells: OrderQrStatusCell[];
  issued_labels: number;
  scanned_labels: number;
  available_labels: number;
  issued_quantity: number | string;
  scanned_quantity: number | string;
  available_quantity: number | string;
};

export type OrderQrStatusLabel = {
  id: number;
  label_uid: string;
  qr_token: string;
  production_no: string | null;
  sales_order_no: string | null;
  batch_no: string | null;
  model_code: string | null;
  operation_code: string | null;
  operation_name: string | null;
  sewing_line_code: string | null;
  sewing_line_name: string | null;
  cutting_passport_no: string | null;
  size: string | null;
  copy_index: number;
  quantity: number | string;
  status: "available" | "scanned";
  employee_name: string | null;
  payroll_status: string | null;
  issued_at: string;
  last_scanned_at: string | null;
  returned_at: string | null;
  return_count: number;
};

export type OrderQrStatusResponse = {
  order_no: string;
  sales_order_nos: string[];
  production_nos: string[];
  model_codes: string[];
  batch_nos: string[];
  sizes: string[];
  operations: OrderQrStatusOperation[];
  items: OrderQrStatusLabel[];
  total: number;
  offset: number;
  limit: number;
  total_labels: number;
  scanned_labels: number;
  available_labels: number;
  total_quantity: number | string;
  scanned_quantity: number | string;
  available_quantity: number | string;
};
