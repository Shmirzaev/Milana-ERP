"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { ClipboardCheck, ExternalLink, PackageCheck, Pencil, Plus, RefreshCw, Scissors, Shirt, Trash2 } from "lucide-react";

import Modal from "@/components/Modal";
import ModelAsyncSelect from "@/components/ModelAsyncSelect";
import PageHeader from "@/components/PageHeader";
import VerticalModelPhoto from "@/components/VerticalModelPhoto";
import { api, fetcher } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { GARMENT_SIZE_OPTIONS } from "@/lib/garmentSizes";
import { useT } from "@/lib/i18n";
import { storageThumbnailUrl } from "@/lib/modelImages";

type UslugaModel = {
  id: number;
  code: string;
  name: string;
  status: string;
  category?: string | null;
  details_json?: { general?: { variant_color?: string | null } | null } | null;
  sizes: Array<{ id: number; size: string }>;
  colors: Array<{ id: number; color_name: string }>;
  images: Array<{ id: number; file_url: string; image_type?: string | null; is_primary: boolean }>;
};

type WorkOrder = {
  id: number;
  operation: "cutting" | "sewing" | "packaging";
  status: string;
  planned_quantity: number;
  passed_quantity: number;
  failed_quantity: number;
};

type UslugaOrder = {
  id: number;
  order_no: string;
  status: string;
  customer_name: string;
  customer_reference: string | null;
  model: { id: number; code: string; name: string } | null;
  model_id: number;
  planned_quantity: number;
  deadline: string | null;
  material_description: string | null;
  material_usage_kg: number | null;
  handed_over_at: string | null;
  ready_for_handover: boolean;
  work_orders: WorkOrder[];
};

type PlanLine = { color: string; size: string; quantity: string };

function formatDate(value: string | null) {
  if (!value) return "—";
  return new Intl.DateTimeFormat(undefined, { year: "numeric", month: "short", day: "2-digit" }).format(new Date(value));
}

function workOrderLink(workOrder: WorkOrder) {
  return `/work-orders/${workOrder.id}/${workOrder.operation}`;
}

function orderedSizes(values: string[]) {
  const order = new Map(GARMENT_SIZE_OPTIONS.map((size, index) => [size, index]));
  return Array.from(new Set(values.filter(Boolean))).sort((left, right) => {
    const leftIndex = order.get(left) ?? Number.MAX_SAFE_INTEGER;
    const rightIndex = order.get(right) ?? Number.MAX_SAFE_INTEGER;
    return leftIndex - rightIndex || left.localeCompare(right, undefined, { numeric: true });
  });
}

export default function UslugaPage() {
  const { t } = useT();
  const { me } = useMe();
  const canManage = can(me, "usluga.manage", "*");
  const canHandover = can(me, "usluga.handover", "*");
  const { data: orders = [], error, isLoading, isValidating, mutate: mutateOrders } = useSWR<UslugaOrder[]>("/api/usluga/orders", fetcher);

  const [modelId, setModelId] = useState(0);
  const { data: selectedModel } = useSWR<UslugaModel>(modelId ? `/api/usluga/models/${modelId}` : null, fetcher);
  const modelSizes = useMemo(() => orderedSizes((selectedModel?.sizes || []).map((row) => row.size)), [selectedModel?.sizes]);
  const modelColor = String(selectedModel?.details_json?.general?.variant_color || selectedModel?.colors?.[0]?.color_name || "white");

  const [form, setForm] = useState({
    customer_name: "",
    customer_reference: "",
    deadline: "",
    material_description: "",
    material_usage_kg: "",
    material_notes: "",
  });
  const [lines, setLines] = useState<PlanLine[]>([]);
  const [sizeFrom, setSizeFrom] = useState("");
  const [sizeTo, setSizeTo] = useState("");
  const [distributionQty, setDistributionQty] = useState("");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState("");
  const [successOrder, setSuccessOrder] = useState<UslugaOrder | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [handoverOrder, setHandoverOrder] = useState<UslugaOrder | null>(null);
  const [handoverForm, setHandoverForm] = useState({ recipient: "", notes: "" });

  useEffect(() => {
    if (!selectedModel || !modelSizes.length) return;
    setLines((current) => current.length ? current : modelSizes.map((size) => ({ color: modelColor, size, quantity: "" })));
    setSizeFrom((current) => current || modelSizes[0]);
    setSizeTo((current) => current || modelSizes[modelSizes.length - 1]);
  }, [modelColor, modelSizes, selectedModel]);

  const totalQuantity = useMemo(
    () => lines.reduce((sum, line) => sum + Math.max(0, Number(line.quantity || 0)), 0),
    [lines],
  );
  const activeLines = useMemo(
    () => lines.filter((line) => line.color.trim() && line.size.trim() && Number(line.quantity || 0) > 0),
    [lines],
  );
  const filteredOrders = useMemo(() => {
    const query = search.trim().toLowerCase();
    return orders.filter((order) => {
      if (statusFilter && order.status !== statusFilter) return false;
      if (!query) return true;
      return [order.order_no, order.customer_name, order.customer_reference, order.model?.code, order.model?.name]
        .some((value) => String(value || "").toLowerCase().includes(query));
    });
  }, [orders, search, statusFilter]);

  function selectModel(nextModelId: number) {
    setModelId(nextModelId);
    setLines([]);
    setSizeFrom("");
    setSizeTo("");
    setDistributionQty("");
    setFormError("");
  }

  function updateLine(index: number, patch: Partial<PlanLine>) {
    setLines((current) => current.map((line, rowIndex) => rowIndex === index ? { ...line, ...patch } : line));
  }

  function addLine() {
    setLines((current) => [...current, { color: modelColor, size: modelSizes[0] || "", quantity: "" }]);
  }

  function distributeBySizeRange() {
    const start = modelSizes.indexOf(sizeFrom);
    const end = modelSizes.indexOf(sizeTo);
    const quantity = Math.floor(Number(distributionQty || 0));
    if (start < 0 || end < start || quantity < 1) {
      setFormError(t("usluga.distributionRequired"));
      return;
    }
    const sizes = modelSizes.slice(start, end + 1);
    const base = Math.floor(quantity / sizes.length);
    let remainder = quantity % sizes.length;
    setLines(sizes.map((size) => {
      const rowQuantity = base + (remainder > 0 ? 1 : 0);
      remainder = Math.max(0, remainder - 1);
      return { color: lines[0]?.color || modelColor, size, quantity: String(rowQuantity) };
    }));
    setFormError("");
  }

  async function createOrder() {
    if (!selectedModel) return setFormError(t("usluga.selectModel"));
    if (!form.customer_name.trim()) return setFormError(t("usluga.customerRequired"));
    if (!activeLines.length) return setFormError(t("usluga.sizeRequired"));
    setBusy(true);
    setFormError("");
    setSuccessOrder(null);
    try {
      const order = await api.post<UslugaOrder>("/api/usluga/orders", {
        customer_name: form.customer_name.trim(),
        customer_reference: form.customer_reference.trim() || null,
        model_id: selectedModel.id,
        lines: activeLines.map((line) => ({ color: line.color.trim(), size: line.size.trim(), quantity: Number(line.quantity) })),
        deadline: form.deadline ? new Date(`${form.deadline}T23:59:59+05:00`).toISOString() : null,
        material_description: form.material_description.trim() || null,
        material_usage_kg: form.material_usage_kg === "" ? null : Number(form.material_usage_kg),
        material_notes: form.material_notes.trim() || null,
      });
      await mutateOrders();
      setSuccessOrder(order);
      setForm({ customer_name: "", customer_reference: "", deadline: "", material_description: "", material_usage_kg: "", material_notes: "" });
      setLines(modelSizes.map((size) => ({ color: modelColor, size, quantity: "" })));
      setDistributionQty("");
    } catch (submitError: unknown) {
      setFormError(String((submitError as Error)?.message || submitError));
    } finally {
      setBusy(false);
    }
  }

  async function handOver() {
    if (!handoverOrder) return;
    setBusy(true);
    setFormError("");
    try {
      await api.post(`/api/usluga/orders/${handoverOrder.id}/handover`, handoverForm);
      await mutateOrders();
      setHandoverOrder(null);
    } catch (submitError: unknown) {
      setFormError(String((submitError as Error)?.message || submitError));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <PageHeader
        title={t("usluga.planningTitle")}
        subtitle={t("usluga.planningSubtitle")}
        actions={<div className="flex flex-wrap gap-2">
          <Link className="btn" href="/usluga/models">{t("usluga.openModels")}</Link>
          {canManage && <Link className="btn" href="/usluga/models/new?mode=edit"><Plus className="h-4 w-4" />{t("usluga.newModel")}</Link>}
          <button className="btn" type="button" onClick={() => void mutateOrders()} disabled={isValidating}>
            <RefreshCw className={`h-4 w-4 ${isValidating ? "animate-spin" : ""}`} />{t("common.refresh")}
          </button>
        </div>}
      />

      <div className="mb-5 border-y border-[#dedbd0] bg-[#fbfaf6] px-4 py-3 text-sm text-[#56503f]">
        {t("usluga.inventoryBoundary")}
      </div>

      {canManage && <div className="mb-7 grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="space-y-4">
          <section className="card p-4 sm:p-5">
            <div className="mb-4 flex items-center justify-between gap-3 border-b border-[#ecebe3] pb-3">
              <h2 className="text-base font-semibold text-[#242117]">{t("usluga.orderDetails")}</h2>
              {selectedModel && <Link className="inline-flex items-center gap-1 text-sm font-medium text-[#56503f] hover:underline" href={`/usluga/models/${selectedModel.id}`}>
                {t("usluga.openModel")}<ExternalLink className="h-3.5 w-3.5" />
              </Link>}
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <label className="md:col-span-2">
                <span className="label">{t("usluga.model")}</span>
                <ModelAsyncSelect inputId="usluga-model" value={modelId || null} onChange={selectModel} status="approved" endpoint="/api/usluga/model-options" placeholder={t("usluga.selectModel")} noResultsText={t("page.models.empty")} loadingText={t("common.loading")} loadMoreText={t("common.loadMore")} required />
              </label>
              <label><span className="label">{t("usluga.customer")}</span><input className="input" value={form.customer_name} onChange={(event) => setForm({ ...form, customer_name: event.target.value })} /></label>
              <label><span className="label">{t("usluga.customerReference")}</span><input className="input" value={form.customer_reference} onChange={(event) => setForm({ ...form, customer_reference: event.target.value })} /></label>
              <label><span className="label">{t("field.deadline")}</span><input className="input" type="date" value={form.deadline} onChange={(event) => setForm({ ...form, deadline: event.target.value })} /></label>
              <label><span className="label">{t("usluga.materialUsed")}</span><input className="input" type="number" min="0" step="0.01" value={form.material_usage_kg} onChange={(event) => setForm({ ...form, material_usage_kg: event.target.value })} /></label>
              <label className="md:col-span-2"><span className="label">{t("usluga.materialDescription")}</span><input className="input" value={form.material_description} onChange={(event) => setForm({ ...form, material_description: event.target.value })} /></label>
              <label className="md:col-span-2"><span className="label">{t("usluga.materialNotes")}</span><textarea className="input min-h-20" value={form.material_notes} onChange={(event) => setForm({ ...form, material_notes: event.target.value })} /></label>
            </div>
          </section>

          <section className="card overflow-hidden">
            <div className="flex flex-col gap-3 border-b border-[#ecebe3] p-4 sm:flex-row sm:items-end sm:justify-between">
              <div><h2 className="text-base font-semibold text-[#242117]">{t("usluga.quantityBySize")}</h2><p className="mt-1 text-sm text-[#8a8472]">{t("usluga.linesHint")}</p></div>
              <button type="button" className="btn" onClick={addLine} disabled={!selectedModel}><Plus className="h-4 w-4" />{t("usluga.addLine")}</button>
            </div>
            <div className="grid gap-3 border-b border-[#ecebe3] bg-[#fbfaf6] p-4 sm:grid-cols-4">
              <label><span className="label">{t("usluga.sizeFrom")}</span><select className="input" value={sizeFrom} onChange={(event) => setSizeFrom(event.target.value)} disabled={!modelSizes.length}>{modelSizes.map((size) => <option key={size} value={size}>{size}</option>)}</select></label>
              <label><span className="label">{t("usluga.sizeTo")}</span><select className="input" value={sizeTo} onChange={(event) => setSizeTo(event.target.value)} disabled={!modelSizes.length}>{modelSizes.map((size) => <option key={size} value={size}>{size}</option>)}</select></label>
              <label><span className="label">{t("field.quantity")}</span><input className="input" type="number" min="1" value={distributionQty} onChange={(event) => setDistributionQty(event.target.value)} /></label>
              <button type="button" className="btn self-end" onClick={distributeBySizeRange} disabled={!modelSizes.length}>{t("usluga.distribute")}</button>
            </div>
            <div className="overflow-x-auto"><table className="table min-w-[640px]">
              <thead><tr><th>{t("common.color")}</th><th>{t("common.size")}</th><th>{t("field.quantity")}</th><th className="w-14">{t("field.actions")}</th></tr></thead>
              <tbody>
                {lines.map((line, index) => <tr key={`${index}-${line.size}`}>
                  <td><input className="input min-w-36" value={line.color} onChange={(event) => updateLine(index, { color: event.target.value })} /></td>
                  <td><select className="input min-w-24" value={line.size} onChange={(event) => updateLine(index, { size: event.target.value })}>{modelSizes.map((size) => <option key={size} value={size}>{size}</option>)}</select></td>
                  <td><input className="input min-w-28" type="number" min="0" value={line.quantity} onChange={(event) => updateLine(index, { quantity: event.target.value })} /></td>
                  <td><button className="icon-btn text-red-700" type="button" title={t("common.delete")} onClick={() => setLines((current) => current.filter((_, rowIndex) => rowIndex !== index))}><Trash2 className="h-4 w-4" /></button></td>
                </tr>)}
                {!lines.length && <tr><td colSpan={4} className="p-6 text-center text-sm text-[#8a8472]">{selectedModel ? t("usluga.noSizes") : t("usluga.selectModel")}</td></tr>}
              </tbody>
            </table></div>
          </section>
        </div>

        <aside className="card p-4 xl:sticky xl:top-24">
          <h2 className="text-base font-semibold text-[#242117]">{t("usluga.planSummary")}</h2>
          {selectedModel ? <div className="mt-4 flex gap-3 border-b border-[#ecebe3] pb-4">
            <div className="h-24 w-[72px] shrink-0 overflow-hidden rounded-md border border-[#dedbd0] bg-[#f1efe8]">
              {selectedModel.images?.[0]?.file_url ? <VerticalModelPhoto src={storageThumbnailUrl(selectedModel.images[0].file_url, 240)} alt={selectedModel.name} className="h-full w-full" width={144} height={192} /> : null}
            </div>
            <div className="min-w-0"><div className="mono text-xs text-[#8a8472]">{selectedModel.code}</div><div className="mt-1 font-semibold text-[#242117]">{selectedModel.name}</div><div className="mt-1 text-xs text-[#8a8472]">{selectedModel.category || "—"}</div></div>
          </div> : <p className="mt-3 text-sm text-[#8a8472]">{t("usluga.selectModel")}</p>}
          <dl className="mt-4 space-y-3 text-sm">
            <div className="flex justify-between gap-4"><dt className="text-[#8a8472]">{t("field.quantity")}</dt><dd className="font-semibold tabular-nums">{totalQuantity.toLocaleString()}</dd></div>
            <div className="flex justify-between gap-4"><dt className="text-[#8a8472]">{t("usluga.planLines")}</dt><dd className="tabular-nums">{activeLines.length}</dd></div>
            <div className="flex justify-between gap-4"><dt className="text-[#8a8472]">{t("field.deadline")}</dt><dd>{form.deadline || "—"}</dd></div>
            <div className="flex justify-between gap-4"><dt className="text-[#8a8472]">{t("usluga.routeLabel")}</dt><dd>ECT → ECO → ECP</dd></div>
          </dl>
          {successOrder && <div className="mt-4 rounded-md border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">{t("usluga.created", { order: successOrder.order_no })}</div>}
          {formError && <div className="mt-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">{formError}</div>}
          <button className="btn btn-primary mt-4 w-full justify-center" type="button" disabled={busy || !selectedModel || activeLines.length === 0} onClick={() => void createOrder()}>{busy ? t("common.saving") : t("usluga.createPlan")}</button>
        </aside>
      </div>}

      <section>
        <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div><h2 className="text-lg font-semibold text-[#242117]">{t("usluga.orderHistory")}</h2><p className="mt-1 text-sm text-[#8a8472]">{t("usluga.orderHistoryHint")}</p></div>
          <div className="grid gap-2 sm:grid-cols-[240px_180px]">
            <input className="input" value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t("usluga.searchOrders")} />
            <select className="input" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="">{t("common.all")}</option>{["planning", "cutting", "sewing", "packaging", "ready_for_handover", "handed_over"].map((status) => <option key={status} value={status}>{t(`usluga.status.${status}`)}</option>)}</select>
          </div>
        </div>
        <div className="card overflow-hidden">
          {error && <div className="border-b border-[#ecebe3] p-4 text-sm text-red-700">{t("usluga.loadFailed")}</div>}
          <div className="overflow-x-auto"><table className="table min-w-[1120px]">
            <thead><tr><th>{t("usluga.order")}</th><th>{t("usluga.customer")}</th><th>{t("usluga.model")}</th><th>{t("field.quantity")}</th><th>{t("usluga.materialUsed")}</th><th>{t("usluga.route")}</th><th>{t("field.deadline")}</th><th>{t("field.status")}</th><th>{t("field.actions")}</th></tr></thead>
            <tbody>
              {isLoading && <tr><td colSpan={9} className="p-6 text-center text-[#8a8472]">{t("common.loading")}</td></tr>}
              {!isLoading && filteredOrders.length === 0 && <tr><td colSpan={9} className="p-8 text-center text-[#8a8472]">{t("usluga.empty")}</td></tr>}
              {filteredOrders.map((order) => <tr key={order.id}>
                <td><Link href={`/usluga/orders/${order.id}`} className="font-medium text-[#242117] hover:underline">{order.order_no}</Link><div className="mt-0.5 text-xs text-[#8a8472]">{order.customer_reference || "—"}</div></td>
                <td>{order.customer_name}</td>
                <td>{order.model ? <Link className="hover:underline" href={`/usluga/models/${order.model.id}`}>{order.model.code} · {order.model.name}</Link> : `#${order.model_id}`}</td>
                <td className="tabular-nums">{order.planned_quantity}</td>
                <td><div className="tabular-nums">{order.material_usage_kg ?? "—"} kg</div><div className="mt-0.5 max-w-48 truncate text-xs text-[#8a8472]">{order.material_description || "—"}</div></td>
                <td><div className="flex items-center gap-2">{order.work_orders.map((workOrder) => <Link key={workOrder.id} href={workOrderLink(workOrder)} className="inline-flex items-center gap-1 text-xs font-medium text-[#4f493a] underline decoration-[#c8c1ae] underline-offset-2" title={`${workOrder.operation}: ${workOrder.status}`}>{workOrder.operation === "cutting" ? <Scissors className="h-3.5 w-3.5" /> : workOrder.operation === "sewing" ? <Shirt className="h-3.5 w-3.5" /> : <PackageCheck className="h-3.5 w-3.5" />}{workOrder.passed_quantity}/{workOrder.planned_quantity}</Link>)}</div></td>
                <td>{formatDate(order.deadline)}</td><td>{t(`usluga.status.${order.status}`)}</td>
                <td><div className="flex items-center gap-3">{canHandover && order.ready_for_handover ? <button className="btn btn-primary" onClick={() => { setFormError(""); setHandoverForm({ recipient: order.customer_name, notes: "" }); setHandoverOrder(order); }}><ClipboardCheck className="h-4 w-4" />{t("usluga.handOver")}</button> : order.handed_over_at ? <span className="text-sm text-emerald-700">{formatDate(order.handed_over_at)}</span> : <Link className="text-sm font-medium hover:underline" href={`/usluga/orders/${order.id}`}>{t("common.view")}</Link>}{canManage && !order.handed_over_at && <Link className="inline-flex items-center gap-1 text-sm font-medium hover:underline" href={`/usluga/orders/${order.id}/edit`}><Pencil className="h-3.5 w-3.5" />{t("btn.edit")}</Link>}</div></td>
              </tr>)}
            </tbody>
          </table></div>
        </div>
      </section>

      <Modal open={Boolean(handoverOrder)} onClose={() => setHandoverOrder(null)} title={t("usluga.handOver")}>
        <div className="mb-4 text-sm text-[#56503f]">{t("usluga.handoverHint", { order: handoverOrder?.order_no || "" })}</div>
        <div className="space-y-3">
          <label><span className="label">{t("usluga.recipient")}</span><input className="input" value={handoverForm.recipient} onChange={(event) => setHandoverForm({ ...handoverForm, recipient: event.target.value })} /></label>
          <label><span className="label">{t("field.notes")}</span><textarea className="input min-h-20" value={handoverForm.notes} onChange={(event) => setHandoverForm({ ...handoverForm, notes: event.target.value })} /></label>
        </div>
        {formError && <div className="mt-3 text-sm text-red-700">{formError}</div>}
        <div className="mt-4 flex justify-end gap-2"><button className="btn" onClick={() => setHandoverOrder(null)}>{t("btn.cancel")}</button><button className="btn btn-primary" onClick={() => void handOver()} disabled={busy}>{busy ? t("common.saving") : t("usluga.confirmHandover")}</button></div>
      </Modal>
    </div>
  );
}
