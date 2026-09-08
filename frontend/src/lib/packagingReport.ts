export type PackagingReportRow = Record<string, string | number | null>;
export type PackagingReport = {
  from_date: string;
  to_date: string;
  packaging_department_code: string;
  entries: PackagingReportRow[];
  completed: PackagingReportRow[];
  daily: PackagingReportRow[];
  totals: { package_count: number; quantity: number };
};

export const packagingReportColumns = {
  entries: ["date", "passport", "order_no", "batch", "brand", "model_no", "variant_no", "category", "color", "sizes", "standards", "package_count", "quantity", "two_piece_quantity", "first_sort", "second_sort"],
  completed: ["date", "passport", "order_no", "batch", "brand", "model_no", "variant_no", "category", "planned_quantity", "packed_quantity", "damaged_quantity", "first_sort", "second_sort", "shortage", "balance", "notes"],
  daily: ["date", "package_count", "quantity", "two_piece_quantity", "first_sort", "second_sort", "cutting_defects"],
} as const;

export const packagingNumericColumns = new Set([
  "package_count", "quantity", "two_piece_quantity", "first_sort", "second_sort", "cutting_defects",
  "planned_quantity", "packed_quantity", "damaged_quantity", "shortage", "balance",
]);
