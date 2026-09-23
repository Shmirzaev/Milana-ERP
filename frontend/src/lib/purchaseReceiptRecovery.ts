export type PurchaseReceiptScope = { userId: number; factoryCode: string };
export type PurchaseReceiptPayload = {
  supplier_id: number | null;
  close_order: boolean;
  lines: [{
    purchase_order_line_id: number;
    received_quantity: number;
    batch_no: string;
    warehouse_id: number;
    cost_per_unit: number;
    piece_count: number | null;
    roll_weights_kg: number[];
  }];
};
export type PendingPurchaseReceipt = {
  version: 1;
  key: string;
  orderId: number;
  payload: PurchaseReceiptPayload;
};
type ReceiptStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export class PurchaseReceiptRecoveryError extends Error {
  constructor(public readonly code: "pending" | "storage" | "completed_unavailable") {
    super(code);
  }
}

export type PurchaseReceiptReconciliation<T> =
  | { status: "completed"; result: T }
  | { status: "completed_unavailable" }
  | { status: "cancelled" };

export function purchaseReceiptStorageKey(scope: PurchaseReceiptScope): string {
  return `milana:purchase-receipt:v1:${scope.factoryCode}:${scope.userId}`;
}

export function readPendingPurchaseReceipt(storage: ReceiptStorage, scope: PurchaseReceiptScope): PendingPurchaseReceipt | null {
  try {
    const raw = storage.getItem(purchaseReceiptStorageKey(scope));
    if (!raw) return null;
    const saved = JSON.parse(raw) as PendingPurchaseReceipt;
    const line = saved?.payload?.lines?.[0];
    if (saved?.version !== 1 || !Number.isInteger(saved.orderId) || saved.orderId <= 0
      || typeof saved.key !== "string" || !/^[A-Za-z0-9._:-]{1,128}$/.test(saved.key)
      || saved.payload?.lines?.length !== 1 || !line || !Number.isInteger(line.purchase_order_line_id)
      || !Number.isFinite(line.received_quantity) || line.received_quantity <= 0
      || typeof line.batch_no !== "string" || !Number.isInteger(line.warehouse_id)
      || !Number.isFinite(line.cost_per_unit) || !Array.isArray(line.roll_weights_kg)
      || typeof saved.payload.close_order !== "boolean") {
      throw new Error("Invalid pending receipt");
    }
    return saved;
  } catch {
    // Preserve unreadable data: silently replacing it could duplicate a receipt.
    throw new PurchaseReceiptRecoveryError("storage");
  }
}

export async function preparePurchaseReceipt(
  storage: ReceiptStorage, scope: PurchaseReceiptScope, orderId: number, payload: PurchaseReceiptPayload,
): Promise<{ pending: PendingPurchaseReceipt; isNew: boolean }> {
  // localStorage operations are individually atomic, not the read/create pair.
  // All tabs must share a lock so concurrent submissions reuse one request key.
  const locks = globalThis.navigator?.locks;
  if (!locks) throw new PurchaseReceiptRecoveryError("storage");
  return locks.request(purchaseReceiptStorageKey(scope), () =>
    prepareStoredPurchaseReceipt(storage, scope, orderId, payload));
}

function prepareStoredPurchaseReceipt(
  storage: ReceiptStorage, scope: PurchaseReceiptScope, orderId: number, payload: PurchaseReceiptPayload,
): { pending: PendingPurchaseReceipt; isNew: boolean } {
  const existing = readPendingPurchaseReceipt(storage, scope);
  if (existing) {
    if (existing.orderId !== orderId || JSON.stringify(existing.payload) !== JSON.stringify(payload)) {
      throw new PurchaseReceiptRecoveryError("pending");
    }
    return { pending: existing, isNew: false };
  }
  const pending: PendingPurchaseReceipt = {
    version: 1, key: crypto.randomUUID(), orderId, payload: JSON.parse(JSON.stringify(payload)),
  };
  try {
    storage.setItem(purchaseReceiptStorageKey(scope), JSON.stringify(pending));
  } catch {
    // Do not send a receipt that cannot be recovered after a reload.
    throw new PurchaseReceiptRecoveryError("storage");
  }
  return { pending, isNew: true };
}

async function clearPendingReceipt(storage: ReceiptStorage, scope: PurchaseReceiptScope, key: string) {
  const locks = globalThis.navigator?.locks;
  if (!locks) throw new PurchaseReceiptRecoveryError("storage");
  try {
    await locks.request(purchaseReceiptStorageKey(scope), () => {
      if (readPendingPurchaseReceipt(storage, scope)?.key === key) {
        storage.removeItem(purchaseReceiptStorageKey(scope));
      }
    });
  } catch {
    throw new PurchaseReceiptRecoveryError("storage");
  }
}

export async function reconcilePendingPurchaseReceipt<T>(
  storage: ReceiptStorage,
  scope: PurchaseReceiptScope,
  pending: PendingPurchaseReceipt,
  reconcile: (pending: PendingPurchaseReceipt) => Promise<PurchaseReceiptReconciliation<T>>,
): Promise<PurchaseReceiptReconciliation<T>> {
  const resolution = await reconcile(pending);
  if (!resolution || !["completed", "completed_unavailable", "cancelled"].includes(resolution.status)
    || (resolution.status === "completed" && resolution.result == null)
    || (resolution.status === "completed_unavailable" && "result" in resolution)) {
    throw new Error("Receipt reconciliation returned an invalid status");
  }
  await clearPendingReceipt(storage, scope, pending.key);
  return resolution;
}

export async function sendPreparedPurchaseReceipt<T>(
  storage: ReceiptStorage,
  scope: PurchaseReceiptScope,
  prepared: { pending: PendingPurchaseReceipt; isNew: boolean },
  send: (pending: PendingPurchaseReceipt) => Promise<T>,
  reconcile?: (pending: PendingPurchaseReceipt) => Promise<PurchaseReceiptReconciliation<T>>,
): Promise<T> {
  let response: T;
  try {
    response = await send(prepared.pending);
  } catch (error) {
    // Only a definitive first rejection permits editing and a new request key.
    // After any uncertain attempt/reload, even a later 4xx cannot undo a commit.
    if (prepared.isNew && error instanceof Error && /^(400|404|409|422):/.test(error.message)) {
      await clearPendingReceipt(storage, scope, prepared.pending.key);
    } else if (!prepared.isNew && reconcile && error instanceof Error
      && /^(400|403|404|409|410|422):/.test(error.message)) {
      // The server serializes reconciliation with the original receipt. It
      // either replays the committed result or tombstones the unused key so a
      // delayed original cannot apply after corrected values are submitted.
      const resolution = await reconcilePendingPurchaseReceipt(
        storage,
        scope,
        prepared.pending,
        reconcile,
      );
      if (resolution.status === "completed") return resolution.result;
      if (resolution.status === "completed_unavailable") {
        throw new PurchaseReceiptRecoveryError("completed_unavailable");
      }
    }
    throw error;
  }
  await clearPendingReceipt(storage, scope, prepared.pending.key);
  return response;
}
