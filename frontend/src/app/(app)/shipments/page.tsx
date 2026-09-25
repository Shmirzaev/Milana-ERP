"use client";
import { formatOrderReference } from "@/lib/orderRef";

import Link from "next/link";
import ShipmentAddClient from "@/components/ShipmentAddClient";
import SearchableSelect from "@/components/SearchableSelect";
import { packageWorkflowChangedEvent, packageWorkflowCopy, pendingPackageWorkflow, postPackageWorkflow, reconcilePendingPackageWorkflow } from "@/lib/packageWorkflow";
import { manualShipmentText } from "@/lib/manualShipmentText";
import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import useSWRInfinite from "swr/infinite";

import PageHeader from "@/components/PageHeader";
import PaginationControls from "@/components/PaginationControls";
import ShipmentPreparationWorkspace, {
  type ShipmentPreparation,
  type ShipmentSummary,
} from "@/components/ShipmentPreparationWorkspace";
import { statusLabel } from "@/components/StagePipeline";
import { useDialogs } from "@/components/DialogProvider";
import { api, fetcher } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { shipmentReviewText } from "@/lib/shipmentReviewText";
import ShipmentTransportDetails, { ShipmentTransportFields, normalizeTransportDetails, type TransportDetails } from "@/components/ShipmentTransportDetails";
import { shipmentTransportText } from "@/lib/shipmentTransportText";

type ShipmentRow = ShipmentSummary & {
  shipment_type?: "sales_order" | "warehouse_exit" | "manual";
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

type ShipmentOrderPage = {
  rows: ShipmentOrder[];
  pinned: ShipmentOrder | null;
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
};
type ShipmentPage = { rows: ShipmentRow[]; total: number; has_more: boolean };

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
  const { t, lang } = useT();
  const dialogs = useDialogs();
  const shipmentId = Number(order.shipment?.id || 0);
  const articleRef = useRef<HTMLElement | null>(null);
  const [preparationActive, setPreparationActive] = useState(false);
  useEffect(() => {
    if (preparationActive || !articleRef.current) return;
    if (typeof IntersectionObserver === "undefined") {
      setPreparationActive(true);
      return;
    }
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        setPreparationActive(true);
        observer.disconnect();
      }
    }, { rootMargin: "200px" });
    observer.observe(articleRef.current);
    return () => observer.disconnect();
  }, [preparationActive]);
  const preparationKey = !preparationActive ? null : shipmentId > 0
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

  async function createShipment(transportDetails: TransportDetails | null) {
    if (shipmentId || isCreating) return;
    setError("");
    setMessage("");
    setIsCreating(true);
    try {
      const shipment = await api.post<ShipmentRow>("/api/shipments", { sales_order_id: order.id, notes: null, transport_details: transportDetails });
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
    if (!shipmentId || !(await dialogs.ask({ message: order.shipment?.shipment_type === "manual" ? manualShipmentText[lang].confirm : t("page.shipments.confirmMarkShipped") }))) return;
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
    <article ref={articleRef} id={order.id ? `shipment-order-${order.id}` : `shipment-${shipmentId}`} className="scroll-mt-4">
      {message ? <div className="border-x border-t border-emerald-200 bg-emerald-50 px-4 py-2 text-sm text-emerald-800">{message}</div> : null}
      {error ? <div className="border-x border-t border-rose-200 bg-rose-50 px-4 py-2 text-sm text-rose-800">{error}</div> : null}
      {preparationActive ? <ShipmentPreparationWorkspace
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
        onReviewChanged={refresh}
      /> : <button type="button" className="card flex w-full items-center justify-between gap-3 p-4 text-left" onClick={() => setPreparationActive(true)}>
        <span className="font-medium">{order.shipment?.shipment_no || formatOrderReference(order.order_no)} · {order.customer_name || "-"}</span>
        <span className="text-sm">{t("common.view")}</span>
      </button>}
    </article>
  );
}

export default function ShipmentsPage() {
  const { t, lang } = useT();
  const { me } = useMe();
  const canTraceability = can(me, "traceability.view");
  const searchParams = useSearchParams();
  const [orderQuery, setOrderQuery] = useState("");
  const [orderSearch, setOrderSearch] = useState("");
  const [orderPage, setOrderPage] = useState(1);
  useEffect(() => {
    const timer = window.setTimeout(() => { setOrderSearch(orderQuery.trim()); setOrderPage(1); }, 200);
    return () => window.clearTimeout(timer);
  }, [orderQuery]);
  const targetOrderId = Number(searchParams.get("so_id") || 0);
  const targetShipmentId = Number(searchParams.get("shipment_id") || 0);
  const floorParams = new URLSearchParams({ page: String(orderPage), page_size: "50", q: orderSearch });
  if (!orderSearch && targetOrderId) floorParams.set("target_sales_order_id", String(targetOrderId));
  else if (!orderSearch && targetShipmentId) floorParams.set("target_shipment_id", String(targetShipmentId));
  const { data: floorPage, mutate: mutateFloor } = useSWR<ShipmentOrderPage>(`/api/shipments/order-floor?${floorParams.toString()}`, fetcher);
  const manualText = manualShipmentText[lang];
  const canManualShipment = can(me, "storage.shipment");
  const { data: customers, mutate: mutateCustomers } = useSWR<Array<{ id: number; name: string }>>(canManualShipment ? "/api/shipments/customers" : null, fetcher);
  const [customerId, setCustomerId] = useState<number | null>(null);
  const [pendingManual, setPendingManual] = useState<Record<string, any> | null>(null);
  useEffect(() => {
    if (!me?.id) return;
    const update = () => {
      try {
        const pending = pendingPackageWorkflow("/api/shipments", me.id);
        setPendingManual(pending?.body || null);
        if (pending) setCustomerId(pending.body.customer_id);
      } catch (caught) {
        setWarehouseError(errorMessage(caught));
      }
    };
    update();
    window.addEventListener(packageWorkflowChangedEvent, update);
    window.addEventListener("storage", update);
    return () => {
      window.removeEventListener(packageWorkflowChangedEvent, update);
      window.removeEventListener("storage", update);
    };
  }, [me?.id]);
  const [warehouseTransport, setWarehouseTransport] = useState<TransportDetails>({});
  const [warehouseCreating, setWarehouseCreating] = useState(false);
  const [warehouseMessage, setWarehouseMessage] = useState("");
  const [warehouseError, setWarehouseError] = useState("");
  const [historyQuery, setHistoryQuery] = useState("");
  const [historyStatus, setHistoryStatus] = useState("all");
  const [historySearch, setHistorySearch] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => setHistorySearch(historyQuery.trim()), 200);
    return () => window.clearTimeout(timer);
  }, [historyQuery]);
  const { data: historyPages, size: historyPageCount, setSize: setHistoryPageCount, mutate: mutateHistory } = useSWRInfinite<ShipmentPage>(
    (index, previous) => previous && !previous.has_more ? null
      : `/api/shipments?page=${index + 1}&page_size=50&q=${encodeURIComponent(historySearch)}&status=${encodeURIComponent(historyStatus)}`,
    fetcher,
    { persistSize: false },
  );
  const { data: targetHistoryPage } = useSWR<ShipmentPage>(
    targetShipmentId ? `/api/shipments?shipment_id=${targetShipmentId}&page=1&page_size=1` : null,
    fetcher,
  );
  const { data: manualPages, size: manualPageCount, setSize: setManualPageCount, mutate: mutateManual } = useSWRInfinite<ShipmentPage>(
    (index, previous) => previous && !previous.has_more ? null
      : `/api/shipments?page=${index + 1}&page_size=50&manual_open=true`,
    fetcher,
  );
  const filteredHistory = useMemo(() => historyPages?.flatMap((page) => page.rows) || [], [historyPages]);
  const manualOpen = useMemo(() => manualPages?.flatMap((page) => page.rows) || [], [manualPages]);
  const shipmentOrders = useMemo(() => [
    ...(floorPage?.pinned ? [floorPage.pinned] : []),
    ...(floorPage?.rows || []),
  ], [floorPage]);
  const floorTarget = targetShipmentId
    ? shipmentOrders.find((order) => Number(order.shipment?.id || 0) === targetShipmentId)
    : shipmentOrders.find((order) => order.id === targetOrderId);
  const pinnedHistory = floorPage && !floorTarget && !historySearch && historyStatus === "all"
    ? targetHistoryPage?.rows?.find((shipment) => shipment.id === targetShipmentId)
    : undefined;
  const historyRows = pinnedHistory
    ? [pinnedHistory, ...filteredHistory.filter((shipment) => shipment.id !== pinnedHistory.id)]
    : filteredHistory;
  const scrolledTargetRef = useRef<string | null>(null);

  async function mutate() {
    await Promise.all([mutateHistory(), mutateManual()]);
  }

  async function refreshOrders() {
    await Promise.all([mutate(), mutateFloor()]);
  }

  async function createWarehouseExit() {
    if (!customerId || warehouseCreating || pendingManual) return;
    setWarehouseError("");
    setWarehouseMessage("");
    setWarehouseCreating(true);
    try {
      const shipment = await postPackageWorkflow<ShipmentRow>("/api/shipments", { manual: true, customer_id: customerId, transport_details: normalizeTransportDetails(warehouseTransport) }, me!.id);
      setPendingManual(null);
      setCustomerId(null);
      setWarehouseTransport({});
      setWarehouseMessage(`${manualText.created}: ${shipment.shipment_no}`);
      await mutate();
    } catch (caught) {
      setWarehouseError(errorMessage(caught));
      setPendingManual(pendingPackageWorkflow("/api/shipments", me!.id)?.body || null);
    } finally {
      setWarehouseCreating(false);
    }
  }

  async function recoverWarehouseExit() {
    if (!pendingManual || warehouseCreating || !me?.id) return;
    setWarehouseError("");
    setWarehouseMessage("");
    setWarehouseCreating(true);
    try {
      const resolution = await reconcilePendingPackageWorkflow<ShipmentRow>("/api/shipments", me.id);
      setPendingManual(null);
      if (resolution.status === "completed") {
        setWarehouseMessage(`${manualText.created}: ${resolution.result.shipment_no}`);
        await mutate();
      } else {
        setWarehouseMessage(resolution.status === "cancelled"
          ? packageWorkflowCopy[lang].pendingCancelled
          : packageWorkflowCopy[lang].resultUnavailable);
      }
    } catch (caught) {
      setWarehouseError(errorMessage(caught));
      try {
        setPendingManual(pendingPackageWorkflow("/api/shipments", me.id)?.body || null);
      } catch {
        setPendingManual(null);
      }
    } finally {
      setWarehouseCreating(false);
    }
  }

  useEffect(() => {
    const targetKey = `${targetOrderId}:${targetShipmentId}`;
    if ((!targetOrderId && !targetShipmentId) || scrolledTargetRef.current === targetKey) return;
    const elementId = floorTarget ? `shipment-order-${floorTarget.id}`
      : pinnedHistory ? `shipment-history-target-${targetShipmentId}` : null;
    if (!elementId) return;
    window.requestAnimationFrame(() => {
      const element = document.getElementById(elementId);
      if (!element || scrolledTargetRef.current === targetKey) return;
      element.scrollIntoView({ block: "start" });
      scrolledTargetRef.current = targetKey;
    });
  }, [targetOrderId, targetShipmentId, floorTarget, pinnedHistory]);

  return (
    <div>
      <PageHeader title={t("page.shipments.title")} />
      <div className="max-w-[1440px] space-y-4">
        <section className="card overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-5">
            <div>
              <h2 className="app-card-title">{t("page.shipments.orderFloorTitle", { count: floorPage?.total || 0 })}</h2>
              <p className="mt-1 text-xs text-[#6f6a5b]">{t("page.shipments.orderFloorHint")}</p>
            </div>
            <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row sm:items-center">
              <div className="flex items-center gap-3 text-xs text-[#56503f]" aria-label={t("page.shipments.orderSelectorHint")}>
                <span className="inline-flex items-center gap-1.5"><span className="h-3 w-3 border border-[#ded9ca] bg-white" />{t("page.shipments.notScanned")}</span>
                <span className="inline-flex items-center gap-1.5"><span className="h-3 w-3 border border-emerald-200 bg-emerald-50" />{t("page.shipments.scanned")}</span>
              </div>
              <input className="input w-full sm:w-72" value={orderQuery} maxLength={200} onChange={(event) => setOrderQuery(event.target.value)} placeholder={t("page.shipments.orderFloorSearch")} aria-label={t("page.shipments.orderFloorSearch")} />
            </div>
          </div>
        </section>

        {shipmentOrders.length ? (
          <div className="space-y-4">
            {shipmentOrders.map((order) => <ShipmentOrderWorkspace key={order.id} order={order} canTraceability={canTraceability} onChanged={refreshOrders} />)}
          </div>
        ) : <section className="card px-4 py-10 text-center text-sm text-[#6f6a5b]">{t("page.shipments.noOrderMatches")}</section>}
        <section className="card overflow-hidden">
          <PaginationControls page={orderPage} pageSize={50} total={floorPage?.total || 0} count={floorPage?.rows?.length || 0}
            onPageChange={setOrderPage} onPageSizeChange={() => setOrderPage(1)} pageSizeOptions={[50]} />
        </section>

        {(canManualShipment || pendingManual || warehouseMessage || warehouseError) && <section id="warehouse-exit" className="card p-4 sm:p-5">
          <div className="mb-3"><h2 className="app-card-title">{manualText.title}</h2><p className="mt-1 text-xs text-[#6f6a5b]">{manualText.hint}</p></div>
          {warehouseMessage ? <div className="mb-3 border-l-2 border-emerald-600 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{warehouseMessage}</div> : null}
          {pendingManual && <div className="mb-3">
            <p role="status" className="text-sm">{packageWorkflowCopy[lang].pendingRequest}</p>
            <button type="button" className="btn mt-2" disabled={warehouseCreating} onClick={recoverWarehouseExit}>
              {warehouseCreating ? packageWorkflowCopy[lang].loading : packageWorkflowCopy[lang].recover}
            </button>
          </div>}
          {warehouseError ? <div className="mb-3 border-l-2 border-rose-600 bg-rose-50 px-3 py-2 text-sm text-rose-800">{warehouseError}</div> : null}
          {canManualShipment && <div className="flex flex-col gap-2 sm:flex-row">
            <div className="min-w-0 flex-1"><SearchableSelect value={customerId} options={(customers || []).map(customer => ({ value: customer.id, label: customer.name }))} onChange={value => setCustomerId(Number(value))} placeholder={manualText.choose} noResultsText={manualText.none} disabled={warehouseCreating || !!pendingManual} /></div>
            <ShipmentAddClient disabled={warehouseCreating || !!pendingManual} onCreated={client => { void mutateCustomers([...(customers || []), client], false); setCustomerId(client.id); }} />
            <button type="button" className="btn btn-primary" onClick={createWarehouseExit} disabled={warehouseCreating || !customerId}>{manualText.title}</button>
          </div>}
          {canManualShipment && <details className="mt-3">
            <summary className="cursor-pointer text-sm font-medium">{shipmentTransportText[lang].optional}</summary>
            <div className="mt-3"><ShipmentTransportFields value={warehouseTransport} onChange={setWarehouseTransport} disabled={warehouseCreating || !!pendingManual} /></div>
          </details>}
        </section>}

        {manualOpen.map(shipment => (
          <ShipmentOrderWorkspace key={shipment.id} order={{ id: 0, order_no: "", status: shipment.status, shipment, is_scanned: !!shipment.is_complete }} canTraceability={canTraceability} onChanged={refreshOrders} />
        ))}
        {manualPages?.at(-1)?.has_more ? <button className="btn" type="button" onClick={() => void setManualPageCount(manualPageCount + 1)}>{t("common.loadMore")}</button> : null}

        {pinnedHistory ? <div id={`shipment-history-target-${targetShipmentId}`} className="scroll-mt-4" /> : null}
        <section className="card overflow-hidden">
          <div className="flex flex-wrap items-end justify-between gap-3 border-b border-[#ded9ca] px-4 py-3 sm:px-5">
            <div><h2 className="app-card-title">{t("page.shipments.history")}</h2><p className="mt-1 text-xs text-[#6f6a5b]">{t("page.shipments.historyHint")}</p></div>
            <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row">
              <input className="input w-full sm:w-72" value={historyQuery} maxLength={200} onChange={(event) => setHistoryQuery(event.target.value)} placeholder={t("page.shipments.historySearch")} aria-label={t("page.shipments.historySearch")} />
              <select className="input w-full sm:w-44" value={historyStatus} onChange={(event) => setHistoryStatus(event.target.value)} aria-label={t("field.status")}>
                <option value="all">{t("page.shipments.allStatuses")}</option>
                {["created", "shipped", "delivered", "cancelled"].map((status) => <option key={status} value={status}>{statusLabel(status, t)}</option>)}
              </select>
            </div>
          </div>
          <div className="divide-y divide-[#ded9ca] md:hidden">
            {historyRows.map((shipment) => (
              <article key={shipment.id} className="p-4">
                <div className="flex items-start justify-between gap-3"><div className="mono font-semibold text-[#14110b]">{shipment.shipment_no}</div><span className="badge">{statusLabel(shipment.status, t)}</span></div>
                <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-[#56503f]"><span>{shipment.shipment_type === "manual" ? manualText.type : shipment.sales_order_id ? t("page.shipments.fromSalesOrder") : t("page.shipments.warehouseExit")}</span><span className="text-right mono">{formatOrderReference(shipment.sales_order_no || "-")}</span><span>{shipment.customer_name || "-"}</span><span className="text-right tabular-nums">{Number(shipment.packages_count || 0)} {t("field.packages")} · {Number(shipment.total_qty || 0).toLocaleString()} {t("page.shipments.pieces")}</span></div>
                {["shipped", "delivered"].includes(shipment.status) && <a className="btn mt-3" href={`/api/shipments/${shipment.id}/invoice/print?lang=${lang}`} target="_blank" rel="noreferrer" title={shipmentReviewText[lang].reference}>{shipmentReviewText[lang].print}</a>}
                {(!shipment.sales_order_id || !["draft", "created"].includes(shipment.status)) && <ShipmentTransportDetails shipment={shipment} onChanged={mutate} />}
                {canTraceability ? <Link className="btn mt-3 h-8 px-2.5 text-[11px]" href={`/traceability?shipment=${encodeURIComponent(shipment.shipment_no || shipment.id)}`}>{t("page.shipments.traceability")}</Link> : null}
              </article>
            ))}
            {!historyRows.length ? <div className="p-8 text-center text-sm text-[#6f6a5b]">{t("page.shipments.noHistoryMatches")}</div> : null}
          </div>
          <div className="hidden overflow-x-auto md:block">
            <table className="table min-w-[1180px]">
              <thead><tr><th>{t("field.shipmentNo")}</th><th>{t("page.shipments.type")}</th><th>{t("page.shipments.salesOrder")}</th><th>{t("field.customer")}</th><th>{t("page.shipments.reference")}</th><th>{t("field.packages")}</th><th>{t("field.totalQty")}</th><th>{t("field.status")}</th><th>{t("field.shipped")}</th><th>{t("field.delivered")}</th><th>{t("field.actions")}</th></tr></thead>
              <tbody>
                {historyRows.map((shipment) => <tr key={shipment.id}><td className="mono whitespace-nowrap font-semibold text-[#14110b]">{shipment.shipment_no}</td><td>{shipment.shipment_type === "manual" ? manualText.type : shipment.sales_order_id ? t("page.shipments.fromSalesOrder") : t("page.shipments.warehouseExit")}</td><td className="mono whitespace-nowrap">{formatOrderReference(shipment.sales_order_no || "-")}</td><td>{shipment.customer_name || "-"}</td><td className="max-w-56 whitespace-normal">{shipment.notes || "-"}{(!shipment.sales_order_id || !["draft", "created"].includes(shipment.status)) && <ShipmentTransportDetails shipment={shipment} onChanged={mutate} />}</td><td className="tabular-nums">{Number(shipment.packages_count || 0)}</td><td className="tabular-nums">{Number(shipment.total_qty || 0).toLocaleString()}</td><td><span className="badge">{statusLabel(shipment.status, t)}</span></td><td className="whitespace-nowrap">{shipment.shipped_at ? new Date(shipment.shipped_at).toLocaleString() : "-"}</td><td className="whitespace-nowrap">{shipment.delivered_at ? new Date(shipment.delivered_at).toLocaleString() : "-"}</td><td>{["shipped", "delivered"].includes(shipment.status) && <a className="btn h-8 px-2.5 text-[11px]" href={`/api/shipments/${shipment.id}/invoice/print?lang=${lang}`} target="_blank" rel="noreferrer" title={shipmentReviewText[lang].reference}>{shipmentReviewText[lang].print}</a>}{canTraceability ? <Link className="btn h-8 px-2.5 text-[11px]" href={`/traceability?shipment=${encodeURIComponent(shipment.shipment_no || shipment.id)}`}>{t("page.shipments.traceability")}</Link> : "-"}</td></tr>)}
                {!historyRows.length ? <tr><td colSpan={11} className="py-8 text-center text-sm text-[#6f6a5b]">{t("page.shipments.noHistoryMatches")}</td></tr> : null}
              </tbody>
            </table>
          </div>
          {historyPages?.at(-1)?.has_more ? <button className="btn m-4" type="button" onClick={() => void setHistoryPageCount(historyPageCount + 1)}>{t("common.loadMore")}</button> : null}
        </section>
      </div>
    </div>
  );
}
