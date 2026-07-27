"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import useSWR from "swr";
import { Check, PackageCheck, Plus, ShoppingCart, X } from "lucide-react";
import PageHeader from "@/components/PageHeader";
import { api, fetcher } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { statusLabel } from "@/components/StagePipeline";
import { LIVE_DATA_SWR_OPTIONS } from "@/lib/liveData";

type SalesOrder = {
  id: number;
  order_no?: string | null;
  status?: string | null;
  customer?: { name?: string | null } | null;
  customer_name?: string | null;
};

type ShortageRow = {
  sales_order_id: number;
  sales_order_no: string;
  item_id: number;
  sku: string;
  name: string;
  required_quantity: number;
  available_quantity: number;
  shortage: number;
  unit: string;
};

type Item = {
  id: number;
  sku: string;
  name: string;
  unit: string;
  category?: string | null;
};

type StockLine = {
  item_id: number;
  quantity: number;
  unit: string;
};

type StockBatch = {
  id: number;
  item_id: number;
  item_sku?: string | null;
  item_name?: string | null;
  item_category?: string | null;
  batch_no: string;
  color?: string | null;
  color_code?: string | null;
  available_quantity?: number | null;
  quantity: number;
  unit: string;
};

type PurchaseItemOption = {
  key: string;
  source: "batch" | "item";
  item_id: number;
  sku: string;
  name: string;
  unit: string;
  category?: string | null;
  batch_no?: string | null;
  color?: string | null;
  color_code?: string | null;
  available_quantity?: number | null;
};

type Supplier = {
  id: number;
  name: string;
};

type PurchaseRequestLine = {
  id: number;
  item_id: number;
  item_sku?: string | null;
  item_name?: string | null;
  requested_quantity: number;
  shortage_quantity: number;
  unit: string;
};

type PurchaseRequest = {
  id: number;
  request_no: string;
  status: string;
  sales_order_no?: string | null;
  lines: PurchaseRequestLine[];
};

type PurchaseOrder = {
  id: number;
  po_no: string;
  request_no?: string | null;
  supplier_name?: string | null;
  status: string;
  lines: { id: number; remaining_quantity: number }[];
};

const EMPTY_FORM = {
  item_key: "",
  requested_quantity: "",
  preferred_supplier_id: 0,
  notes: "",
};

const RECEIVABLE_ORDER_STATUSES = new Set(["sent", "approved", "partially_received"]);

function fmtQty(value: number | string | null | undefined) {
  const n = Number(value || 0);
  return Number.isFinite(n) ? n.toFixed(2) : "0.00";
}

function lineItemLabel(line: PurchaseRequestLine) {
  return [line.item_sku, line.item_name].filter(Boolean).join(" - ") || `#${line.item_id}`;
}

function itemOptionLabel(option: PurchaseItemOption) {
  const base = [option.sku, option.name].filter(Boolean).join(" - ") || `#${option.item_id}`;
  if (option.source !== "batch") return base;
  const meta = [option.color, option.color_code].filter(Boolean).join(" / ");
  return meta ? `${base} (${meta})` : base;
}

function StatusBadge({ status }: { status: string }) {
  const { t } = useT();
  const tone =
    status === "approved" || status === "received"
      ? "border-emerald-200 bg-emerald-50 text-emerald-700"
      : status === "rejected" || status === "cancelled"
        ? "border-red-200 bg-red-50 text-red-700"
        : status === "converted" || status === "partially_received"
          ? "border-amber-200 bg-amber-50 text-amber-700"
          : "border-[#ded9ca] bg-[#f7f4ed] text-[#56503f]";
  return <span className={`inline-flex rounded-md border px-2 py-1 text-xs font-medium ${tone}`}>{statusLabel(status, t)}</span>;
}

export default function PurchasingPage() {
  const { t } = useT();
  const { me } = useMe();
  const canView = can(me, "purchasing.view");
  const canRequest = can(me, "purchasing.request");
  const canApprove = can(me, "purchasing.approve");
  const canOrder = can(me, "purchasing.order");
  const [form, setForm] = useState(EMPTY_FORM);
  const [message, setMessage] = useState("");
  const [creatingRequestOrderId, setCreatingRequestOrderId] = useState<number | null>(null);
  const [requestBusyId, setRequestBusyId] = useState<number | null>(null);
  const [savingManualRequest, setSavingManualRequest] = useState(false);

  const { data: salesOrders } = useSWR<SalesOrder[]>(
    canView ? "/api/sales-orders?order_type=client_order&page_size=200" : null,
    fetcher,
  );
  const planningOrders = useMemo(
    () => (salesOrders || []).filter((order) => ["confirmed", "pending_sales_approval", "planning_approved"].includes(String(order.status || ""))),
    [salesOrders],
  );
  const orderIdKey = useMemo(() => planningOrders.map((order) => Number(order.id)).filter(Boolean).join(","), [planningOrders]);

  const { data: shortages, mutate: refreshShortages } = useSWR<ShortageRow[]>(
    canView && orderIdKey ? `purchasing-shortages:${orderIdKey}` : null,
    async () => {
      const orderById = new Map(planningOrders.map((order) => [Number(order.id), order]));
      const chunks = await Promise.all(
        orderIdKey.split(",").filter(Boolean).map(async (rawId) => {
          const salesOrderId = Number(rawId);
          const rows = await api.get<any[]>(`/api/planning/material-requirements/${salesOrderId}`);
          const order = orderById.get(salesOrderId);
          return rows
            .filter((row) => Number(row.shortage || 0) > 0)
            .map((row) => ({
              ...row,
              sales_order_id: salesOrderId,
              sales_order_no: order?.order_no || `#${salesOrderId}`,
            }));
        }),
      );
      return chunks.flat();
    },
  );

  const { data: requests, mutate: refreshRequests } = useSWR<PurchaseRequest[]>(
    canView ? "/api/purchasing/requests" : null,
    fetcher,
    LIVE_DATA_SWR_OPTIONS,
  );
  const { data: orders, mutate: refreshOrders } = useSWR<PurchaseOrder[]>(
    canView ? "/api/purchasing/orders" : null,
    fetcher,
    LIVE_DATA_SWR_OPTIONS,
  );
  const { data: materialItems } = useSWR<Item[]>(canRequest ? "/api/inventory/items?group=materials&page_size=500" : null, fetcher);
  const { data: accessoryItems } = useSWR<Item[]>(canRequest ? "/api/inventory/items?group=accessories&page_size=500" : null, fetcher);
  const { data: materialBatches } = useSWR<StockBatch[]>(canRequest ? "/api/inventory/batches?group=materials&page_size=500" : null, fetcher);
  const { data: materialStock } = useSWR<StockLine[]>(canRequest ? "/api/inventory/stock?group=materials" : null, fetcher);
  const { data: accessoryStock } = useSWR<StockLine[]>(canRequest ? "/api/inventory/stock?group=accessories" : null, fetcher);
  const { data: suppliers } = useSWR<Supplier[]>(canRequest ? "/api/suppliers" : null, fetcher);

  const materialBatchOptions = useMemo<PurchaseItemOption[]>(() => {
    return (materialBatches || []).map((batch) => ({
      key: `batch:${batch.id}`,
      source: "batch" as const,
      item_id: Number(batch.item_id),
      sku: batch.batch_no || batch.item_sku || "",
      name: batch.item_name || batch.item_sku || "",
      unit: batch.unit,
      category: batch.item_category,
      batch_no: batch.batch_no,
      color: batch.color,
      color_code: batch.color_code,
      available_quantity: batch.available_quantity ?? batch.quantity,
    }));
  }, [materialBatches]);
  const materialBatchItemIds = useMemo(
    () => new Set(materialBatchOptions.map((option) => Number(option.item_id))),
    [materialBatchOptions],
  );
  const materialItemOptions = useMemo<PurchaseItemOption[]>(() => {
    return (materialItems || [])
      .filter((item) => !materialBatchItemIds.has(Number(item.id)))
      .map((item) => ({
        key: `item:${item.id}`,
        source: "item" as const,
        item_id: Number(item.id),
        sku: item.sku,
        name: item.name,
        unit: item.unit,
        category: item.category,
      }))
      .sort((a, b) => itemOptionLabel(a).localeCompare(itemOptionLabel(b)));
  }, [materialBatchItemIds, materialItems]);
  const accessoryItemOptions = useMemo<PurchaseItemOption[]>(() => {
    return (accessoryItems || [])
      .map((item) => ({
        key: `item:${item.id}`,
        source: "item" as const,
        item_id: Number(item.id),
        sku: item.sku,
        name: item.name,
        unit: item.unit,
        category: item.category,
      }))
      .sort((a, b) => itemOptionLabel(a).localeCompare(itemOptionLabel(b)));
  }, [accessoryItems]);
  const optionByKey = useMemo(() => {
    const map = new Map<string, PurchaseItemOption>();
    for (const option of [...materialBatchOptions, ...materialItemOptions, ...accessoryItemOptions]) {
      map.set(option.key, option);
    }
    return map;
  }, [accessoryItemOptions, materialBatchOptions, materialItemOptions]);
  const stockByItem = useMemo(() => {
    const map = new Map<number, StockLine>();
    for (const row of [...(materialStock || []), ...(accessoryStock || [])]) map.set(Number(row.item_id), row);
    return map;
  }, [accessoryStock, materialStock]);
  const selectedItem = form.item_key ? optionByKey.get(form.item_key) : undefined;
  const selectedStock = selectedItem?.source === "batch"
    ? { item_id: selectedItem.item_id, quantity: Number(selectedItem.available_quantity || 0), unit: selectedItem.unit }
    : selectedItem ? stockByItem.get(selectedItem.item_id) : undefined;

  async function createRequestFromSalesOrder(salesOrderId: number) {
    setMessage("");
    setCreatingRequestOrderId(salesOrderId);
    try {
      const request = await api.post<PurchaseRequest>(`/api/purchasing/requests/from-sales-order/${salesOrderId}`);
      setMessage(t("page.purchasing.requestSent", { requestNo: request.request_no }));
      refreshRequests();
      refreshShortages();
    } catch (error: any) {
      setMessage(error?.message || t("page.purchasing.actionFailed"));
    } finally {
      setCreatingRequestOrderId(null);
    }
  }

  async function submitManualRequest(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const quantity = Number(form.requested_quantity || 0);
    if (!selectedItem || !Number.isFinite(quantity) || quantity <= 0) {
      setMessage(t("page.purchasing.requestQtyRequired"));
      return;
    }
    const available = Number(selectedStock?.quantity || 0);
    setSavingManualRequest(true);
    setMessage("");
    try {
      const batchNote = selectedItem.source === "batch"
        ? [
          `${t("field.batch")}: ${selectedItem.batch_no || selectedItem.sku}`,
          selectedItem.color ? `${t("field.color")}: ${selectedItem.color}` : "",
          selectedItem.color_code ? `${t("field.colorCode")}: ${selectedItem.color_code}` : "",
        ].filter(Boolean).join(" / ")
        : "";
      const request = await api.post<PurchaseRequest>("/api/purchasing/requests", {
        status: "pending_approval",
        notes: [form.notes.trim(), batchNote].filter(Boolean).join("\n") || null,
        lines: [
          {
            item_id: selectedItem.item_id,
            required_quantity: quantity,
            requested_quantity: quantity,
            unit: selectedItem.unit,
            available_quantity: available,
            shortage_quantity: Math.max(0, quantity - available),
            preferred_supplier_id: form.preferred_supplier_id || null,
          },
        ],
      });
      setForm(EMPTY_FORM);
      setMessage(t("page.purchasing.requestSent", { requestNo: request.request_no }));
      refreshRequests();
    } catch (error: any) {
      setMessage(error?.message || t("page.purchasing.actionFailed"));
    } finally {
      setSavingManualRequest(false);
    }
  }

  async function runRequestAction(requestId: number, action: "approve" | "reject" | "convert-to-order") {
    setMessage("");
    setRequestBusyId(requestId);
    try {
      await api.post(`/api/purchasing/requests/${requestId}/${action}`);
      refreshRequests();
      refreshOrders();
      setMessage(action === "approve" ? t("page.purchasing.approved") : action === "convert-to-order" ? t("page.purchasing.orderCreated") : "");
    } catch (error: any) {
      setMessage(error?.message || t("page.purchasing.actionFailed"));
    } finally {
      setRequestBusyId(null);
    }
  }

  const shortageRows = shortages || [];
  const requestRows = requests || [];
  const openOrderCount = (orders || []).filter((order) => RECEIVABLE_ORDER_STATUSES.has(order.status) && order.lines.some((line) => Number(line.remaining_quantity || 0) > 0)).length;

  if (!canView) {
    return (
      <div>
        <PageHeader title={t("page.purchasing.title")} subtitle={t("page.purchasing.noAccess")} />
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title={t("page.purchasing.title")}
        subtitle={t("page.purchasing.subtitle")}
        actions={(
          <Link className="btn" href="/purchasing/receiving">
            <PackageCheck className="h-4 w-4" />
            {t("nav.purchaseReceiving")} ({openOrderCount})
          </Link>
        )}
      />

      {message && <div className="mb-4 rounded-md border border-[#ded9ca] bg-[#fbfaf6] px-4 py-3 text-sm text-[#56503f]">{message}</div>}

      <div className="mb-6 grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(360px,0.8fr)]">
        <section className="card overflow-hidden">
          <div className="border-b border-[#ecebe3] px-5 py-4">
            <h2 className="app-card-title">{t("page.purchasing.shortagesTitle")}</h2>
          </div>
          <div className="overflow-x-auto px-5 py-4">
            <table className="table">
              <thead>
                <tr>
                  <th>{t("field.orderNo")}</th>
                  <th>{t("field.sku")}</th>
                  <th>{t("common.name")}</th>
                  <th>{t("field.required")}</th>
                  <th>{t("field.available")}</th>
                  <th>{t("field.shortage")}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {shortageRows.map((row) => (
                  <tr key={`${row.sales_order_id}-${row.item_id}-${row.unit}`}>
                    <td className="mono font-semibold text-[#14110b]">{row.sales_order_no}</td>
                    <td className="mono">{row.sku}</td>
                    <td>{row.name}</td>
                    <td className="mono">{fmtQty(row.required_quantity)} {row.unit}</td>
                    <td className="mono">{fmtQty(row.available_quantity)} {row.unit}</td>
                    <td className="mono font-semibold text-red-700">{fmtQty(row.shortage)} {row.unit}</td>
                    <td>
                      {canRequest && (
                        <button
                          type="button"
                          className="btn btn-primary whitespace-nowrap"
                          disabled={creatingRequestOrderId === row.sales_order_id}
                          onClick={() => createRequestFromSalesOrder(row.sales_order_id)}
                        >
                          <ShoppingCart className="h-4 w-4" />
                          {creatingRequestOrderId === row.sales_order_id ? t("common.creating") : t("page.purchasing.createRequest")}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
                {shortageRows.length === 0 && (
                  <tr>
                    <td colSpan={7} className="text-sm text-slate-400">{t("page.purchasing.noShortages")}</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        {canRequest && (
          <form onSubmit={submitManualRequest} className="card p-5">
            <h2 className="app-card-title">{t("page.purchasing.manualTitle")}</h2>
            <div className="mt-4 space-y-3">
              <div>
                <label className="label">{t("field.item")}</label>
                <select className="input" value={form.item_key} onChange={(event) => setForm({ ...form, item_key: event.target.value })} required>
                  <option value="">{t("page.purchasing.selectItem")}</option>
                  {materialBatchOptions.length > 0 && (
                    <optgroup label={`${t("page.masterData.materials")} / ${t("field.batch")}`}>
                      {materialBatchOptions.map((option) => (
                        <option key={option.key} value={option.key}>{itemOptionLabel(option)}</option>
                      ))}
                    </optgroup>
                  )}
                  {materialItemOptions.length > 0 && (
                    <optgroup label={t("page.masterData.materials")}>
                      {materialItemOptions.map((option) => (
                        <option key={option.key} value={option.key}>{itemOptionLabel(option)}</option>
                      ))}
                    </optgroup>
                  )}
                  {accessoryItemOptions.length > 0 && (
                    <optgroup label={t("page.masterData.accessories")}>
                      {accessoryItemOptions.map((option) => (
                        <option key={option.key} value={option.key}>{itemOptionLabel(option)}</option>
                      ))}
                    </optgroup>
                  )}
                </select>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">{t("field.requested")}</label>
                  <input
                    className="input"
                    type="number"
                    min={0}
                    step="0.0001"
                    value={form.requested_quantity}
                    onChange={(event) => setForm({ ...form, requested_quantity: event.target.value })}
                    required
                  />
                </div>
                <div>
                  <label className="label">{t("field.available")}</label>
                  <input className="input" value={`${fmtQty(selectedStock?.quantity)} ${selectedStock?.unit || selectedItem?.unit || ""}`.trim()} readOnly />
                </div>
              </div>
              <div>
                <label className="label">{t("field.supplier")}</label>
                <select className="input" value={form.preferred_supplier_id} onChange={(event) => setForm({ ...form, preferred_supplier_id: Number(event.target.value) })}>
                  <option value={0}>{t("ph.supplier")}</option>
                  {suppliers?.map((supplier) => (
                    <option key={supplier.id} value={supplier.id}>{supplier.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="label">{t("field.notes")}</label>
                <textarea className="input min-h-20" value={form.notes} onChange={(event) => setForm({ ...form, notes: event.target.value })} />
              </div>
              <button className="btn btn-primary w-full justify-center" disabled={savingManualRequest}>
                <Plus className="h-4 w-4" />
                {savingManualRequest ? t("common.creating") : t("page.purchasing.createRequest")}
              </button>
            </div>
          </form>
        )}
      </div>

      <section className="card overflow-hidden">
        <div className="border-b border-[#ecebe3] px-5 py-4">
          <h2 className="app-card-title">{t("page.purchasing.requestsTitle")}</h2>
        </div>
        <div className="overflow-x-auto px-5 py-4">
          <table className="table">
            <thead>
              <tr>
                <th>{t("field.purchaseRequest")}</th>
                <th>{t("field.orderNo")}</th>
                <th>{t("common.status")}</th>
                <th>{t("field.requested")}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {requestRows.map((request) => {
                const requestedQty = request.lines.reduce((sum, line) => sum + Number(line.requested_quantity || 0), 0);
                return (
                  <tr key={request.id}>
                    <td className="mono font-semibold text-[#14110b]">{request.request_no}</td>
                    <td>{request.sales_order_no || "-"}</td>
                    <td><StatusBadge status={request.status} /></td>
                    <td>
                      <div className="mono font-semibold text-[#14110b]">{fmtQty(requestedQty)}</div>
                      <div className="max-w-[280px] truncate text-xs text-[#8a8472]">{request.lines.map(lineItemLabel).join(", ") || "-"}</div>
                    </td>
                    <td>
                      <div className="flex flex-wrap justify-end gap-2">
                        {canApprove && ["draft", "pending_approval"].includes(request.status) && (
                          <>
                            <button type="button" className="btn" disabled={requestBusyId === request.id} onClick={() => runRequestAction(request.id, "approve")}>
                              <Check className="h-4 w-4" />
                              {t("btn.approve")}
                            </button>
                            <button type="button" className="btn" disabled={requestBusyId === request.id} onClick={() => runRequestAction(request.id, "reject")}>
                              <X className="h-4 w-4" />
                              {t("btn.reject")}
                            </button>
                          </>
                        )}
                        {canOrder && request.status === "approved" && (
                          <button type="button" className="btn btn-primary" disabled={requestBusyId === request.id} onClick={() => runRequestAction(request.id, "convert-to-order")}>
                            <ShoppingCart className="h-4 w-4" />
                            {t("page.purchasing.createOrder")}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
              {requestRows.length === 0 && (
                <tr>
                  <td colSpan={5} className="text-sm text-slate-400">{t("page.purchasing.noRequests")}</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
