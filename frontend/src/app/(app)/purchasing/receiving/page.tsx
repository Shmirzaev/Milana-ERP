"use client";
import { formatOrderReference } from "@/lib/orderRef";

import Link from "next/link";
import { Fragment, useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";
import useSWRInfinite from "swr/infinite";
import { ArrowLeft, ChevronDown, ChevronRight, PackageCheck, X } from "lucide-react";
import PageHeader from "@/components/PageHeader";
import { useDialogs } from "@/components/DialogProvider";
import { api, fetcher } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { statusLabel } from "@/components/StagePipeline";
import { divideBatchQuantityByRollCount } from "@/lib/materialRollWeights";
import {
  PendingPurchaseReceipt, PurchaseReceiptPayload, PurchaseReceiptRecoveryError,
  preparePurchaseReceipt, readPendingPurchaseReceipt, reconcilePendingPurchaseReceipt,
  sendPreparedPurchaseReceipt,
} from "@/lib/purchaseReceiptRecovery";

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

type PurchaseOrderPage = {
  rows: PurchaseOrder[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
  supplier_totals: { key: string; total_ordered_kg: number }[];
};
const EMPTY_PURCHASE_ORDERS: PurchaseOrder[] = [];

type Warehouse = {
  id: number;
  name: string;
  type?: string | null;
};

type Supplier = {
  id: number;
  name: string;
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
  const { t } = useT();
  const dialogs = useDialogs();
  const { me } = useMe();
  const canReceive = can(me, "purchasing.receive");
  const canView = can(me, "purchasing.view", "purchasing.receive");
  const [message, setMessage] = useState("");
  const [receiveState, setReceiveState] = useState<ReceiveState | null>(null);
  const [pendingReceipt, setPendingReceipt] = useState<PendingPurchaseReceipt | null>(null);
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search.trim());
  const [recoveryStorageError, setRecoveryStorageError] = useState(false);
  const [recoveryBusy, setRecoveryBusy] = useState(false);
  const receiving = useRef(false);
  const receiptUserId = me?.id;
  const receiptFactory = me?.factory_code;
  const [collapsedSuppliers, setCollapsedSuppliers] = useState<Set<string>>(() => new Set());
  const {
    data: orderPages,
    size,
    setSize,
    mutate: refreshOrders,
    isValidating: ordersValidating,
  } = useSWRInfinite<PurchaseOrderPage>(
    (index, previousPage) => !canView || (previousPage && !previousPage.has_more)
      ? null
      : `/api/purchasing/orders?page=${index + 1}&page_size=50&receivable_only=true&q=${encodeURIComponent(deferredSearch)}`,
    fetcher,
    { persistSize: false },
  );
  const orders = useMemo(
    () => orderPages?.flatMap((page) => page.rows) ?? EMPTY_PURCHASE_ORDERS,
    [orderPages],
  );
  const totalOrders = orderPages?.[0]?.total ?? 0;
  const hasMoreOrders = orderPages?.at(-1)?.has_more ?? false;
  const supplierTotals = useMemo(
    () => new Map((orderPages ?? []).flatMap((page) => page.supplier_totals ?? []).map((entry) => [entry.key, entry.total_ordered_kg])),
    [orderPages],
  );
  const loadedPendingOrder = orders.find((order) => order.id === pendingReceipt?.orderId);
  const { data: targetedPendingOrders } = useSWR<PurchaseOrder[]>(
    canView && pendingReceipt && !loadedPendingOrder
      ? `/api/purchasing/orders?order_id=${pendingReceipt.orderId}`
      : null,
    fetcher,
  );
  const pendingOrder = loadedPendingOrder || targetedPendingOrders?.[0];
  const pendingLine = pendingOrder?.lines.find((line) => line.id === pendingReceipt?.payload.lines[0].purchase_order_line_id);
  const { data: warehouses } = useSWR<Warehouse[]>(canReceive ? "/api/inventory/warehouses" : null, fetcher);
  const { data: suppliers } = useSWR<Supplier[]>(canReceive ? "/api/suppliers" : null, fetcher);

  useEffect(() => {
    setReceiveState(null);
    setPendingReceipt(null);
    setRecoveryStorageError(false);
    if (!receiptUserId || !receiptFactory) return;
    const update = () => {
      try {
        setPendingReceipt(readPendingPurchaseReceipt(localStorage, { userId: receiptUserId, factoryCode: receiptFactory }));
      } catch {
        setRecoveryStorageError(true);
      }
    };
    update();
    window.addEventListener("storage", update);
    return () => window.removeEventListener("storage", update);
  }, [receiptUserId, receiptFactory]);

  const openOrders = useMemo(
    () => orders.filter((order) => RECEIVABLE_ORDER_STATUSES.has(order.status) && order.lines.some((line) => Number(line.remaining_quantity || 0) > 0)),
    [orders],
  );
  const supplierOrderGroups = useMemo(() => {
    const groups = new Map<string, SupplierOrderGroup>();

    for (const order of openOrders) {
      for (const line of order.lines) {
        if (Number(line.remaining_quantity || 0) <= 0) continue;

        const supplierId = Number(line.supplier_id || order.supplier_id || 0);
        const rawSupplierName = line.supplier_name || order.supplier_name || "";
        const supplierName = rawSupplierName || t("page.purchasing.unassignedSupplier");
        const key = supplierId > 0 ? `supplier:${supplierId}` : `supplier-name:${rawSupplierName.trim().toLowerCase()}`;
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

    for (const group of groups.values()) {
      group.totalOrderedKg = supplierTotals.get(group.key) ?? group.totalOrderedKg;
    }
    return Array.from(groups.values()).sort((left, right) => left.supplierName.localeCompare(right.supplierName));
  }, [openOrders, supplierTotals, t]);
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
    if (!me || receiving.current) return;
    let saved: PendingPurchaseReceipt | null;
    try {
      saved = readPendingPurchaseReceipt(localStorage, { userId: me.id, factoryCode: me.factory_code });
      setPendingReceipt(saved);
      setRecoveryStorageError(false);
    } catch {
      setRecoveryStorageError(true);
      return;
    }
    if (saved && (saved.orderId !== order.id || saved.payload.lines[0].purchase_order_line_id !== line.id)) {
      setMessage(t("page.purchasing.pendingReceipt"));
      return;
    }
    setMessage("");
    const usesRollWeights = isKilogramUnit(line.unit);
    const savedLine = saved?.payload.lines[0];
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
      ...(saved && savedLine ? {
        received_quantity: String(savedLine.received_quantity),
        piece_count: savedLine.piece_count ? String(savedLine.piece_count) : "",
        batch_no: savedLine.batch_no,
        warehouse_id: savedLine.warehouse_id,
        supplier_id: Number(saved.payload.supplier_id || 0),
        cost_per_unit: String(savedLine.cost_per_unit),
      } : {}),
    });
  }

  async function submitReceive(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!receiveState || !me || receiving.current) return;
    receiving.current = true;
    const scope = { userId: me.id, factoryCode: me.factory_code };
    setReceiveState({ ...receiveState, saving: true, message: "" });
    try {
      const saved = readPendingPurchaseReceipt(localStorage, scope);
      if (saved?.key !== pendingReceipt?.key) {
        // Another tab may have started or resolved this receipt while the form was open.
        setReceiveState(null);
        setPendingReceipt(saved);
        refreshOrders();
        if (saved) setMessage(t("page.purchasing.pendingReceipt"));
        return;
      }
      if (saved && (saved.orderId !== receiveState.order.id || saved.payload.lines[0].purchase_order_line_id !== receiveState.line.id)) {
        throw new PurchaseReceiptRecoveryError("pending");
      }
      let payload: PurchaseReceiptPayload;
      if (saved) {
        payload = saved.payload;
      } else {
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
                received: fmtQty(receivedTotal), ordered: fmtQty(orderedQuantity),
                remaining: fmtQty(remainingQuantity), unit: receiveState.line.unit,
              }),
              confirmText: t("page.purchasing.closeShortReceiptConfirm"),
              cancelText: t("page.purchasing.closeShortReceiptKeepOpen"),
            })
          : false;
        const rollWeights = usesRollWeights ? divideBatchQuantityByRollCount(quantity, rollCount) : [];
        payload = {
          supplier_id: receiveState.supplier_id || null,
          close_order: closeOrder,
          lines: [{
            purchase_order_line_id: receiveState.line.id,
            received_quantity: quantity,
            batch_no: receiveState.batch_no.trim(),
            warehouse_id: warehouseId,
            cost_per_unit: Number.isFinite(cost) ? cost : 0,
            piece_count: usesRollWeights ? rollCount : null,
            roll_weights_kg: rollWeights,
          }],
        };
      }
      const prepared = await preparePurchaseReceipt(localStorage, scope, receiveState.order.id, payload);
      setPendingReceipt(prepared.pending);
      await sendPreparedPurchaseReceipt(
        localStorage,
        scope,
        prepared,
        (pending) => api.postWithIdempotency(
          `/api/purchasing/orders/${pending.orderId}/receive`, pending.payload, pending.key,
        ),
        (pending) => api.postWithIdempotency(
          `/api/purchasing/orders/${pending.orderId}/receive/reconcile`, pending.payload, pending.key,
        ),
      );
      setPendingReceipt(null);
      refreshOrders();
      setReceiveState(null);
      setMessage(t("page.purchasing.received"));
    } catch (error: any) {
      try {
        setPendingReceipt(readPendingPurchaseReceipt(localStorage, scope));
      } catch {
        setRecoveryStorageError(true);
      }
      const errorMessage = error instanceof PurchaseReceiptRecoveryError
        ? t(error.code === "pending"
          ? "page.purchasing.pendingReceipt"
          : error.code === "completed_unavailable"
            ? "page.purchasing.receiptRecoveryResolved"
            : "page.purchasing.receiptStorageUnavailable")
        : error?.message || t("page.purchasing.actionFailed");
      if (error instanceof PurchaseReceiptRecoveryError && error.code === "pending") {
        setReceiveState(null);
        setMessage(errorMessage);
      } else if (error instanceof PurchaseReceiptRecoveryError && error.code === "completed_unavailable") {
        setPendingReceipt(null);
        setReceiveState(null);
        setMessage(errorMessage);
        refreshOrders();
      } else {
        setReceiveState((prev) => prev ? { ...prev, saving: false, message: errorMessage } : prev);
      }
    } finally {
      receiving.current = false;
    }
  }

  async function recoverPendingReceipt() {
    if (!me || !pendingReceipt || receiving.current || recoveryBusy) return;
    receiving.current = true;
    setRecoveryBusy(true);
    const scope = { userId: me.id, factoryCode: me.factory_code };
    setMessage("");
    try {
      const resolution = await reconcilePendingPurchaseReceipt(
        localStorage,
        scope,
        pendingReceipt,
        (pending) => api.postWithIdempotency(
          `/api/purchasing/orders/${pending.orderId}/receive/reconcile`,
          pending.payload,
          pending.key,
        ),
      );
      setPendingReceipt(null);
      setReceiveState(null);
      setMessage(t(resolution.status === "cancelled"
        ? "page.purchasing.receiptRecoveryCancelled"
        : resolution.status === "completed_unavailable"
          ? "page.purchasing.receiptRecoveryResolved"
          : "page.purchasing.received"));
      refreshOrders();
    } catch (error: any) {
      try {
        setPendingReceipt(readPendingPurchaseReceipt(localStorage, scope));
      } catch {
        setRecoveryStorageError(true);
      }
      setMessage(error?.message || t("page.purchasing.actionFailed"));
    } finally {
      receiving.current = false;
      setRecoveryBusy(false);
    }
  }

  const pendingRecovery = pendingReceipt ? (
    <div className="mb-4 rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm">
      <p>{t("page.purchasing.pendingReceipt")}</p>
      <button type="button" className="btn mt-2" disabled={recoveryBusy} onClick={recoverPendingReceipt}>
        {t(recoveryBusy ? "common.saving" : "common.retry")}{pendingOrder && pendingLine
          ? ` · ${formatOrderReference(pendingOrder.po_no)} · ${lineItemLabel(pendingLine)}`
          : ""}
      </button>
    </div>
  ) : null;

  if (!canView) {
    return <div>
      <PageHeader title={t("page.purchasing.receivingTitle")} subtitle={t("page.purchasing.noAccess")} />
      {message && <div className="mb-4 rounded-md border border-[#ded9ca] bg-[#fbfaf6] px-4 py-3 text-sm text-[#56503f]">{message}</div>}
      {recoveryStorageError && <div role="alert" className="mb-4 text-sm text-red-600">{t("page.purchasing.receiptStorageUnavailable")}</div>}
      {pendingRecovery}
    </div>;
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
      {recoveryStorageError && <div role="alert" className="mb-4 text-sm text-red-600">{t("page.purchasing.receiptStorageUnavailable")}</div>}
      {pendingRecovery}

      <section className="card overflow-hidden">
        <div className="border-b border-[#ecebe3] px-5 py-4">
          <h2 className="app-card-title">{t("page.purchasing.pendingOrders")}</h2>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <input
              className="input h-9 min-w-48 flex-1"
              aria-label={`${t("common.search")} ${t("page.purchasing.pendingOrders")}`}
              placeholder={t("common.search")}
              maxLength={100}
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
            <span className="text-xs text-slate-500">{orders.length} / {totalOrders}</span>
          </div>
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
        </div>
      </section>
      {hasMoreOrders && (
        <div className="mt-3 flex justify-center">
          <button className="btn btn-secondary" disabled={ordersValidating} onClick={() => setSize(size + 1)}>
            {ordersValidating ? t("common.loading") : t("common.loadMore")}
          </button>
        </div>
      )}

      {receiveState && (
        <div className="fixed inset-0 z-40 bg-black/40">
          <div className="absolute inset-0 overflow-y-auto p-4 md:p-6">
            <form onSubmit={submitReceive} className="card mx-auto w-full max-w-2xl p-5">
              <div className="mb-4 flex items-start justify-between gap-4">
                <div>
                  <div className="text-lg font-semibold text-[#14110b]">{t("page.purchasing.receiveOrder")}</div>
                  <div className="mt-1 text-sm text-[#6f684f]">{formatOrderReference(receiveState.order.po_no)} - {lineItemLabel(receiveState.line)}</div>
                </div>
                <button type="button" className="icon-btn" disabled={receiveState.saving} onClick={() => setReceiveState(null)} aria-label={t("common.close")}>
                  <X />
                </button>
              </div>

              {pendingReceipt && <p className="mb-3 text-sm text-amber-700">{t("page.purchasing.pendingReceipt")}</p>}
              <fieldset disabled={receiveState.saving || !!pendingReceipt} className="grid grid-cols-1 gap-3 md:grid-cols-2">
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
                    {suppliers?.map((supplier) => (
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
              </fieldset>
              {receiveState.message && <div className="mt-3 text-sm text-red-600">{receiveState.message}</div>}
              <div className="mt-5 flex justify-end gap-2">
                <button type="button" className="btn" onClick={() => setReceiveState(null)} disabled={receiveState.saving}>{t("btn.cancel")}</button>
                <button className="btn btn-primary" disabled={receiveState.saving}>
                  {receiveState.saving ? t("common.saving") : pendingReceipt ? t("common.retry") : t("btn.receive")}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
