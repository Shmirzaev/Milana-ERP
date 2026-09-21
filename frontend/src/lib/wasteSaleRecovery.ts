import { api } from "@/lib/api";

export type WasteSalePayload = {
  buyer_name: string;
  quantity: number;
  unit_price: number;
};

export type PendingWasteSale = {
  version: 1;
  key: string;
  payload: WasteSalePayload;
};

function storageKey(userId: number, wasteId: number): string {
  return `waste-sale:${userId}:${wasteId}`;
}

export function pendingWasteSale(userId: number, wasteId: number): PendingWasteSale | null {
  if (!userId || !wasteId || typeof sessionStorage === "undefined") return null;
  const raw = sessionStorage.getItem(storageKey(userId, wasteId));
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as PendingWasteSale;
    const payload = parsed?.payload;
    if (parsed?.version !== 1 || typeof parsed.key !== "string" || !parsed.key ||
        !payload || typeof payload.buyer_name !== "string" || !payload.buyer_name.trim() ||
        typeof payload.quantity !== "number" || !Number.isFinite(payload.quantity) || payload.quantity <= 0 ||
        typeof payload.unit_price !== "number" || !Number.isFinite(payload.unit_price) || payload.unit_price < 0) {
      throw new Error("invalid shape");
    }
    return parsed;
  } catch {
    throw new Error("Saved waste sale evidence is unreadable; do not submit another sale");
  }
}

function clearPendingWasteSale(userId: number, wasteId: number, key: string): void {
  const current = pendingWasteSale(userId, wasteId);
  if (current?.key === key) sessionStorage.removeItem(storageKey(userId, wasteId));
}

export async function postWasteSale<T>(
  userId: number,
  wasteId: number,
  payload: WasteSalePayload,
): Promise<T> {
  if (!userId) throw new Error("Sign in before recording a waste sale");
  const existing = pendingWasteSale(userId, wasteId);
  if (existing && JSON.stringify(existing.payload) !== JSON.stringify(payload)) {
    throw new Error("Retry the saved waste sale before changing its values");
  }
  const pending: PendingWasteSale = existing ?? {
    version: 1,
    key: crypto.randomUUID(),
    payload: JSON.parse(JSON.stringify(payload)) as WasteSalePayload,
  };
  if (!existing) sessionStorage.setItem(storageKey(userId, wasteId), JSON.stringify(pending));

  try {
    const result = await api.postWithIdempotency<T>(
      `/api/waste/${wasteId}/sell`, pending.payload, pending.key, 60_000,
    );
    clearPendingWasteSale(userId, wasteId, pending.key);
    return result;
  } catch (error: unknown) {
    // A first definitive rejection proves that no sale was committed. Once an
    // outcome was uncertain, later errors cannot safely discard its identity.
    const message = error && typeof error === "object" && "message" in error
      ? String(error.message)
      : String(error);
    if (!existing && /^(400|401|403|404|409|422):/.test(message)) {
      clearPendingWasteSale(userId, wasteId, pending.key);
    }
    throw error;
  }
}
