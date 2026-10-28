export type SewingSize = { size: string; sewing_completed_quantity?: number };
export type SizeAllocation = {
  total: number;
  rows: { size: string; recorded: number; quantity: number | "" }[];
  suggested: boolean;
  valid: boolean;
  fingerprint: string;
};

// Keep the physical Sewing ledger unchanged. These are proposed label quantities.
// Callers supply sizes in garment order so remainder pieces are deterministic.
export function allocateLabelSizes(
  total: number,
  recordedSizes: SewingSize[],
  modelSizes: string[],
  draft?: { fingerprint: string; quantities: Record<string, number | ""> },
): SizeAllocation {
  const recorded = new Map<string, { size: string; quantity: number }>();
  for (const row of recordedSizes) {
    const size = row.size.trim();
    const quantity = Number(row.sewing_completed_quantity || 0);
    if (!size || !Number.isSafeInteger(quantity) || quantity < 0) continue;
    const key = size.toLowerCase();
    const previous = recorded.get(key);
    recorded.set(key, { size: previous?.size || size, quantity: (previous?.quantity || 0) + quantity });
  }
  const recordedTotal = [...recorded.values()].reduce((sum, row) => sum + row.quantity, 0);
  const remaining = Math.max(0, total - recordedTotal);
  const suggested = remaining > 0;
  const names = new Map<string, string>();
  if (suggested) for (const raw of modelSizes) {
    const size = raw.trim();
    if (size && size !== "-" && !names.has(size.toLowerCase())) names.set(size.toLowerCase(), size);
  }
  const targetKeys = [...names.keys()];
  for (const [key, row] of recorded) if (!names.has(key)) names.set(key, row.size);
  const rows = [...names].map(([key, size]) => {
    const index = targetKeys.indexOf(key);
    const extra = suggested && index >= 0
      ? Math.floor(remaining / targetKeys.length) + (index < remaining % targetKeys.length ? 1 : 0)
      : 0;
    const minimum = recorded.get(key)?.quantity || 0;
    return { size, recorded: minimum, quantity: minimum + extra as number | "" };
  });
  const fingerprint = JSON.stringify([total, rows.map(row => [row.size, row.recorded, row.quantity])]);
  if (suggested && draft?.fingerprint === fingerprint) {
    for (const row of rows) row.quantity = draft.quantities[row.size] ?? row.quantity;
  }
  const valid = Number.isSafeInteger(total) && total >= 0 && recordedTotal <= total
    && (!suggested || targetKeys.length > 0)
    && rows.every(row => row.quantity !== "" && Number.isSafeInteger(row.quantity) && row.quantity >= row.recorded)
    && rows.reduce((sum, row) => sum + Number(row.quantity), 0) === total;
  return { total, rows, suggested, valid, fingerprint };
}

export function allocationQuantity(allocation: SizeAllocation | undefined, size: string): number {
  if (!allocation?.valid) return 0;
  return Number(allocation.rows.find(row => row.size.toLowerCase() === size.toLowerCase())?.quantity || 0);
}

// A refreshed suggestion must not silently redistribute an already issued
// operation. UIDs end in size:copy; their prefix identifies its exact batch/line.
export function issuedSizeAllocationConflicts(
  proposed: { labelUid: string; quantity: number }[],
  issued: { label_uid: string; quantity: number; status: string }[],
): boolean {
  const prefix = (uid: string) => uid.split(":").slice(0, -2).join(":");
  const scopes = new Set(proposed.map(row => prefix(row.labelUid)));
  const quantities = new Map(proposed.map(row => [row.labelUid, row.quantity]));
  return issued.some(row => row.status !== "superseded" && scopes.has(prefix(row.label_uid))
    && quantities.get(row.label_uid) !== Number(row.quantity));
}
