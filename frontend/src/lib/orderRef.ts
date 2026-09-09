/** Compact business order labels only; stored references and QR values stay intact. */
export function formatOrderReference(value: unknown, fallback = "-"): string {
  const reference = String(value ?? "").trim();
  if (!reference) return fallback;
  const match = /^(SO|PO|USL|PR|PUR)-(?:\d{4}-)?(\d+)$/i.exec(reference);
  if (!match?.[1] || !match[2]) return reference;
  const number = Number(match[2]);
  // Never truncate large identifiers or make distinct numbers look identical.
  if (!Number.isSafeInteger(number) || number > 9999) return reference;
  return `${match[1].toUpperCase()}-${String(number).padStart(4, "0")}`;
}

export function formatOrderReferencesInText(value: string): string {
  return value.replace(/\b(?:SO|PO|USL|PR|PUR)-(?:\d{4}-)?\d+\b/gi, reference => formatOrderReference(reference));
}

export function orderReference(source: any, fallback = "-"): string {
  return formatOrderReference(rawOrderReference(source, fallback), fallback);
}

/** Use when prefilling persisted fields; presentation aliases must not replace identity. */
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
