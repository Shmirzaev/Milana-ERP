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

type WasteSaleStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;
type WasteSaleReconciliation<T> =
  | { status: "completed"; result: T }
  | { status: "completed_unavailable" }
  | { status: "cancelled" };

export class WasteSaleRecoveryError extends Error {
  constructor(public readonly code: "pending" | "storage" | "cancelled" | "completed_unavailable") {
    super(code);
  }
}

export const wasteSaleChangedEvent = "waste-sale-changed";

export function wasteSaleStorageKey(userId: number, wasteId: number): string {
  return `waste-sale:${userId}:${wasteId}`;
}

function notifyWasteSaleChanged(): void {
  if (typeof window !== "undefined") window.dispatchEvent(new Event(wasteSaleChangedEvent));
}

function parsePendingWasteSale(raw: string | null): PendingWasteSale | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as PendingWasteSale;
    const payload = parsed?.payload;
    if (parsed?.version !== 1 || typeof parsed.key !== "string"
        || !/^[A-Za-z0-9._:-]{1,128}$/.test(parsed.key)
        || !payload || typeof payload.buyer_name !== "string" || !payload.buyer_name.trim()
        || typeof payload.quantity !== "number" || !Number.isFinite(payload.quantity) || payload.quantity <= 0
        || typeof payload.unit_price !== "number" || !Number.isFinite(payload.unit_price) || payload.unit_price < 0) {
      throw new Error("invalid shape");
    }
    return parsed;
  } catch {
    // Never overwrite unreadable evidence: its request may already have
    // committed even though this browser can no longer decode the payload.
    throw new WasteSaleRecoveryError("storage");
  }
}

function readStoredSale(storage: WasteSaleStorage, key: string): PendingWasteSale | null {
  try {
    return parsePendingWasteSale(storage.getItem(key));
  } catch (error) {
    if (error instanceof WasteSaleRecoveryError) throw error;
    throw new WasteSaleRecoveryError("storage");
  }
}

function saleStorage(): { current: WasteSaleStorage; legacy: WasteSaleStorage } {
  if (typeof window === "undefined") throw new WasteSaleRecoveryError("storage");
  try {
    return { current: window.localStorage, legacy: window.sessionStorage };
  } catch {
    throw new WasteSaleRecoveryError("storage");
  }
}

function readSaleSources(userId: number, wasteId: number): {
  pending: PendingWasteSale | null;
  current: WasteSaleStorage;
  legacy: WasteSaleStorage;
  key: string;
} {
  const key = wasteSaleStorageKey(userId, wasteId);
  const { current, legacy } = saleStorage();
  const saved = readStoredSale(current, key);
  const legacySaved = readStoredSale(legacy, key);
  if (saved && legacySaved && (saved.key !== legacySaved.key
      || JSON.stringify(saved.payload) !== JSON.stringify(legacySaved.payload))) {
    throw new WasteSaleRecoveryError("storage");
  }
  return { pending: saved || legacySaved, current, legacy, key };
}

function saleLocks(): LockManager {
  const locks = globalThis.navigator?.locks;
  if (!locks) throw new WasteSaleRecoveryError("storage");
  return locks;
}

export function pendingWasteSale(userId: number, wasteId: number): PendingWasteSale | null {
  if (!userId || !wasteId || typeof window === "undefined") return null;
  return readSaleSources(userId, wasteId).pending;
}

async function preparePendingWasteSale(
  userId: number,
  wasteId: number,
  payload: WasteSalePayload,
): Promise<{ pending: PendingWasteSale; isNew: boolean }> {
  const key = wasteSaleStorageKey(userId, wasteId);
  return saleLocks().request(key, () => {
    const sources = readSaleSources(userId, wasteId);
    if (sources.pending) {
      if (JSON.stringify(sources.pending.payload) !== JSON.stringify(payload)) {
        throw new WasteSaleRecoveryError("pending");
      }
      let migrated = false;
      try {
        if (!readStoredSale(sources.current, key)) {
          sources.current.setItem(key, JSON.stringify(sources.pending));
          migrated = true;
        }
        if (readStoredSale(sources.legacy, key)) {
          sources.legacy.removeItem(key);
          migrated = true;
        }
      } catch {
        throw new WasteSaleRecoveryError("storage");
      }
      if (migrated) notifyWasteSaleChanged();
      return { pending: sources.pending, isNew: false };
    }

    const pending: PendingWasteSale = {
      version: 1,
      key: crypto.randomUUID(),
      payload: JSON.parse(JSON.stringify(payload)) as WasteSalePayload,
    };
    try {
      sources.current.setItem(key, JSON.stringify(pending));
    } catch {
      throw new WasteSaleRecoveryError("storage");
    }
    notifyWasteSaleChanged();
    return { pending, isNew: true };
  });
}

async function clearPendingWasteSale(userId: number, wasteId: number, requestKey: string): Promise<void> {
  const key = wasteSaleStorageKey(userId, wasteId);
  await saleLocks().request(key, () => {
    const sources = readSaleSources(userId, wasteId);
    if (sources.pending?.key !== requestKey) return;
    try {
      if (readStoredSale(sources.current, key)?.key === requestKey) sources.current.removeItem(key);
      if (readStoredSale(sources.legacy, key)?.key === requestKey) sources.legacy.removeItem(key);
    } catch {
      throw new WasteSaleRecoveryError("storage");
    }
    notifyWasteSaleChanged();
  });
}

function validReconciliation<T>(value: unknown): value is WasteSaleReconciliation<T> {
  if (!value || typeof value !== "object" || !("status" in value)) return false;
  const resolution = value as WasteSaleReconciliation<T>;
  return resolution.status === "cancelled" || resolution.status === "completed_unavailable"
    || (resolution.status === "completed" && resolution.result != null);
}

export async function postWasteSale<T>(
  userId: number,
  wasteId: number,
  payload: WasteSalePayload,
): Promise<T> {
  if (!userId) throw new Error("Sign in before recording a waste sale");
  const prepared = await preparePendingWasteSale(userId, wasteId, payload);
  const { pending } = prepared;

  if (!prepared.isNew) {
    const resolution = await api.postWithIdempotency<WasteSaleReconciliation<T>>(
      `/api/waste/${wasteId}/sell/reconcile`, pending.payload, pending.key, 60_000,
    );
    if (!validReconciliation<T>(resolution)) {
      throw new WasteSaleRecoveryError("storage");
    }
    await clearPendingWasteSale(userId, wasteId, pending.key);
    if (resolution.status === "completed") return resolution.result;
    throw new WasteSaleRecoveryError(resolution.status);
  }

  try {
    const result = await api.postWithIdempotency<T>(
      `/api/waste/${wasteId}/sell`, pending.payload, pending.key, 60_000,
    );
    await clearPendingWasteSale(userId, wasteId, pending.key);
    return result;
  } catch (error: unknown) {
    // Only a definitive first rejection proves that no sale was committed.
    // Uncertain outcomes retain the exact key and payload for reconciliation.
    const message = error && typeof error === "object" && "message" in error
      ? String(error.message)
      : String(error);
    if (/^(400|401|403|404|409|422):/.test(message)) {
      await clearPendingWasteSale(userId, wasteId, pending.key);
    }
    throw error;
  }
}
