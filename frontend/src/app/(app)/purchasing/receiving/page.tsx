"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import useSWR from "swr";
import { ArrowLeft, PackageCheck, X } from "lucide-react";
import PageHeader from "@/components/PageHeader";
import { api, fetcher } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { statusLabel } from "@/components/StagePipeline";
import { LIVE_DATA_SWR_OPTIONS } from "@/lib/liveData";

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
};

type PurchaseOrder = {
  id: number;
  po_no: string;
  request_no?: string | null;
  supplier_id?: number | null;
  supplier_name?: string | null;
  status: string;
  lines: PurchaseOrderLine[];
};

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
  batch_no: string;
  warehouse_id: number;
  supplier_id: number;
  cost_per_unit: string;
  message: string;
  saving: boolean;
};

const RECEIVABLE_ORDER_STATUSES = new Set(["sent", "approved", "partially_received"]);

function fmtQty(value: number | string | null | undefined) {
  const n = Number(value || 0);
  return Number.isFinite(n) ? n.toFixed(2) : "0.00";
}

function lineItemLabel(line: PurchaseOrderLine) {
  return [line.item_sku, line.item_name].filter(Boolean).join(" - ") || `#${line.item_id}`;
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
  const { me } = useMe();
  const canReceive = can(me, "purchasing.receive");
  const canView = can(me, "purchasing.view", "purchasing.receive");
  const [message, setMessage] = useState("");
  const [receiveState, setReceiveState] = useState<ReceiveState | null>(null);
  const { data: orders, mutate: refreshOrders } = useSWR<PurchaseOrder[]>(
    canView ? "/api/purchasing/orders" : null,
    fetcher,
    LIVE_DATA_SWR_OPTIONS,
  );
  const { data: warehouses } = useSWR<Warehouse[]>(canReceive ? "/api/inventory/warehouses" : null, fetcher);
  const { data: suppliers } = useSWR<Supplier[]>(canReceive ? "/api/suppliers" : null, fetcher);

  const openOrders = useMemo(
    () => (orders || []).filter((order) => RECEIVABLE_ORDER_STATUSES.has(order.status) && order.lines.some((line) => Number(line.remaining_quantity || 0) > 0)),
    [orders],
  );
  const storageWarehouses = useMemo(
    () => (warehouses || []).filter((warehouse) => ["fabric_storage", "accessory_storage", "packaging"].includes(String(warehouse.type || ""))),
    [warehouses],
  );

  function openReceive(order: PurchaseOrder, line: PurchaseOrderLine) {
    setMessage("");
    setReceiveState({
      order,
      line,
      received_quantity: String(Number(line.remaining_quantity || 0).toFixed(4)).replace(/\.?0+$/, ""),
      batch_no: `${order.po_no}-${line.id}`,
      warehouse_id: Number(line.warehouse_id || storageWarehouses[0]?.id || 0),
      supplier_id: Number(order.supplier_id || 0),
      cost_per_unit: String(Number(line.unit_cost || 0)),
      message: "",
      saving: false,
    });
  }

  async function submitReceive(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!receiveState) return;
    const quantity = Number(receiveState.received_quantity || 0);
    const warehouseId = Number(receiveState.warehouse_id || 0);
    const cost = Number(receiveState.cost_per_unit || 0);
    if (!Number.isFinite(quantity) || quantity <= 0) {
      setReceiveState({ ...receiveState, message: t("page.purchasing.receiveQtyRequired") });
      return;
    }
    if (!warehouseId) {
      setReceiveState({ ...receiveState, message: t("page.purchasing.receiveWarehouseRequired") });
      return;
    }
    setReceiveState({ ...receiveState, saving: true, message: "" });
    try {
      await api.post(`/api/purchasing/orders/${receiveState.order.id}/receive`, {
        supplier_id: receiveState.supplier_id || null,
        lines: [
          {
            purchase_order_line_id: receiveState.line.id,
            received_quantity: quantity,
            batch_no: receiveState.batch_no.trim(),
            warehouse_id: warehouseId,
            cost_per_unit: Number.isFinite(cost) ? cost : 0,
          },
        ],
      });
      refreshOrders();
      setReceiveState(null);
      setMessage(t("page.purchasing.received"));
    } catch (error: any) {
      setReceiveState((prev) => prev ? { ...prev, saving: false, message: error?.message || t("page.purchasing.actionFailed") } : prev);
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

      <section className="card overflow-hidden">
        <div className="border-b border-[#ecebe3] px-5 py-4">
          <h2 className="app-card-title">{t("page.purchasing.pendingOrders")}</h2>
        </div>
        <div className="overflow-x-auto px-5 py-4">
          <table className="table">
            <thead>
              <tr>
                <th>{t("field.purchaseOrder")}</th>
                <th>{t("field.item")}</th>
                <th>{t("field.remaining")}</th>
                <th>{t("field.warehouse")}</th>
                <th>{t("common.status")}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {openOrders.flatMap((order) => (
                order.lines
                  .filter((line) => Number(line.remaining_quantity || 0) > 0)
                  .map((line) => (
                    <tr key={`${order.id}-${line.id}`}>
                      <td>
                        <div className="mono font-semibold text-[#14110b]">{order.po_no}</div>
                        <div className="text-xs text-[#8a8472]">{order.supplier_name || order.request_no || "-"}</div>
                      </td>
                      <td>{lineItemLabel(line)}</td>
                      <td className="mono">
                        {fmtQty(line.remaining_quantity)} / {fmtQty(line.ordered_quantity)} {line.unit}
                      </td>
                      <td>{line.warehouse_name || "-"}</td>
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
                  ))
              ))}
              {openOrders.length === 0 && (
                <tr>
                  <td colSpan={6} className="text-sm text-slate-400">{t("page.purchasing.noOpenOrders")}</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {receiveState && (
        <div className="fixed inset-0 z-40 bg-black/40">
          <div className="absolute inset-0 overflow-y-auto p-4 md:p-6">
            <form onSubmit={submitReceive} className="card mx-auto w-full max-w-2xl p-5">
              <div className="mb-4 flex items-start justify-between gap-4">
                <div>
                  <div className="text-lg font-semibold text-[#14110b]">{t("page.purchasing.receiveOrder")}</div>
                  <div className="mt-1 text-sm text-[#6f684f]">{receiveState.order.po_no} - {lineItemLabel(receiveState.line)}</div>
                </div>
                <button type="button" className="icon-btn" onClick={() => setReceiveState(null)} aria-label={t("common.close")}>
                  <X />
                </button>
              </div>

              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <div>
                  <label className="label">{t("field.quantity")}</label>
                  <input
                    className="input"
                    type="number"
                    min={0}
                    step="0.0001"
                    max={Number(receiveState.line.remaining_quantity || 0)}
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
              </div>
              {receiveState.message && <div className="mt-3 text-sm text-red-600">{receiveState.message}</div>}
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
