"use client";

import { localizeError } from "@/lib/errorMessages";
import Link from "next/link";
import ShipmentAddClient from "@/components/ShipmentAddClient";
import SearchableSelect from "@/components/SearchableSelect";
import { packageWorkflowCopy, pendingPackageWorkflow, postPackageWorkflow } from "@/lib/packageWorkflow";
import { manualShipmentText } from "@/lib/manualShipmentText";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";

import ShipmentWorkspaceTable, { type ShipmentWorkspaceRow } from "@/components/ShipmentWorkspaceTable";
import PageHeader from "@/components/PageHeader";
import ShipmentPreparationWorkspace, {
  type ShipmentPreparation,
  type ShipmentSummary,
} from "@/components/ShipmentPreparationWorkspace";
import { useDialogs } from "@/components/DialogProvider";
import { api, fetcher } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { ShipmentTransportFields, normalizeTransportDetails, type TransportDetails } from "@/components/ShipmentTransportDetails";
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

function errorMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return localizeError("Action failed.");
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
        setError(result.message ? localizeError(String(result.message), 400) : t("page.shipments.scanMismatch"));
      } else {
        setMessage(t("page.shipments.scanProcessed"));
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
    <article id={order.id ? `shipment-order-${order.id}` : `shipment-${shipmentId}`} className="scroll-mt-4">
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
        onReviewChanged={refresh}
      />
    </article>
  );
}

export default function ShipmentsPage() {
  const { t, lang } = useT();
  const { me } = useMe();
  const canTraceability = can(me, "traceability.view");
  const searchParams = useSearchParams();
  const { data, mutate } = useSWR<ShipmentRow[]>("/api/shipments", fetcher);
  const { data: orders, mutate: mutateOrders } = useSWR<EligibleOrder[]>("/api/shipments/eligible-orders", fetcher);
  const [orderQuery, setOrderQuery] = useState("");
  const [createdShipmentId, setCreatedShipmentId] = useState<number | null>(null);
  const manualText = manualShipmentText[lang];
  const { data: customers, mutate: mutateCustomers } = useSWR<Array<{ id: number; name: string }>>(can(me, "storage.shipment") ? "/api/shipments/customers" : null, fetcher);
  const [customerId, setCustomerId] = useState<number | null>(null);
  const [pendingManual, setPendingManual] = useState<Record<string, any> | null>(null);
  useEffect(() => {
    if (!me?.id) return;
    const pending = pendingPackageWorkflow("/api/shipments", me.id);
    if (pending) { setPendingManual(pending.body); setCustomerId(pending.body.customer_id); }
  }, [me?.id]);
  const [warehouseTransport, setWarehouseTransport] = useState<TransportDetails>({});
  const [warehouseCreating, setWarehouseCreating] = useState(false);
  const [warehouseMessage, setWarehouseMessage] = useState("");
  const [warehouseError, setWarehouseError] = useState("");

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


  async function refreshOrders() {
    await Promise.all([mutate(), mutateOrders()]);
  }

  async function createWarehouseExit() {
    if (!customerId || warehouseCreating) return;
    setWarehouseError("");
    setWarehouseMessage("");
    setWarehouseCreating(true);
    try {
      const shipment = await postPackageWorkflow<ShipmentRow>("/api/shipments", pendingManual || { manual: true, customer_id: customerId, transport_details: normalizeTransportDetails(warehouseTransport) }, me!.id);
      setCreatedShipmentId(shipment.id);
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

  const requestedShipmentId = createdShipmentId || Number(searchParams.get("shipment_id") || 0);
  const requestedOrderId = Number(searchParams.get("so_id") || 0);
  const standalone = (data || []).filter(shipment =>
    !shipmentOrders.some(order => order.shipment?.id === shipment.id) && (
      (!shipment.sales_order_id && ["draft", "created"].includes(shipment.status)) ||
      (shipment.shipment_type === "manual" && shipment.status === "shipped") ||
      (shipment.id === requestedShipmentId && shipment.status !== "cancelled")
    )).filter(shipment => !orderQuery.trim() || [shipment.shipment_no, shipment.sales_order_no, shipment.customer_name]
      .some(value => String(value || "").toLocaleLowerCase().includes(orderQuery.trim().toLocaleLowerCase())));
  function workspaceRow(order: ShipmentOrder): ShipmentWorkspaceRow {
    const shipment = order.shipment;
    return {
      key: shipment ? `shipment-${shipment.id}` : `order-${order.id}`,
      reference: shipment?.shipment_no || order.order_no,
      order: order.order_no || shipment?.sales_order_no || "",
      customer: order.customer_name || shipment?.customer_name || "",
      status: shipment?.status || "draft",
      packages: Number(shipment?.packages_count || 0),
      quantity: Number(shipment?.total_qty || order.ready_qty || 0),
      workspace: <ShipmentOrderWorkspace order={order} canTraceability={canTraceability} onChanged={refreshOrders} />,
    };
  }
  const workspaceRows = [
    ...filteredOrders.map(workspaceRow),
    ...standalone.map(shipment => workspaceRow({ id: 0, order_no: "", status: shipment.status, shipment, is_scanned: !!shipment.is_complete })),
  ];
  const requestedOrder = shipmentOrders.find(order => order.id === requestedOrderId);
  const requestedKey = requestedShipmentId ? `shipment-${requestedShipmentId}` : requestedOrder
    ? requestedOrder.shipment ? `shipment-${requestedOrder.shipment.id}` : `order-${requestedOrder.id}` : undefined;

  return (
    <div>
      <PageHeader title={t("page.shipments.title")} actions={<Link className="btn" href="/shipments/history">{t("page.shipments.history")}</Link>} />
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

        <ShipmentWorkspaceTable rows={workspaceRows} requestedKey={requestedKey} />

        {can(me, "storage.shipment") && <section id="warehouse-exit" className="card p-4 sm:p-5">
          <div className="mb-3"><h2 className="app-card-title">{manualText.title}</h2><p className="mt-1 text-xs text-[#6f6a5b]">{manualText.hint}</p></div>
          {warehouseMessage ? <div className="mb-3 border-l-2 border-emerald-600 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{warehouseMessage}</div> : null}
          {pendingManual && <p role="status" className="mb-3 text-sm">{packageWorkflowCopy[lang].pendingRequest}</p>}
          {warehouseError ? <div className="mb-3 border-l-2 border-rose-600 bg-rose-50 px-3 py-2 text-sm text-rose-800">{warehouseError}</div> : null}
          <div className="flex flex-col gap-2 sm:flex-row">
            <div className="min-w-0 flex-1"><SearchableSelect value={customerId} options={(customers || []).map(customer => ({ value: customer.id, label: customer.name }))} onChange={value => setCustomerId(Number(value))} placeholder={manualText.choose} noResultsText={manualText.none} disabled={warehouseCreating || !!pendingManual} /></div>
            <ShipmentAddClient disabled={warehouseCreating || !!pendingManual} onCreated={client => { void mutateCustomers([...(customers || []), client], false); setCustomerId(client.id); }} />
            <button type="button" className="btn btn-primary" onClick={createWarehouseExit} disabled={warehouseCreating || !customerId}>{manualText.title}</button>
          </div>
          {can(me, "storage.shipment") && <details className="mt-3">
            <summary className="cursor-pointer text-sm font-medium">{shipmentTransportText[lang].optional}</summary>
            <div className="mt-3"><ShipmentTransportFields value={warehouseTransport} onChange={setWarehouseTransport} disabled={warehouseCreating || !!pendingManual} /></div>
          </details>}
        </section>}




      </div>
    </div>
  );
}
