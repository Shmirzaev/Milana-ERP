function normalizeOrderReference(value: unknown): string {
  const text = String(value ?? "").trim();
  if (text.toUpperCase().startsWith("PO-")) return `SO-${text.slice(3)}`;
  return text;
}

export function orderReference(source: any, fallback = "-"): string {
  if (!source) return fallback;
  const ref =
    source.order_no
    || source.sales_order_no
    || source.production_no
    || source.orderNo
    || source.salesOrderNo
    || source.productionNo;
  if (ref) return normalizeOrderReference(ref);
  if (source.sales_order_id != null) return `#${source.sales_order_id}`;
  if (source.production_order_id != null) return `#${source.production_order_id}`;
  if (source.id != null) return `#${source.id}`;
  return fallback;
}
