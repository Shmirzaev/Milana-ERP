"use client";
import { formatOrderReference } from "@/lib/orderRef";

import Link from "next/link";
import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import useSWRInfinite from "swr/infinite";
import { ArrowLeft, ChevronDown, ChevronRight, PackageCheck, X } from "lucide-react";
import PageHeader from "@/components/PageHeader";
import { useDialogs } from "@/components/DialogProvider";
import { api, fetcher } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { useT, type Lang } from "@/lib/i18n";
import { statusLabel } from "@/components/StagePipeline";
import { divideBatchQuantityByRollCount } from "@/lib/materialRollWeights";

type PurchaseOrderLine = {
  id: number;
  item_id: number;
  item_sku?: string | null;
  item_name?: string | null;
  ordered_quantity: number;
  received_quantity: number;
  remaining_quantity: number;
  unit: string;
  unit_cost: number;
  warehouse_id?: number | null;
  warehouse_name?: string | null;
  supplier_id?: number | null;
  supplier_name?: string | null;
  material_name?: string | null;
  photo_url?: string | null;
};

type PurchaseOrder = {
  id: number;
  po_no: string;
  request_no?: string | null;
  supplier_id?: number | null;
  supplier_name?: string | null;
  status: string;
  expected_date?: string | null;
  lines: PurchaseOrderLine[];
};

/** The orders route returns a page plus the exact filtered total. */
type PurchaseOrderPage = {
  items: PurchaseOrder[];
  total: number;
  limit: number;
  offset: number;
};

type Warehouse = {
  id: number;
  name: string;
  type?: string | null;
};

type ReceiveState = {
  order: PurchaseOrder;
  line: PurchaseOrderLine;
  received_quantity: string;
  piece_count: string;
  batch_no: string;
  warehouse_id: number;
  supplier_id: number;
  cost_per_unit: string;
  message: string;
  saving: boolean;
  // True when the form was restored from an unconfirmed receipt, so the next
  // submit replays the same key instead of creating a second receipt.
  retry: boolean;
  tone: "error" | "recoverable";
};

type SupplierOrderRow = {
  order: PurchaseOrder;
  line: PurchaseOrderLine;
};

type SupplierOrderGroup = {
  key: string;
  supplierName: string;
  rows: SupplierOrderRow[];
  totalOrderedKg: number;
};

const RECEIVABLE_ORDER_STATUSES = new Set(["sent", "approved", "partially_received"]);

function fmtQty(value: number | string | null | undefined) {
  const n = Number(value || 0);
  return Number.isFinite(n) ? n.toFixed(2) : "0.00";
}

function lineItemLabel(line: PurchaseOrderLine) {
  return [line.item_sku, line.item_name].filter(Boolean).join(" - ") || `#${line.item_id}`;
}

function isKilogramUnit(unit: string | null | undefined) {
  const normalizedUnit = String(unit || "").trim().toLowerCase().replaceAll(".", "");
  return ["kg", "kgs", "kilogram", "kilograms", "кг"].includes(normalizedUnit);
}

// Recovery copy lives here, like lib/packageWorkflow.ts, so the durable retry
// UI keeps all three languages without touching the shared dictionary.
const recoveryEn = {
  pendingTitle: "Unconfirmed purchase receipt",
  pendingBody: "A receipt for {label} was not confirmed. Retry it to avoid receiving the same goods twice.",
  retry: "Retry the saved receipt",
  retrying: "This receipt was not confirmed. Sending it again reuses the same receipt key, so the goods are received only once.",
  replayed: "This receipt was already recorded. The retry confirmed the same receipt, so stock was not added twice.",
  conflict: "This receipt was already sent with different values, so nothing was added. Correct the values and receive again; a new receipt key is used.",
};
type RecoveryCopy = Record<keyof typeof recoveryEn, string>;
const recoveryRu: RecoveryCopy = {
  pendingTitle: "Неподтверждённая приёмка закупки",
  pendingBody: "Приёмка по {label} не подтверждена. Повторите её, чтобы не принять один и тот же товар дважды.",
  retry: "Повторить сохранённую приёмку",
  retrying: "Эта приёмка не подтверждена. Повторная отправка использует тот же ключ приёмки, поэтому товар будет принят только один раз.",
  replayed: "Эта приёмка уже была записана. Повтор подтвердил ту же приёмку, поэтому остатки не увеличились дважды.",
  conflict: "Эта приёмка уже была отправлена с другими значениями, поэтому ничего не добавлено. Исправьте значения и примите снова; будет использован новый ключ приёмки.",
};
const recoveryUz: RecoveryCopy = {
  pendingTitle: "Tasdiqlanmagan xarid qabuli",
  pendingBody: "{label} bo‘yicha qabul tasdiqlanmagan. Bir xil tovarni ikki marta qabul qilmaslik uchun uni takrorlang.",
  retry: "Saqlangan qabulni takrorlash",
  retrying: "Bu qabul tasdiqlanmagan. Qayta yuborishda bir xil qabul kaliti ishlatiladi, shuning uchun tovar faqat bir marta qabul qilinadi.",
  replayed: "Bu qabul allaqachon saqlangan. Takrorlash shu qabulni tasdiqladi, shuning uchun qoldiq ikki marta oshilmadi.",
  conflict: "Bu qabul boshqa qiymatlar bilan allaqachon yuborilgan, shuning uchun hech narsa qo‘shilmadi. Qiymatlarni tuzatib, qayta qabul qiling; yangi qabul kaliti ishlatiladi.",
};
const recoveryCopy: Record<Lang, RecoveryCopy> = { en: recoveryEn, ru: recoveryRu, uz: recoveryUz };

function fillCopy(template: string, vars: Record<string, string | number>) {
  return template.replace(/\{(\w+)\}/g, (match, name: string) => (name in vars ? String(vars[name]) : match));
}

// The server accepts 1-128 characters of [A-Za-z0-9._:-] and scopes a key to
// factory + caller + order, so the key itself must never add a colliding
// dimension. The client record is keyed per order AND line: two lines of one
// order are two different receipts, not one.
const RECEIPT_KEY_PREFIX = "purchase-receipt";
const RECEIPT_KEY_PATTERN = /^[A-Za-z0-9._:-]{1,128}$/;
const DEFINITE_REJECTION = /^(400|401|403|404|409|422):/;

type PendingReceipt = { key: string; body: Record<string, any>; label: string; orderId: number; lineId: number };

// sessionStorage is the durable tier, so a reload can still retry with the same
// key. The map keeps the key stable for retries within one page load when
// storage is unavailable (private mode, blocked cookies).
const memoryPending = new Map<string, PendingReceipt>();

function receiptStorageKey(userId: number, orderId: number, lineId: number) {
  return `${RECEIPT_KEY_PREFIX}:${userId}:${orderId}:${lineId}`;
}

function readPendingReceipt(storageKey: string): PendingReceipt | null {
  try {
    const saved = sessionStorage.getItem(storageKey);
    if (saved) {
      const parsed = JSON.parse(saved);
      const key = String(parsed?.key || "");
      if (RECEIPT_KEY_PATTERN.test(key)) return { ...parsed, key };
    }
  } catch {}
  return memoryPending.get(storageKey) || null;
}

function writePendingReceipt(storageKey: string, pending: PendingReceipt) {
  memoryPending.set(storageKey, pending);
  try {
    sessionStorage.setItem(storageKey, JSON.stringify(pending));
  } catch {}
}

function clearPendingReceipt(storageKey: string) {
  memoryPending.delete(storageKey);
  try {
    sessionStorage.removeItem(storageKey);
  } catch {}
}

function pendingReceiptKeys(userId: number) {
  const prefix = `${RECEIPT_KEY_PREFIX}:${userId}:`;
  const keys = new Set<string>();
  for (const key of memoryPending.keys()) if (key.startsWith(prefix)) keys.add(key);
  try {
    for (let index = 0; index < sessionStorage.length; index += 1) {
      const key = sessionStorage.key(index);
      if (key?.startsWith(prefix)) keys.add(key);
    }
  } catch {}
  return Array.from(keys);
}

// Object key order must not decide whether a retry counts as unchanged; the
// server fingerprints its payload with sorted keys.
function stableStringify(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  if (value && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
      .map(([name, item]) => `${JSON.stringify(name)}:${stableStringify(item)}`);
    return `{${entries.join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

function newReceiptKey(): string | null {
  const random = typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}.${Math.random().toString(36).slice(2, 12)}`;
  const key = `rcpt-${random}`;
  return RECEIPT_KEY_PATTERN.test(key) ? key : null;
}

// Stable key on an unchanged retry, new key on any edit. Reusing a key with a
// changed body is a 409 on the server, which an operator cannot act on, so an
// edited receipt is a new key and therefore a genuinely new receipt.
function prepareReceipt(storageKey: string, body: Record<string, any>, meta: { orderId: number; lineId: number; label: string }) {
  const pending = readPendingReceipt(storageKey);
  if (pending && stableStringify(pending.body) === stableStringify(body)) {
    return { key: pending.key, wasPending: true };
  }
  const key = newReceiptKey();
  if (key) writePendingReceipt(storageKey, { key, body, ...meta });
  return { key, wasPending: false };
}

function StatusBadge({ status }: { status: string }) {
  const { t } = useT();
  const tone =
    status === "received"
      ? "border-emerald-200 bg-emerald-50 text-emerald-700"
      : status === "cancelled"
        ? "border-red-200 bg-red-50 text-red-700"
        : status === "partially_received"
          ? "border-amber-200 bg-amber-50 text-amber-700"
          : "border-[#ded9ca] bg-[#f7f4ed] text-[#56503f]";
  return <span className={`inline-flex rounded-md border px-2 py-1 text-xs font-medium ${tone}`}>{statusLabel(status, t)}</span>;
}

export default function PurchaseReceivingPage() {
  const { t, lang } = useT();
  const dialogs = useDialogs();
  const { me } = useMe();
  const canReceive = can(me, "purchasing.receive");
  const canView = can(me, "purchasing.view", "purchasing.receive");
  const userId = Number(me?.id || 0);
  const [message, setMessage] = useState("");
  const [receiveState, setReceiveState] = useState<ReceiveState | null>(null);
  const [pendingReceipts, setPendingReceipts] = useState<PendingReceipt[]>([]);
  const [collapsedSuppliers, setCollapsedSuppliers] = useState<Set<string>>(() => new Set());
  // Read after mount: sessionStorage is unavailable while server-rendering.
  const refreshPendingReceipts = useCallback(() => {
    if (!userId) {
      setPendingReceipts([]);
      return;
    }
    setPendingReceipts(
      pendingReceiptKeys(userId)
        .map((key) => readPendingReceipt(key))
        .filter((pending): pending is PendingReceipt => !!pending),
    );
  }, [userId]);
  useEffect(() => {
    refreshPendingReceipts();
  }, [refreshPendingReceipts]);
  const ORDER_PAGE_SIZE = 50;
  const {
    data: orderPages,
    mutate: refreshOrders,
    setSize: setOrderPageCount,
    size: orderPageCount,
  } = useSWRInfinite<PurchaseOrderPage>(
    (pageIndex) =>
      canView
        ? `/api/purchasing/orders?limit=${ORDER_PAGE_SIZE}&offset=${pageIndex * ORDER_PAGE_SIZE}`
        : null,
    fetcher,
  );
  // Pages ACCUMULATE rather than replace. `openPendingReceipt` resolves a saved
  // receipt out of this list, so a single page would silently fail to resume a
  // receipt for an order further down the directory.
  const orders = useMemo(
    () => (orderPages ?? []).flatMap((page) => page.items ?? []),
    [orderPages],
  );
  const ordersTotal = orderPages?.[0]?.total ?? 0;
  const hasMoreOrders = orders.length < ordersTotal;
  const isLoadingOrders = orderPageCount > (orderPages?.length ?? 0);
  const growOrders = useCallback(() => setOrderPageCount((count) => count + 1), [
    setOrderPageCount,
  ]);

  // A saved pending receipt can name an order that is not on the first page.
  // Grow the loaded window until every pending order is present, bounded, so
  // resuming a receipt never silently degrades into a recovery message.
  useEffect(() => {
    if (!canView || isLoadingOrders || !hasMoreOrders || pendingReceipts.length === 0) return;
    const missing = pendingReceipts.some(
      (pending) => !orders.some((order) => order.id === pending.orderId),
    );
    if (missing) growOrders();
  }, [canView, isLoadingOrders, hasMoreOrders, pendingReceipts, orders, growOrders]);
  const { data: warehouses } = useSWR<Warehouse[]>(canReceive ? "/api/inventory/warehouses" : null, fetcher);

  // The receive dialog only needs the suppliers these orders already name, so the whole
  // supplier directory is not fetched. Derived from `orders` rather than the receivable
  // queue on purpose: `openPendingReceipt` resolves its order out of `orders` and reopens
  // a saved receipt even for an order that is no longer receivable. Deriving from the
  // filtered queue would drop that supplier from the options and the select would fall
  // back to the placeholder, quietly sending a different supplier_id on retry.
  const supplierOptions = useMemo(() => {
    const options = new Map<number, string>();
    for (const order of orders || []) {
      for (const [supplierId, supplierName] of [
        [order.supplier_id, order.supplier_name],
        ...(order.lines || []).map((line) => [line.supplier_id, line.supplier_name] as const),
      ]) {
        const id = Number(supplierId || 0);
        if (id > 0 && !options.has(id)) options.set(id, String(supplierName || `#${id}`));
      }
    }
    return [...options.entries()]
      .map(([id, name]) => ({ id, name }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [orders]);

  const openOrders = useMemo(
    () => (orders || []).filter((order) => RECEIVABLE_ORDER_STATUSES.has(order.status) && order.lines.some((line) => Number(line.remaining_quantity || 0) > 0)),
    [orders],
  );
  const supplierOrderGroups = useMemo(() => {
    const groups = new Map<string, SupplierOrderGroup>();

    for (const order of openOrders) {
      for (const line of order.lines) {
        if (Number(line.remaining_quantity || 0) <= 0) continue;

        const supplierId = Number(line.supplier_id || order.supplier_id || 0);
        const supplierName = line.supplier_name || order.supplier_name || t("page.purchasing.unassignedSupplier");
        const key = supplierId > 0 ? `supplier:${supplierId}` : `supplier-name:${supplierName.trim().toLocaleLowerCase()}`;
        const group = groups.get(key) || {
          key,
          supplierName,
          rows: [],
          totalOrderedKg: 0,
        };

        group.rows.push({ order, line });
        if (isKilogramUnit(line.unit)) {
          group.totalOrderedKg += Number(line.ordered_quantity || 0);
        }
        groups.set(key, group);
      }
    }

    return Array.from(groups.values()).sort((left, right) => left.supplierName.localeCompare(right.supplierName));
  }, [openOrders, t]);
  const storageWarehouses = useMemo(
    () => (warehouses || []).filter((warehouse) => ["fabric_storage", "accessory_storage", "packaging"].includes(String(warehouse.type || ""))),
    [warehouses],
  );

  function toggleSupplierGroup(supplierKey: string) {
    setCollapsedSuppliers((current) => {
      const next = new Set(current);
      if (next.has(supplierKey)) {
        next.delete(supplierKey);
      } else {
        next.add(supplierKey);
      }
      return next;
    });
  }

  function openReceive(order: PurchaseOrder, line: PurchaseOrderLine) {
    setMessage("");
    const usesRollWeights = isKilogramUnit(line.unit);
    setReceiveState({
      order,
      line,
      received_quantity: usesRollWeights ? "" : String(Number(line.remaining_quantity || 0).toFixed(4)).replace(/\.?0+$/, ""),
      piece_count: "",
      batch_no: "",
      warehouse_id: Number(line.warehouse_id || storageWarehouses[0]?.id || 0),
      supplier_id: Number(line.supplier_id || order.supplier_id || 0),
      cost_per_unit: String(Number(line.unit_cost || 0)),
      message: "",
      saving: false,
      retry: false,
      tone: "error",
    });
  }

  // Reopen an unconfirmed receipt with its saved values, so the operator
  // submits the identical payload and the server replays it under the same key.
  function openPendingReceipt(pending: PendingReceipt) {
    const order = (orders || []).find((candidate) => candidate.id === pending.orderId);
    const line = order?.lines.find((candidate) => candidate.id === pending.lineId);
    if (!order || !line) {
      setMessage(fillCopy(recoveryCopy[lang].pendingBody, { label: pending.label }));
      return;
    }
    const savedLine = pending.body?.lines?.[0] || {};
    setMessage("");
    setReceiveState({
      order,
      line,
      received_quantity: savedLine.received_quantity != null ? String(savedLine.received_quantity) : "",
      piece_count: savedLine.piece_count != null ? String(savedLine.piece_count) : "",
      batch_no: String(savedLine.batch_no || ""),
      warehouse_id: Number(savedLine.warehouse_id || storageWarehouses[0]?.id || 0),
      supplier_id: Number(pending.body?.supplier_id || order.supplier_id || 0),
      cost_per_unit: String(savedLine.cost_per_unit ?? Number(line.unit_cost || 0)),
      message: "",
      saving: false,
      retry: true,
      tone: "recoverable",
    });
  }

  async function submitReceive(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!receiveState) return;
    const quantity = Number(receiveState.received_quantity || 0);
    const warehouseId = Number(receiveState.warehouse_id || 0);
    const cost = Number(receiveState.cost_per_unit || 0);
    const usesRollWeights = isKilogramUnit(receiveState.line.unit);
    const rollCount = Number(receiveState.piece_count || 0);
    if (usesRollWeights && (!Number.isInteger(rollCount) || rollCount <= 0)) {
      setReceiveState({ ...receiveState, message: t("page.inventory.rollWeightsRequired") });
      return;
    }
    if (!Number.isFinite(quantity) || quantity <= 0) {
      setReceiveState({ ...receiveState, message: t("page.purchasing.receiveQtyRequired") });
      return;
    }
    if (!warehouseId) {
      setReceiveState({ ...receiveState, message: t("page.purchasing.receiveWarehouseRequired") });
      return;
    }
    const receivedTotal = Number(receiveState.line.received_quantity || 0) + quantity;
    const orderedQuantity = Number(receiveState.line.ordered_quantity || 0);
    const remainingQuantity = Math.max(0, orderedQuantity - receivedTotal);
    const closeOrder = remainingQuantity > 0.000001
      ? await dialogs.ask({
          title: t("page.purchasing.closeShortReceiptTitle"),
          message: t("page.purchasing.closeShortReceiptMessage", {
            received: fmtQty(receivedTotal),
            ordered: fmtQty(orderedQuantity),
            remaining: fmtQty(remainingQuantity),
            unit: receiveState.line.unit,
          }),
          confirmText: t("page.purchasing.closeShortReceiptConfirm"),
          cancelText: t("page.purchasing.closeShortReceiptKeepOpen"),
        })
      : false;
    const rollWeights = usesRollWeights ? divideBatchQuantityByRollCount(quantity, rollCount) : [];
    const body = {
      supplier_id: receiveState.supplier_id || null,
      close_order: closeOrder,
      lines: [
        {
          purchase_order_line_id: receiveState.line.id,
          received_quantity: quantity,
          batch_no: receiveState.batch_no.trim(),
          warehouse_id: warehouseId,
          cost_per_unit: Number.isFinite(cost) ? cost : 0,
          piece_count: usesRollWeights ? rollCount : null,
          roll_weights_kg: rollWeights,
        },
      ],
    };
    const storageKey = receiptStorageKey(userId, receiveState.order.id, receiveState.line.id);
    const { key: receiptKey, wasPending } = prepareReceipt(storageKey, body, {
      orderId: receiveState.order.id,
      lineId: receiveState.line.id,
      label: `${formatOrderReference(receiveState.order.po_no)} - ${lineItemLabel(receiveState.line)}`,
    });
    setReceiveState({ ...receiveState, saving: true, message: "" });
    try {
      await api.postWithHeaders(`/api/purchasing/orders/${receiveState.order.id}/receive`, body, receiptKey ? { "Idempotency-Key": receiptKey } : undefined);
      clearPendingReceipt(storageKey);
      refreshPendingReceipts();
      refreshOrders();
      setReceiveState(null);
      // A replayed receipt is the same receipt, so it is reported as success
      // rather than as a duplicate or a failure.
      setMessage(wasPending ? recoveryCopy[lang].replayed : t("page.purchasing.received"));
    } catch (error: any) {
      const conflict = Number(error?.status) === 409 || String(error?.message || "").startsWith("409:");
      // A definite first rejection can be corrected freely. Once an earlier
      // outcome is uncertain, a later 4xx cannot prove that receipt failed, so
      // only a genuine conflict or a clean first rejection drops the saved key.
      if (conflict || (!wasPending && (DEFINITE_REJECTION.test(String(error?.message)) || [400, 401, 403, 404, 422].includes(Number(error?.status))))) {
        clearPendingReceipt(storageKey);
      }
      refreshPendingReceipts();
      setReceiveState((prev) => prev ? {
        ...prev,
        saving: false,
        retry: false,
        tone: conflict ? "recoverable" : "error",
        message: conflict ? recoveryCopy[lang].conflict : error?.message || t("page.purchasing.actionFailed"),
      } : prev);
    }
  }

  if (!canView) {
    return <PageHeader title={t("page.purchasing.receivingTitle")} subtitle={t("page.purchasing.noAccess")} />;
  }

  return (
    <div>
      <PageHeader
        title={t("page.purchasing.receivingTitle")}
        subtitle={t("page.purchasing.receivingSubtitle")}
        actions={(
          <Link className="btn" href="/purchasing">
            <ArrowLeft className="h-4 w-4" />
            {t("nav.purchaseRequests")}
          </Link>
        )}
      />
      {message && <div className="mb-4 rounded-md border border-[#ded9ca] bg-[#fbfaf6] px-4 py-3 text-sm text-[#56503f]">{message}</div>}

      {pendingReceipts.length > 0 && (
        <div role="status" className="mb-4 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <div className="font-semibold">{recoveryCopy[lang].pendingTitle}</div>
          <ul className="mt-2 space-y-2">
            {pendingReceipts.map((pending) => (
              <li key={pending.key} className="flex flex-wrap items-center justify-between gap-2">
                <span>{fillCopy(recoveryCopy[lang].pendingBody, { label: pending.label })}</span>
                <button type="button" className="btn whitespace-nowrap" onClick={() => openPendingReceipt(pending)} disabled={receiveState?.saving}>
                  {recoveryCopy[lang].retry}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <section className="card overflow-hidden">
        <div className="border-b border-[#ecebe3] px-5 py-4">
          <h2 className="app-card-title">{t("page.purchasing.pendingOrders")}</h2>
        </div>
        <div className="overflow-x-auto px-5 py-4">
          <table className="table">
            <thead>
              <tr>
                <th>{t("field.purchaseOrder")}</th>
                <th>{t("page.purchasing.photo")}</th>
                <th>{t("page.purchasing.materialName")}</th>
                <th>{t("field.supplier")}</th>
                <th>{t("page.purchasing.orderedQty")}</th>
                <th>{t("page.purchasing.expectedDate")}</th>
                <th>{t("common.status")}</th>
                <th></th>
              </tr>
            </thead>
            {supplierOrderGroups.map((group) => {
              const isCollapsed = collapsedSuppliers.has(group.key);
              const groupContentId = `supplier-orders-${group.key.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
              return (
                <Fragment key={group.key}>
                  <tbody>
                  <tr className="border-b border-[#ded9ca] bg-[#f7f4ed]">
                    <td colSpan={8} className="px-3 py-2.5">
                      <button
                        type="button"
                        className="flex w-full items-center gap-2 rounded-md px-1 py-1 text-left text-sm font-semibold text-[#14110b] hover:bg-[#efebdf] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#a89262]"
                        aria-expanded={!isCollapsed}
                        aria-controls={groupContentId}
                        aria-label={t(isCollapsed ? "page.purchasing.expandSupplier" : "page.purchasing.collapseSupplier", { supplier: group.supplierName })}
                        onClick={() => toggleSupplierGroup(group.key)}
                      >
                        {isCollapsed ? <ChevronRight className="h-4 w-4 shrink-0" /> : <ChevronDown className="h-4 w-4 shrink-0" />}
                        <span>{group.supplierName}</span>
                      </button>
                    </td>
                  </tr>
                  </tbody>
                  <tbody id={groupContentId} hidden={isCollapsed}>
                  {group.rows.map(({ order, line }) => (
                    <tr key={`${order.id}-${line.id}`}>
                      <td>
                        <div className="mono font-semibold text-[#14110b]">{formatOrderReference(order.po_no)}</div>
                        <div className="text-xs text-[#8a8472]">{formatOrderReference(order.supplier_name || order.request_no || "-")}</div>
                      </td>
                      <td>{line.photo_url ? (
                        <a
                          href={line.photo_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          aria-label={t("page.purchasing.openPhoto")}
                          className="inline-block rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#a89262]"
                        >
                          <img src={line.photo_url} alt="" className="h-[168px] w-[168px] rounded-md border border-[#ded9ca] object-cover" />
                        </a>
                      ) : <div className="h-[168px] w-[168px] rounded-md border border-[#ded9ca] bg-[#f7f4ed]" />}</td>
                      <td><div className="font-medium text-[#14110b]">{line.material_name || line.item_name || "-"}</div><div className="mono text-xs text-[#8a8472]">{line.item_sku || ""}</div></td>
                      <td>{line.supplier_name || order.supplier_name || "-"}</td>
                      <td className="mono">
                        {fmtQty(line.remaining_quantity)} / {fmtQty(line.ordered_quantity)} {line.unit}
                      </td>
                      <td>{order.expected_date ? new Date(order.expected_date).toLocaleDateString() : "-"}</td>
                      <td><StatusBadge status={order.status} /></td>
                      <td className="text-right">
                        {canReceive && (
                          <button type="button" className="btn btn-primary whitespace-nowrap" onClick={() => openReceive(order, line)}>
                            <PackageCheck className="h-4 w-4" />
                            {t("btn.receive")}
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                  <tr className="border-y border-[#ded9ca] bg-[#fbfaf6]">
                    <td colSpan={4} className="px-3 py-3 text-right text-sm font-semibold text-[#56503f]">
                      {t("page.purchasing.supplierTotalOrderedKg")}
                    </td>
                    <td className="mono px-3 py-3 font-semibold text-[#14110b]">{fmtQty(group.totalOrderedKg)} kg</td>
                    <td colSpan={3} />
                  </tr>
                  </tbody>
                </Fragment>
              );
            })}
            {supplierOrderGroups.length === 0 && (
              <tbody>
                <tr>
                  <td colSpan={8} className="text-sm text-slate-400">{t("page.purchasing.noOpenOrders")}</td>
                </tr>
              </tbody>
            )}
          </table>
          {hasMoreOrders && (
            <div className="flex flex-wrap items-center justify-center gap-3 border-t border-[#ecebe3] p-4">
              <span className="text-sm text-[#8a8472]">{orders.length} / {ordersTotal}</span>
              <button className="btn" type="button" onClick={growOrders} disabled={isLoadingOrders}>
                {t("common.loadMore")}
              </button>
            </div>
          )}
        </div>
      </section>

      {receiveState && (
        <div className="fixed inset-0 z-40 bg-black/40">
          <div className="absolute inset-0 overflow-y-auto p-4 md:p-6">
            <form onSubmit={submitReceive} className="card mx-auto w-full max-w-2xl p-5">
              <div className="mb-4 flex items-start justify-between gap-4">
                <div>
                  <div className="text-lg font-semibold text-[#14110b]">{t("page.purchasing.receiveOrder")}</div>
                  <div className="mt-1 text-sm text-[#6f684f]">{formatOrderReference(receiveState.order.po_no)} - {lineItemLabel(receiveState.line)}</div>
                </div>
                <button type="button" className="icon-btn" onClick={() => setReceiveState(null)} aria-label={t("common.close")}>
                  <X />
                </button>
              </div>

              {receiveState.retry && (
                <p role="status" className="mb-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                  {recoveryCopy[lang].retrying}
                </p>
              )}

              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <div>
                  <label className="label">{t("field.quantity")}</label>
                  <input
                    className="input"
                    type="number"
                    min={0}
                    step={isKilogramUnit(receiveState.line.unit) ? "0.01" : "0.0001"}
                    value={receiveState.received_quantity}
                    onChange={(event) => setReceiveState({ ...receiveState, received_quantity: event.target.value })}
                    required
                  />
                </div>
                <div>
                  <label className="label">{t("field.batchNo")}</label>
                  <input className="input" value={receiveState.batch_no} onChange={(event) => setReceiveState({ ...receiveState, batch_no: event.target.value })} required />
                </div>
                <div>
                  <label className="label">{t("field.internalBatchNo")}</label>
                  <input className="input" value={formatOrderReference(receiveState.order.po_no)} title={receiveState.order.po_no} readOnly aria-readonly="true" />
                </div>
                <div>
                  <label className="label">{t("field.warehouse")}</label>
                  <select className="input" value={receiveState.warehouse_id} onChange={(event) => setReceiveState({ ...receiveState, warehouse_id: Number(event.target.value) })} required>
                    <option value={0}>{t("ph.warehouse")}</option>
                    {storageWarehouses.map((warehouse) => (
                      <option key={warehouse.id} value={warehouse.id}>{warehouse.name}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="label">{t("field.supplier")}</label>
                  <select className="input" value={receiveState.supplier_id} onChange={(event) => setReceiveState({ ...receiveState, supplier_id: Number(event.target.value) })}>
                    <option value={0}>{t("ph.supplier")}</option>
                    {supplierOptions.map((supplier) => (
                      <option key={supplier.id} value={supplier.id}>{supplier.name}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="label">{`${t("field.cost")} / ${t("field.unit")}`}</label>
                  <input
                    className="input"
                    type="number"
                    min={0}
                    step="0.0001"
                    value={receiveState.cost_per_unit}
                    onChange={(event) => setReceiveState({ ...receiveState, cost_per_unit: event.target.value })}
                  />
                </div>
                {isKilogramUnit(receiveState.line.unit) && (
                  <div>
                    <label className="label">{t("field.pieceCount")}</label>
                    <input
                      className="input"
                      type="number"
                      min={1}
                      step={1}
                      value={receiveState.piece_count}
                      onChange={(event) => setReceiveState({ ...receiveState, piece_count: event.target.value })}
                      disabled={receiveState.saving}
                      required
                    />
                  </div>
                )}
              </div>
              {receiveState.message && (
                <div
                  role={receiveState.tone === "recoverable" ? "status" : "alert"}
                  className={`mt-3 text-sm ${receiveState.tone === "recoverable" ? "text-amber-700" : "text-red-600"}`}
                >
                  {receiveState.message}
                </div>
              )}
              <div className="mt-5 flex justify-end gap-2">
                <button type="button" className="btn" onClick={() => setReceiveState(null)} disabled={receiveState.saving}>{t("btn.cancel")}</button>
                <button className="btn btn-primary" disabled={receiveState.saving}>
                  {receiveState.saving ? t("common.saving") : t("btn.receive")}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
