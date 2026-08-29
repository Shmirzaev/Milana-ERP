export type ReportOption = {
  value: string;
  label: string;
};

export type SewingProductionReportRow = {
  id: number;
  scanned_at: string;
  employee_id: number;
  employee_no?: string | null;
  employee_name: string;
  barcode: string;
  sewing_line_code?: string | null;
  sewing_line_name?: string | null;
  cutting_reference?: string | null;
  production_no?: string | null;
  sales_order_no?: string | null;
  batch_no?: string | null;
  model_code?: string | null;
  product_name?: string | null;
  operation_code?: string | null;
  operation_name?: string | null;
  size?: string | null;
  quantity: number | string;
  rate_per_piece: number | string;
  total_amount: number | string;
  currency: string;
  status: string;
  factory_code?: string | null;
};

export type SewingProductionReportOptions = {
  employees: ReportOption[];
  operations: ReportOption[];
  sewing_lines: ReportOption[];
  models: ReportOption[];
  orders: ReportOption[];
  cutting_references: ReportOption[];
  sizes: ReportOption[];
};

export type SewingProductionReportResponse = {
  items: SewingProductionReportRow[];
  total: number;
  offset: number;
  limit: number;
  total_quantity: number | string;
  total_amount: number | string;
  currency: string;
  options: SewingProductionReportOptions;
};

export type SewingProductionReportFilters = {
  dateFrom: string;
  dateTo: string;
  employeeId: string;
  orderNo: string;
  cuttingReference: string;
  modelCode: string;
  sewingLine: string;
  operation: string;
  barcode: string;
  size: string;
  factoryCode: string;
  status: string;
};

export function buildSewingReportParams(
  filters: SewingProductionReportFilters,
  page: number,
  pageSize: number,
): URLSearchParams {
  const params = new URLSearchParams({
    status: filters.status || "active",
    limit: String(pageSize),
    offset: String(Math.max(0, page - 1) * pageSize),
  });
  if (filters.dateFrom) params.set("date_from", new Date(filters.dateFrom).toISOString());
  if (filters.dateTo) params.set("date_to", new Date(filters.dateTo).toISOString());
  if (filters.employeeId) params.set("employee_id", filters.employeeId);
  if (filters.orderNo.trim()) params.set("order_no", filters.orderNo.trim());
  if (filters.cuttingReference.trim()) params.set("cutting_reference", filters.cuttingReference.trim());
  if (filters.modelCode) params.set("model_code", filters.modelCode);
  if (filters.sewingLine) params.set("sewing_line", filters.sewingLine);
  if (filters.operation) params.set("operation", filters.operation);
  if (filters.barcode.trim()) params.set("barcode", filters.barcode.trim());
  if (filters.size.trim()) params.set("size", filters.size.trim());
  if (filters.factoryCode) params.set("factory_code", filters.factoryCode);
  return params;
}
