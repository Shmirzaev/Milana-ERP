"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";

import PageHeader from "@/components/PageHeader";
import SearchableSelect, { type SearchableSelectOption } from "@/components/SearchableSelect";
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

type ShipmentOrderChoice = EligibleOrder & {
  shipment_id?: number | null;
  shipment_no?: string | null;
  shipment_status?: string | null;
  is_scanned: boolean;
};

function errorMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return "Action failed.";
}

export default function ShipmentsPage() {
  const { t } = useT();
  const dialogs = useDialogs();
  const { me } = useMe();
  const canTraceability = can(me, "traceability.view");
  const searchParams = useSearchParams();
  const { data, mutate } = useSWR<ShipmentRow[]>("/api/shipments", fetcher);
  const { data: orders, mutate: mutateOrders } = useSWR<EligibleOrder[]>("/api/shipments/eligible-orders", fetcher);

  const [salesOrderId, setSalesOrderId] = useState(0);
  const [shipmentMode, setShipmentMode] = useState<"sales_order" | "warehouse_exit">("sales_order");
  const [warehouseExitReference, setWarehouseExitReference] = useState("");
  const [activeShipmentId, setActiveShipmentId] = useState(0);
  const [scanCode, setScanCode] = useState("");
  const [error, setError] = useState("");
  const [scanResult, setScanResult] = useState<Record<string, unknown> | null>(null);
  const [message, setMessage] = useState("");
  const [historyQuery, setHistoryQuery] = useState("");
  const [historyStatus, setHistoryStatus] = useState("all");

  useEffect(() => {
    const salesOrder = Number(searchParams.get("so_id") || 0);
    const shipment = Number(searchParams.get("shipment_id") || 0);
    if (salesOrder > 0) setSalesOrderId(salesOrder);
    if (shipment > 0) setActiveShipmentId(shipment);
    if (searchParams.get("mode") === "warehouse_exit") setShipmentMode("warehouse_exit");
  }, [searchParams]);

  const shipmentOrderChoices = useMemo<ShipmentOrderChoice[]>(() => {
    const byOrder = new Map<number, ShipmentOrderChoice>();
    for (const shipment of data || []) {
      const orderId = Number(shipment.sales_order_id || 0);
      if (!orderId || String(shipment.status || "") === "cancelled" || byOrder.has(orderId)) continue;
      byOrder.set(orderId, {
        id: orderId,
        order_no: shipment.sales_order_no || `#${orderId}`,
        customer_name: shipment.customer_name,
        status: shipment.status,
        ready_qty: shipment.total_qty,
        shipment_id: Number(shipment.id),
        shipment_no: shipment.shipment_no,
        shipment_status: shipment.status,
        is_scanned: Boolean(shipment.is_complete),
      });
    }
    for (const order of orders || []) {
      if (byOrder.has(Number(order.id))) continue;
      byOrder.set(Number(order.id), {
        ...order,
        shipment_id: null,
        shipment_no: null,
        shipment_status: null,
        is_scanned: false,
      });
    }
    return Array.from(byOrder.values()).sort((a, b) => Number(b.id || 0) - Number(a.id || 0));
  }, [data, orders]);

  const shipmentOrderOptions = useMemo<SearchableSelectOption<number>[]>(
    () => shipmentOrderChoices.map((order) => ({
      value: Number(order.id),
      label: `${order.order_no} — ${order.customer_name || "-"}`,
      searchText: `${order.shipment_no || ""} ${order.shipment_status || order.status || ""}`,
      metaText: order.is_scanned ? t("page.shipments.scanned") : t("page.shipments.notScanned"),
      tone: order.is_scanned ? "success" : "default",
    })),
    [shipmentOrderChoices, t],
  );

  useEffect(() => {
    if ((!orders && !data) || !salesOrderId) return;
    if (!shipmentOrderChoices.some((order) => Number(order.id) === Number(salesOrderId))) {
      setSalesOrderId(0);
    }
  }, [data, orders, salesOrderId, shipmentOrderChoices]);

  useEffect(() => {
    if (!Array.isArray(data) || data.length === 0) return;
    if (data.some((shipment) => Number(shipment.id) === Number(activeShipmentId))) return;
    if (salesOrderId > 0) return;
    const next = data.find((shipment) => ["draft", "created"].includes(String(shipment.status || ""))) || data[0];
    setActiveShipmentId(Number(next.id || 0));
    setSalesOrderId(Number(next.sales_order_id || 0));
  }, [data, activeShipmentId, salesOrderId]);

  const preparationKey = activeShipmentId > 0
    ? `/api/shipments/${activeShipmentId}/preparation`
    : shipmentMode === "sales_order" && salesOrderId > 0
      ? `/api/shipments/sales-order/${salesOrderId}/preparation`
      : null;
  const {
    data: preparation,
    isLoading: isPreparationLoading,
    mutate: mutatePreparation,
  } = useSWR<ShipmentPreparation>(preparationKey, fetcher);

  const filteredHistory = useMemo(() => {
    const query = historyQuery.trim().toLocaleLowerCase();
    return (data || []).filter((shipment) => {
      if (historyStatus !== "all" && String(shipment.status || "") !== historyStatus) return false;
      if (!query) return true;
      return [shipment.shipment_no, shipment.sales_order_no, shipment.customer_name, shipment.notes]
        .some((value) => String(value || "").toLocaleLowerCase().includes(query));
    });
  }, [data, historyQuery, historyStatus]);

  async function createShipment() {
    const warehouseExit = shipmentMode === "warehouse_exit";
    if ((!warehouseExit && !salesOrderId) || (warehouseExit && !warehouseExitReference.trim())) return;
    setError("");
    setMessage("");
    try {
      const shipment = await api.post<ShipmentRow>("/api/shipments", {
        sales_order_id: warehouseExit ? null : salesOrderId,
        notes: warehouseExit ? warehouseExitReference.trim() : null,
      });
      setActiveShipmentId(Number(shipment.id));
      setWarehouseExitReference("");
      setMessage(
        warehouseExit
          ? t("page.shipments.warehouseExitCreated", { shipment: shipment.shipment_no })
          : t("page.shipments.salesShipmentCreated", {
              shipment: shipment.shipment_no,
              count: Number(shipment.packages_count || 0),
            }),
      );
      setScanResult(null);
      setScanCode("");
      await Promise.all([mutate(), mutateOrders()]);
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }

  async function addAllReady() {
    if (!activeShipmentId) return;
    setError("");
    setMessage("");
    try {
      await api.post(`/api/shipments/${activeShipmentId}/add-ready-packages`);
      setMessage(t("page.shipments.allReadyAdded"));
      await Promise.all([mutate(), mutatePreparation()]);
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }

  async function scanPackage() {
    if (!activeShipmentId || !scanCode.trim()) return;
    setError("");
    setMessage("");
    try {
      const result = await api.post<Record<string, unknown>>(`/api/shipments/${activeShipmentId}/scan-package`, {
        code: scanCode.trim(),
      });
      setScanResult(result);
      if (String(result.sign || "") === "error") {
        setError(String(result.message || t("page.shipments.scanMismatch")));
      } else {
        setMessage(String(result.message || t("page.shipments.scanProcessed")));
      }
      setScanCode("");
      await Promise.all([mutate(), mutatePreparation()]);
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }

  async function shipActive() {
    if (!activeShipmentId) return;
    setError("");
    setMessage("");
    if (!(await dialogs.ask({ message: t("page.shipments.confirmMarkShipped") }))) return;
    try {
      await api.post(`/api/shipments/${activeShipmentId}/ship`);
      setMessage(t("page.shipments.markedShipped"));
      await Promise.all([mutate(), mutatePreparation()]);
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }

  async function deliverActive() {
    if (!activeShipmentId) return;
    setError("");
    setMessage("");
    if (!(await dialogs.ask({ message: t("page.shipments.confirmMarkDelivered") }))) return;
    try {
      await api.post(`/api/shipments/${activeShipmentId}/deliver`);
      setMessage(t("page.shipments.markedDelivered"));
      await Promise.all([mutate(), mutatePreparation()]);
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }

  function selectShipment(shipment: ShipmentRow) {
    setActiveShipmentId(Number(shipment.id || 0));
    setScanResult(null);
    setScanCode("");
    setError("");
    setSalesOrderId(Number(shipment.sales_order_id || 0));
    setMessage(t("page.shipments.shipmentSelected", { shipment: shipment.shipment_no }));
  }

  function selectSalesOrder(orderId: number) {
    const choice = shipmentOrderChoices.find((order) => Number(order.id) === Number(orderId));
    setSalesOrderId(Number(orderId));
    setActiveShipmentId(Number(choice?.shipment_id || 0));
    setScanResult(null);
    setScanCode("");
    setError("");
    setMessage("");
  }

  async function markRowShipped(shipment: ShipmentRow) {
    if (!(await dialogs.ask({ message: t("page.shipments.confirmRowShipped", { shipment: shipment.shipment_no }) }))) return;
    setError("");
    try {
      await api.post(`/api/shipments/${shipment.id}/ship`);
      await mutate();
      if (Number(activeShipmentId) === Number(shipment.id)) await mutatePreparation();
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }

  async function markRowDelivered(shipment: ShipmentRow) {
    if (!(await dialogs.ask({ message: t("page.shipments.confirmRowDelivered", { shipment: shipment.shipment_no }) }))) return;
    setError("");
    try {
      await api.post(`/api/shipments/${shipment.id}/deliver`);
      await mutate();
      if (Number(activeShipmentId) === Number(shipment.id)) await mutatePreparation();
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }

  return (
    <div>
      <PageHeader title={t("page.shipments.title")} />
      <div className="max-w-[1440px] space-y-4">
        <section className="card p-4 sm:p-5">
          <div className="mb-3">
            <h2 className="app-card-title">{t("page.shipments.createShipment")}</h2>
            <p className="mt-1 text-sm text-[#6f6a5b]">{t("page.shipments.createShipmentHint")}</p>
          </div>
          <div className="grid gap-3 lg:grid-cols-[220px_minmax(320px,1fr)_auto] lg:items-end">
            <div>
              <label className="label">{t("page.shipments.createType")}</label>
              <select
                className="input"
                value={shipmentMode}
                onChange={(event) => setShipmentMode(event.target.value as "sales_order" | "warehouse_exit")}
              >
                <option value="sales_order">{t("page.shipments.fromSalesOrder")}</option>
                <option value="warehouse_exit">{t("page.shipments.withoutSalesOrder")}</option>
              </select>
            </div>
            {shipmentMode === "sales_order" ? (
              <div className="min-w-0">
                <label className="label">{t("page.shipments.salesOrder")}</label>
                <SearchableSelect<number>
                  inputId="shipment-sales-order"
                  value={salesOrderId || null}
                  options={shipmentOrderOptions}
                  onChange={(value) => selectSalesOrder(Number(value))}
                  placeholder={t("page.shipments.chooseSalesOrder")}
                  noResultsText={t("page.shipments.noOrderMatches")}
                />
                <p className="mt-1.5 text-xs text-[#6f6a5b]">{t("page.shipments.orderSelectorHint")}</p>
              </div>
            ) : (
              <div className="min-w-0">
                <label className="label">{t("page.shipments.exitReference")}</label>
                <input
                  className="input"
                  value={warehouseExitReference}
                  onChange={(event) => setWarehouseExitReference(event.target.value)}
                  placeholder={t("page.shipments.exitReferencePlaceholder")}
                />
              </div>
            )}
            <button
              type="button"
              className="btn btn-primary"
              onClick={createShipment}
              disabled={shipmentMode === "sales_order" ? !salesOrderId || activeShipmentId > 0 : !warehouseExitReference.trim()}
            >
              {shipmentMode === "warehouse_exit"
                ? t("page.shipments.createWarehouseExit")
                : activeShipmentId > 0
                  ? t("page.shipments.shipmentAlreadyCreated")
                  : t("btn.createShipment")}
            </button>
          </div>
          {shipmentMode === "warehouse_exit" ? <p className="mt-2 text-xs text-[#6f6a5b]">{t("page.shipments.warehouseExitHint")}</p> : null}
        </section>

        {message ? <div className="border-l-2 border-emerald-600 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{message}</div> : null}
        {error ? <div className="border-l-2 border-rose-600 bg-rose-50 px-3 py-2 text-sm text-rose-800">{error}</div> : null}
        {scanResult?.package_no ? <div className="text-xs text-[#56503f]">{t("page.shipments.lastScan")}: {String(scanResult.package_no)}</div> : null}

        <ShipmentPreparationWorkspace
          preparation={preparation}
          isLoading={Boolean(activeShipmentId) && isPreparationLoading}
          scanCode={scanCode}
          onScanCodeChange={setScanCode}
          onScan={scanPackage}
          onAddReadyPackages={addAllReady}
          onShip={shipActive}
          onDeliver={deliverActive}
          canTraceability={canTraceability}
        />

        <section className="card overflow-hidden">
          <div className="flex flex-wrap items-end justify-between gap-3 border-b border-[#ded9ca] px-4 py-3 sm:px-5">
            <div>
              <h2 className="app-card-title">{t("page.shipments.history")}</h2>
              <p className="mt-1 text-xs text-[#6f6a5b]">{t("page.shipments.historyHint")}</p>
            </div>
            <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row">
              <input
                className="input w-full sm:w-72"
                value={historyQuery}
                onChange={(event) => setHistoryQuery(event.target.value)}
                placeholder={t("page.shipments.historySearch")}
                aria-label={t("page.shipments.historySearch")}
              />
              <select
                className="input w-full sm:w-44"
                value={historyStatus}
                onChange={(event) => setHistoryStatus(event.target.value)}
                aria-label={t("field.status")}
              >
                <option value="all">{t("page.shipments.allStatuses")}</option>
                {["created", "shipped", "delivered", "cancelled"].map((status) => (
                  <option key={status} value={status}>{statusLabel(status, t)}</option>
                ))}
              </select>
            </div>
          </div>
          <div className="divide-y divide-[#ded9ca] md:hidden">
            {filteredHistory.map((shipment) => (
              <article
                key={shipment.id}
                className={`p-4 ${shipment.id === activeShipmentId ? "bg-yellow-50" : ""}`}
                onClick={() => selectShipment(shipment)}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="mono font-semibold text-[#14110b]">{shipment.shipment_no}</div>
                  <span className="badge">{statusLabel(shipment.status, t)}</span>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-[#56503f]">
                  <span>{shipment.sales_order_id ? t("page.shipments.fromSalesOrder") : t("page.shipments.warehouseExit")}</span>
                  <span className="text-right mono">{shipment.sales_order_no || "-"}</span>
                  <span>{shipment.customer_name || "-"}</span>
                  <span className="text-right tabular-nums">{Number(shipment.packages_count || 0)} {t("field.packages")} · {Number(shipment.total_qty || 0).toLocaleString()} {t("page.shipments.pieces")}</span>
                </div>
                {shipment.notes ? <div className="mt-2 text-xs text-[#56503f]">{t("page.shipments.reference")}: {shipment.notes}</div> : null}
                <div className="mt-3 flex flex-wrap gap-2">
                  <button type="button" className="btn h-8 px-2.5 text-[11px]" onClick={(event) => { event.stopPropagation(); selectShipment(shipment); }}>
                    {Number(shipment.id) === Number(activeShipmentId) ? t("page.shipments.selected") : t("page.shipments.select")}
                  </button>
                  {canTraceability ? (
                    <Link
                      className="btn h-8 px-2.5 text-[11px]"
                      href={`/traceability?shipment=${encodeURIComponent(shipment.shipment_no || shipment.id)}`}
                      onClick={(event) => event.stopPropagation()}
                    >
                      {t("page.shipments.traceability")}
                    </Link>
                  ) : null}
                  {["draft", "created"].includes(String(shipment.status || "")) ? (
                    <button type="button" className="btn h-8 px-2.5 text-[11px]" onClick={(event) => { event.stopPropagation(); void markRowShipped(shipment); }}>
                      {t("page.shipments.markAsShipped")}
                    </button>
                  ) : null}
                  {String(shipment.status || "") === "shipped" ? (
                    <button type="button" className="btn h-8 px-2.5 text-[11px]" onClick={(event) => { event.stopPropagation(); void markRowDelivered(shipment); }}>
                      {t("page.shipments.markAsDelivered")}
                    </button>
                  ) : null}
                </div>
              </article>
            ))}
            {!filteredHistory.length ? <div className="p-8 text-center text-sm text-[#6f6a5b]">{t("page.shipments.noHistoryMatches")}</div> : null}
          </div>
          <div className="hidden overflow-x-auto md:block">
            <table className="table min-w-[1280px]">
              <thead>
                <tr>
                  <th>{t("field.shipmentNo")}</th>
                  <th>{t("page.shipments.type")}</th>
                  <th>{t("page.shipments.salesOrder")}</th>
                  <th>{t("field.customer")}</th>
                  <th>{t("page.shipments.reference")}</th>
                  <th>{t("field.packages")}</th>
                  <th>{t("field.totalQty")}</th>
                  <th>{t("field.status")}</th>
                  <th>{t("field.shipped")}</th>
                  <th>{t("field.delivered")}</th>
                  <th>{t("field.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {filteredHistory.map((shipment) => (
                  <tr
                    key={shipment.id}
                    className={`${shipment.id === activeShipmentId ? "bg-yellow-50" : ""} cursor-pointer`}
                    onClick={() => selectShipment(shipment)}
                  >
                    <td className="mono whitespace-nowrap font-semibold text-[#14110b]">{shipment.shipment_no}</td>
                    <td>{shipment.sales_order_id ? t("page.shipments.fromSalesOrder") : t("page.shipments.warehouseExit")}</td>
                    <td className="mono whitespace-nowrap">{shipment.sales_order_no || "-"}</td>
                    <td>{shipment.customer_name || "-"}</td>
                    <td className="max-w-56 whitespace-normal">{shipment.notes || "-"}</td>
                    <td className="tabular-nums">{Number(shipment.packages_count || 0)}</td>
                    <td className="tabular-nums">{Number(shipment.total_qty || 0).toLocaleString()}</td>
                    <td><span className="badge">{statusLabel(shipment.status, t)}</span></td>
                    <td className="whitespace-nowrap">{shipment.shipped_at ? new Date(shipment.shipped_at).toLocaleString() : "-"}</td>
                    <td className="whitespace-nowrap">{shipment.delivered_at ? new Date(shipment.delivered_at).toLocaleString() : "-"}</td>
                    <td>
                      <div className="flex flex-wrap gap-2 whitespace-nowrap">
                        <button type="button" className="btn h-8 px-2.5 text-[11px]" onClick={(event) => { event.stopPropagation(); selectShipment(shipment); }}>
                          {Number(shipment.id) === Number(activeShipmentId) ? t("page.shipments.selected") : t("page.shipments.select")}
                        </button>
                        {canTraceability ? (
                          <Link
                            className="btn h-8 px-2.5 text-[11px]"
                            href={`/traceability?shipment=${encodeURIComponent(shipment.shipment_no || shipment.id)}`}
                            onClick={(event) => event.stopPropagation()}
                          >
                            {t("page.shipments.traceability")}
                          </Link>
                        ) : null}
                        {["draft", "created"].includes(String(shipment.status || "")) ? (
                          <button type="button" className="btn h-8 px-2.5 text-[11px]" onClick={(event) => { event.stopPropagation(); void markRowShipped(shipment); }}>
                            {t("page.shipments.markAsShipped")}
                          </button>
                        ) : null}
                        {String(shipment.status || "") === "shipped" ? (
                          <button type="button" className="btn h-8 px-2.5 text-[11px]" onClick={(event) => { event.stopPropagation(); void markRowDelivered(shipment); }}>
                            {t("page.shipments.markAsDelivered")}
                          </button>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                ))}
                {!filteredHistory.length ? <tr><td colSpan={11} className="py-8 text-center text-sm text-[#6f6a5b]">{t("page.shipments.noHistoryMatches")}</td></tr> : null}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  );
}
