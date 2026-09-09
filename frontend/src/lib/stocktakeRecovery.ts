export type PendingStocktakeScan = { id: string; code: string; createdAt: number };

export function stocktakePendingPrefix(userId: number, countId: number) {
  return `erp:stocktake:${userId}:${countId}:pending:v2:`;
}

/** One key per scan: another tab can append or acknowledge without replacing our queue. */
export function readStocktakePending(storage: Storage, prefix: string): PendingStocktakeScan[] {
  const scans: PendingStocktakeScan[] = [];
  for (let index = 0; index < storage.length; index++) {
    const key = storage.key(index);
    if (!key?.startsWith(prefix)) continue;
    const raw = storage.getItem(key);
    if (raw === null) continue;
    const scan: unknown = JSON.parse(raw);
    if (!scan || typeof scan !== "object" || !("id" in scan) || !("code" in scan) || !("createdAt" in scan)
      || typeof scan.id !== "string" || key !== prefix + scan.id || typeof scan.code !== "string"
      || !scan.code.trim() || scan.code.length > 512 || typeof scan.createdAt !== "number" || !Number.isFinite(scan.createdAt)) {
      throw new Error("Invalid saved stocktake scan");
    }
    scans.push(scan as PendingStocktakeScan);
  }
  return scans.sort((a, b) => a.createdAt - b.createdAt || a.id.localeCompare(b.id));
}

export function addStocktakePending(storage: Storage, prefix: string, scan: PendingStocktakeScan) {
  storage.setItem(prefix + scan.id, JSON.stringify(scan));
}

export function removeStocktakePending(storage: Storage, prefix: string, id: string) {
  storage.removeItem(prefix + id);
}

/** Migrate the previous tab-only queue without deleting it until every code is durable. */
export function migrateStocktakePending(storage: Storage, legacy: Storage, userId: number, countId: number) {
  const key = `erp:stocktake:${userId}:${countId}:pending`;
  const raw = legacy.getItem(key);
  if (!raw) return;
  const codes: unknown = JSON.parse(raw);
  if (!Array.isArray(codes) || !codes.every(code => typeof code === "string" && !!code.trim() && code.length <= 512)) {
    throw new Error("Invalid previous stocktake queue");
  }
  const prefix = stocktakePendingPrefix(userId, countId);
  codes.forEach((code: string, index: number) => {
    const id = `legacy:${index}:${encodeURIComponent(code)}`;
    if (!storage.getItem(prefix + id)) addStocktakePending(storage, prefix, { id, code, createdAt: index });
  });
  legacy.removeItem(key);
}

export function stocktakeSelectionKey(userId: number) {
  return `erp:stocktake:${userId}:selected`;
}

export function readStocktakeSelection(storage: Storage, userId: number): number | null {
  const raw = storage.getItem(stocktakeSelectionKey(userId));
  if (!raw || !/^\d+$/.test(raw)) return null;
  const id = Number(raw);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
}
