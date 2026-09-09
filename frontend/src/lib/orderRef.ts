/** Display the authoritative reference returned by the server after renumbering. */
export function formatOrderReference(value: unknown, fallback = "-"): string {
  const reference = String(value ?? "").trim();
  // A legacy suffix is not an identity: the migration may reassign collisions.
  // Only the backend's persisted mapping can decide the canonical number.
  return reference || fallback;
}

export function formatOrderReferencesInText(value: string): string {
  return value;
}

export function orderReference(source: any, fallback = "-"): string {
  return formatOrderReference(rawOrderReference(source, fallback), fallback);
}

/** Prefer business references from the API when prefilling fields or grouping rows. */
export function rawOrderReference(source: any, fallback = "-"): string {
  if (!source) return fallback;
  const ref =
    source.order_no
    || source.sales_order_no
    || source.production_no
    || source.orderNo
    || source.salesOrderNo
    || source.productionNo;
  if (ref) return String(ref).trim();
  if (source.sales_order_id != null) return `#${source.sales_order_id}`;
  if (source.production_order_id != null) return `#${source.production_order_id}`;
  if (source.id != null) return `#${source.id}`;
  return fallback;
}
