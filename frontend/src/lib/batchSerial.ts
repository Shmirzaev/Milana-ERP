type BatchLike = {
  batch_index?: number | null;
  batch_no?: string | null;
  name?: string | null;
};

export function normalizeBatchSerial(value?: string | null): string {
  return String(value || "").trim().replace(/^BT-/i, "");
}

export function formatBatchSerial(batch: BatchLike, productionOrderId?: number | null): string {
  const stored = normalizeBatchSerial(batch?.batch_no);
  if (stored) return stored;
  const idx = Math.max(1, Number(batch?.batch_index || 1));
  const idxPart = String(idx).padStart(2, "0");
  const poId = Math.max(0, Number(productionOrderId || 0));
  if (poId > 0) {
    return `${String(poId).padStart(4, "0")}-${idxPart}`;
  }
  return idxPart;
}

export function formatBatchLabel(batch: BatchLike, productionOrderId?: number | null): string {
  const serial = formatBatchSerial(batch, productionOrderId);
  const name = String(batch?.name || "").trim();
  return name ? `${serial} - ${name}` : serial;
}
