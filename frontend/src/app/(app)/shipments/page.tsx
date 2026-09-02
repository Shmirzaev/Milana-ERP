"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";

import PageHeader from "@/components/PageHeader";
import ShipmentPreparationWorkspace, {
  type ShipmentPreparation,
  type ShipmentSummary,
} from "@/components/ShipmentPreparationWorkspace";
import { statusLabel } from "@/components/StagePipeline";
import { useDialogs } from "@/components/DialogProvider";
import { api, fetcher } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";

type ShipmentRow = ShipmentSummary & {
  shipment_type?: "sales_order" | "warehouse_exit";
  shipped_at?: string | null;
  delivered_at?: string | null;
  created_at?: string | null;
  required_count?: number | null;
  scanned_count?: number | null;
  remaining_count?: number | null;
  is_complete?: boolean;
};

type EligibleOrder = {
  id: number;
  order_no: string;
  customer_id?: number | null;
  customer_name?: string | null;
  status: string;
  ready_qty?: number | null;
};

type ShipmentOrder = EligibleOrder & {
  shipment?: ShipmentRow | null;
  is_scanned: boolean;
};

function errorMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return "Action failed.";
}

function ShipmentOrderWorkspace({
  order,
  canTraceability,
  onChanged,
}: {
  order: ShipmentOrder;
  canTraceability: boolean;
  onChanged: () => Promise<unknown>;
}) {
  const { t } = useT();
  const dialogs = useDialogs();
  const shipmentId = Number(order.shipment?.id || 0);
  const preparationKey = shipmentId > 0
    ? `/api/shipments/${shipmentId}/preparation`
    : `/api/shipments/sales-order/${order.id}/preparation`;
  const { data: preparation, isLoading, mutate } = useSWR<ShipmentPreparation>(preparationKey, fetcher);
  const [scanCode, setScanCode] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [isCreating, setIsCreating] = useState(false);

  async function refresh() {
    await Promise.all([mutate(), onChanged()]);
  }

  async function createShipment() {
    if (shipmentId || isCreating) return;
    setError("");
    setMessage("");
    setIsCreating(true);
    try {
      const shipment = await api.post<ShipmentRow>("/api/shipments", { sales_order_id: order.id, notes: null });
      setMessage(t("page.shipments.salesShipmentCreated", {
        shipment: shipment.shipment_no,
        count: Number(shipment.packages_count || 0),
      }));
      await onChanged();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setIsCreating(false);
    }
  }

  async function addAllReady() {
    if (!shipmentId) return;
    setError("");
    setMessage("");
    try {
      await api.post(`/api/shipments/${shipmentId}/add-ready-packages`);
      setMessage(t("page.shipments.allReadyAdded"));
      await refresh();
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }

  async function scanPackage() {
    if (!shipmentId || !scanCode.trim()) return;
    setError("");
    setMessage("");
    try {
      const result = await api.post<Record<string, unknown>>(`/api/shipments/${shipmentId}/scan-package`, {
        code: scanCode.trim(),
      });
      if (String(result.sign || "") === "error") {
        setError(String(result.message || t("page.shipments.scanMismatch")));
      } else {
        setMessage(String(result.message || t("page.shipments.scanProcessed")));
      }
      setScanCode("");
      await refresh();
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }

  async function ship() {
    if (!shipmentId || !(await dialogs.ask({ message: t("page.shipments.confirmMarkShipped") }))) return;
    setError("");
    setMessage("");
    try {
      await api.post(`/api/shipments/${shipmentId}/ship`);
      setMessage(t("page.shipments.markedShipped"));
      await refresh();
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }

  async function deliver() {
    if (!shipmentId || !(await dialogs.ask({ message: t("page.shipments.confirmMarkDelivered") }))) return;
    setError("");
    setMessage("");
    try {
      await api.post(`/api/shipments/${shipmentId}/deliver`);
      setMessage(t("page.shipments.markedDelivered"));
      await refresh();
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }

  return (
    <article id={`shipment-order-${order.id}`} className="scroll-mt-4">
      {message ? <div className="border-x border-t border-emerald-200 bg-emerald-50 px-4 py-2 text-sm text-emerald-800">{message}</div> : null}
      {error ? <div className="border-x border-t border-rose-200 bg-rose-50 px-4 py-2 text-sm text-rose-800">{error}</div> : null}
      <ShipmentPreparationWorkspace
        preparation={preparation}
        isLoading={isLoading}
        scanCode={scanCode}
        onScanCodeChange={setScanCode}
        onScan={scanPackage}
        onAddReadyPackages={addAllReady}
        onShip={ship}
        onDeliver={deliver}
        onCreate={createShipment}
        isCreating={isCreating}
        canTraceability={canTraceability}
      />
    </article>
  );
}

export default function ShipmentsPage() {
  const { t } = useT();
  const { me } = useMe();
  const canTraceability = can(me, "traceability.view");
  const searchParams = useSearchParams();
  const { data, mutate } = useSWR<ShipmentRow[]>("/api/shipments", fetcher);
  const { data: orders, mutate: mutateOrders } = useSWR<EligibleOrder[]>("/api/shipments/eligible-orders", fetcher);
  const [orderQuery, setOrderQuery] = useState("");
  const [warehouseExitReference, setWarehouseExitReference] = useState("");
  const [warehouseMessage, setWarehouseMessage] = useState("");
  const [warehouseError, setWarehouseError] = useState("");
  const [historyQuery, setHistoryQuery] = useState("");
  const [historyStatus, setHistoryStatus] = useState("all");

  const shipmentOrders = useMemo<ShipmentOrder[]>(() => {
    const byOrder = new Map<number, ShipmentOrder>();
    for (const shipment of data || []) {
      const orderId = Number(shipment.sales_order_id || 0);
      if (!orderId || !["draft", "created"].includes(String(shipment.status || "")) || byOrder.has(orderId)) continue;
      byOrder.set(orderId, {
        id: orderId,
        order_no: shipment.sales_order_no || `#${orderId}`,
        customer_name: shipment.customer_name,
        status: shipment.status,
        ready_qty: shipment.total_qty,
        shipment,
        is_scanned: Boolean(shipment.is_complete),
      });
    }
    for (const order of orders || []) {
      if (byOrder.has(Number(order.id))) continue;
      byOrder.set(Number(order.id), { ...order, shipment: null, is_scanned: false });
    }
    return Array.from(byOrder.values()).sort((a, b) => Number(b.id) - Number(a.id));
  }, [data, orders]);

  const filteredOrders = useMemo(() => {
    const query = orderQuery.trim().toLocaleLowerCase();
    if (!query) return shipmentOrders;
    return shipmentOrders.filter((order) => [order.order_no, order.customer_name, order.shipment?.shipment_no]
      .some((value) => String(value || "").toLocaleLowerCase().includes(query)));
  }, [orderQuery, shipmentOrders]);

  const filteredHistory = useMemo(() => {
    const query = historyQuery.trim().toLocaleLowerCase();
    return (data || []).filter((shipment) => {
      if (historyStatus !== "all" && String(shipment.status || "") !== historyStatus) return false;
      if (!query) return true;
      return [shipment.shipment_no, shipment.sales_order_no, shipment.customer_name, shipment.notes]
        .some((value) => String(value || "").toLocaleLowerCase().includes(query));
    });
  }, [data, historyQuery, historyStatus]);

  async function refreshOrders() {
    await Promise.all([mutate(), mutateOrders()]);
  }

  async function createWarehouseExit() {
    if (!warehouseExitReference.trim()) return;
    setWarehouseError("");
    setWarehouseMessage("");
    try {
      const shipment = await api.post<ShipmentRow>("/api/shipments", { sales_order_id: null, notes: warehouseExitReference.trim() });
      setWarehouseExitReference("");
      setWarehouseMessage(t("page.shipments.warehouseExitCreated", { shipment: shipment.shipment_no }));
      await mutate();
    } catch (caught) {
      setWarehouseError(errorMessage(caught));
    }
  }

  useEffect(() => {
    if (!shipmentOrders.length) return;
    const requestedOrderId = Number(searchParams.get("so_id") || 0);
    const requestedShipmentId = Number(searchParams.get("shipment_id") || 0);
    const requestedOrder = requestedOrderId
      ? shipmentOrders.find((order) => order.id === requestedOrderId)
      : shipmentOrders.find((order) => Number(order.shipment?.id || 0) === requestedShipmentId);
    if (!requestedOrder) return;
    window.requestAnimationFrame(() => {
      document.getElementById(`shipment-order-${requestedOrder.id}`)?.scrollIntoView({ block: "start" });
    });
  }, [searchParams, shipmentOrders]);

  return (
    <div>
      <PageHeader title={t("page.shipments.title")} />
      <div className="max-w-[1440px] space-y-4">
        <section className="card overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-5">
            <div>
              <h2 className="app-card-title">{t("page.shipments.orderFloorTitle", { count: shipmentOrders.length })}</h2>
              <p className="mt-1 text-xs text-[#6f6a5b]">{t("page.shipments.orderFloorHint")}</p>
            </div>
            <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row sm:items-center">
              <div className="flex items-center gap-3 text-xs text-[#56503f]" aria-label={t("page.shipments.orderSelectorHint")}>
                <span className="inline-flex items-center gap-1.5"><span className="h-3 w-3 border border-[#ded9ca] bg-white" />{t("page.shipments.notScanned")}</span>
                <span className="inline-flex items-center gap-1.5"><span className="h-3 w-3 border border-emerald-200 bg-emerald-50" />{t("page.shipments.scanned")}</span>
              </div>
              <input className="input w-full sm:w-72" value={orderQuery} onChange={(event) => setOrderQuery(event.target.value)} placeholder={t("page.shipments.orderFloorSearch")} aria-label={t("page.shipments.orderFloorSearch")} />
            </div>
          </div>
        </section>

        {filteredOrders.length ? (
          <div className="space-y-4">
            {filteredOrders.map((order) => <ShipmentOrderWorkspace key={order.id} order={order} canTraceability={canTraceability} onChanged={refreshOrders} />)}
          </div>
        ) : <section className="card px-4 py-10 text-center text-sm text-[#6f6a5b]">{t("page.shipments.noOrderMatches")}</section>}

        <section id="warehouse-exit" className="card p-4 sm:p-5">
          <div className="mb-3"><h2 className="app-card-title">{t("page.shipments.createWarehouseExit")}</h2><p className="mt-1 text-xs text-[#6f6a5b]">{t("page.shipments.warehouseExitHint")}</p></div>
          {warehouseMessage ? <div className="mb-3 border-l-2 border-emerald-600 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{warehouseMessage}</div> : null}
          {warehouseError ? <div className="mb-3 border-l-2 border-rose-600 bg-rose-50 px-3 py-2 text-sm text-rose-800">{warehouseError}</div> : null}
          <div className="flex flex-col gap-2 sm:flex-row">
            <input className="input min-w-0 flex-1" value={warehouseExitReference} onChange={(event) => setWarehouseExitReference(event.target.value)} placeholder={t("page.shipments.exitReferencePlaceholder")} />
            <button type="button" className="btn btn-primary" onClick={createWarehouseExit} disabled={!warehouseExitReference.trim()}>{t("page.shipments.createWarehouseExit")}</button>
          </div>
        </section>

        <section className="card overflow-hidden">
          <div className="flex flex-wrap items-end justify-between gap-3 border-b border-[#ded9ca] px-4 py-3 sm:px-5">
            <div><h2 className="app-card-title">{t("page.shipments.history")}</h2><p className="mt-1 text-xs text-[#6f6a5b]">{t("page.shipments.historyHint")}</p></div>
            <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row">
              <input className="input w-full sm:w-72" value={historyQuery} onChange={(event) => setHistoryQuery(event.target.value)} placeholder={t("page.shipments.historySearch")} aria-label={t("page.shipments.historySearch")} />
              <select className="input w-full sm:w-44" value={historyStatus} onChange={(event) => setHistoryStatus(event.target.value)} aria-label={t("field.status")}>
                <option value="all">{t("page.shipments.allStatuses")}</option>
                {["created", "shipped", "delivered", "cancelled"].map((status) => <option key={status} value={status}>{statusLabel(status, t)}</option>)}
              </select>
            </div>
          </div>
          <div className="divide-y divide-[#ded9ca] md:hidden">
            {filteredHistory.map((shipment) => (
              <article key={shipment.id} className="p-4">
                <div className="flex items-start justify-between gap-3"><div className="mono font-semibold text-[#14110b]">{shipment.shipment_no}</div><span className="badge">{statusLabel(shipment.status, t)}</span></div>
                <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-[#56503f]"><span>{shipment.sales_order_id ? t("page.shipments.fromSalesOrder") : t("page.shipments.warehouseExit")}</span><span className="text-right mono">{shipment.sales_order_no || "-"}</span><span>{shipment.customer_name || "-"}</span><span className="text-right tabular-nums">{Number(shipment.packages_count || 0)} {t("field.packages")} · {Number(shipment.total_qty || 0).toLocaleString()} {t("page.shipments.pieces")}</span></div>
                {canTraceability ? <Link className="btn mt-3 h-8 px-2.5 text-[11px]" href={`/traceability?shipment=${encodeURIComponent(shipment.shipment_no || shipment.id)}`}>{t("page.shipments.traceability")}</Link> : null}
              </article>
            ))}
            {!filteredHistory.length ? <div className="p-8 text-center text-sm text-[#6f6a5b]">{t("page.shipments.noHistoryMatches")}</div> : null}
          </div>
          <div className="hidden overflow-x-auto md:block">
            <table className="table min-w-[1180px]">
              <thead><tr><th>{t("field.shipmentNo")}</th><th>{t("page.shipments.type")}</th><th>{t("page.shipments.salesOrder")}</th><th>{t("field.customer")}</th><th>{t("page.shipments.reference")}</th><th>{t("field.packages")}</th><th>{t("field.totalQty")}</th><th>{t("field.status")}</th><th>{t("field.shipped")}</th><th>{t("field.delivered")}</th><th>{t("field.actions")}</th></tr></thead>
              <tbody>
                {filteredHistory.map((shipment) => <tr key={shipment.id}><td className="mono whitespace-nowrap font-semibold text-[#14110b]">{shipment.shipment_no}</td><td>{shipment.sales_order_id ? t("page.shipments.fromSalesOrder") : t("page.shipments.warehouseExit")}</td><td className="mono whitespace-nowrap">{shipment.sales_order_no || "-"}</td><td>{shipment.customer_name || "-"}</td><td className="max-w-56 whitespace-normal">{shipment.notes || "-"}</td><td className="tabular-nums">{Number(shipment.packages_count || 0)}</td><td className="tabular-nums">{Number(shipment.total_qty || 0).toLocaleString()}</td><td><span className="badge">{statusLabel(shipment.status, t)}</span></td><td className="whitespace-nowrap">{shipment.shipped_at ? new Date(shipment.shipped_at).toLocaleString() : "-"}</td><td className="whitespace-nowrap">{shipment.delivered_at ? new Date(shipment.delivered_at).toLocaleString() : "-"}</td><td>{canTraceability ? <Link className="btn h-8 px-2.5 text-[11px]" href={`/traceability?shipment=${encodeURIComponent(shipment.shipment_no || shipment.id)}`}>{t("page.shipments.traceability")}</Link> : "-"}</td></tr>)}
                {!filteredHistory.length ? <tr><td colSpan={11} className="py-8 text-center text-sm text-[#6f6a5b]">{t("page.shipments.noHistoryMatches")}</td></tr> : null}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  );
}
