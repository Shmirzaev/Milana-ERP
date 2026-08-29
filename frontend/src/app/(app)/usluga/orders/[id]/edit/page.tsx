"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";
import { ArrowLeft, Plus, Save, Trash2 } from "lucide-react";

import ModelAsyncSelect from "@/components/ModelAsyncSelect";
import PageHeader from "@/components/PageHeader";
import { api, fetcher } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { GARMENT_SIZE_OPTIONS } from "@/lib/garmentSizes";
import { useT } from "@/lib/i18n";

type PlanLine = { color: string; size: string; quantity: string };

type Order = {
  id: number;
  order_no: string;
  customer_name: string;
  customer_reference: string | null;
  model_id: number;
  planned_quantity: number;
  deadline: string | null;
  material_description: string | null;
  material_usage_kg: number | null;
  material_notes: string | null;
  handed_over_at: string | null;
  items: Array<{ id: number; color: string; size: string; planned_quantity: number }>;
};

type UslugaModel = {
  id: number;
  code: string;
  name: string;
  details_json?: { general?: { variant_color?: string | null } | null } | null;
  sizes: Array<{ id: number; size: string }>;
  colors: Array<{ id: number; color_name: string }>;
};

function orderedSizes(values: string[]) {
  const order = new Map(GARMENT_SIZE_OPTIONS.map((size, index) => [size, index]));
  return Array.from(new Set(values.filter(Boolean))).sort((left, right) => {
    const leftIndex = order.get(left) ?? Number.MAX_SAFE_INTEGER;
    const rightIndex = order.get(right) ?? Number.MAX_SAFE_INTEGER;
    return leftIndex - rightIndex || left.localeCompare(right, undefined, { numeric: true });
  });
}

function dateInputValue(value: string | null) {
  if (!value) return "";
  const parts = new Intl.DateTimeFormat("en", {
    timeZone: "Asia/Tashkent",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date(value));
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((row) => row.type === type)?.value || "";
  return `${part("year")}-${part("month")}-${part("day")}`;
}

export default function EditUslugaOrderPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { t } = useT();
  const { me } = useMe();
  const canManage = can(me, "usluga.manage", "*");
  const { data: order, error, isLoading } = useSWR<Order>(id ? `/api/usluga/orders/${id}` : null, fetcher);
  const initializedOrderId = useRef(0);

  const [modelId, setModelId] = useState(0);
  const { data: selectedModel } = useSWR<UslugaModel>(modelId ? `/api/usluga/models/${modelId}` : null, fetcher);
  const [form, setForm] = useState({
    customer_name: "",
    customer_reference: "",
    deadline: "",
    material_description: "",
    material_usage_kg: "",
    material_notes: "",
  });
  const [lines, setLines] = useState<PlanLine[]>([]);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState("");

  const modelSizes = useMemo(
    () => orderedSizes([...(selectedModel?.sizes || []).map((row) => row.size), ...lines.map((row) => row.size)]),
    [lines, selectedModel?.sizes],
  );
  const modelColor = String(
    selectedModel?.details_json?.general?.variant_color || selectedModel?.colors?.[0]?.color_name || "white",
  );
  const activeLines = useMemo(
    () => lines.filter((line) => line.color.trim() && line.size.trim() && Number(line.quantity || 0) > 0),
    [lines],
  );
  const totalQuantity = useMemo(
    () => activeLines.reduce((sum, line) => sum + Math.floor(Number(line.quantity)), 0),
    [activeLines],
  );

  useEffect(() => {
    if (!order || initializedOrderId.current === order.id) return;
    initializedOrderId.current = order.id;
    setModelId(order.model_id);
    setForm({
      customer_name: order.customer_name || "",
      customer_reference: order.customer_reference || "",
      deadline: dateInputValue(order.deadline),
      material_description: order.material_description || "",
      material_usage_kg: order.material_usage_kg == null ? "" : String(order.material_usage_kg),
      material_notes: order.material_notes || "",
    });
    setLines(order.items.map((row) => ({
      color: row.color,
      size: row.size,
      quantity: String(row.planned_quantity),
    })));
  }, [order]);

  useEffect(() => {
    if (!selectedModel || !order || modelId === order.model_id || lines.length) return;
    const sizes = orderedSizes(selectedModel.sizes.map((row) => row.size));
    setLines(sizes.map((size) => ({ color: modelColor, size, quantity: "" })));
  }, [lines.length, modelColor, modelId, order, selectedModel]);

  function selectModel(nextModelId: number) {
    if (nextModelId === modelId) return;
    setModelId(nextModelId);
    setLines([]);
    setFormError("");
  }

  function updateLine(index: number, patch: Partial<PlanLine>) {
    setLines((current) => current.map((line, rowIndex) => rowIndex === index ? { ...line, ...patch } : line));
  }

  function addLine() {
    setLines((current) => [...current, { color: modelColor, size: modelSizes[0] || "", quantity: "" }]);
  }

  async function saveOrder() {
    if (!order || !selectedModel) return;
    if (!form.customer_name.trim()) return setFormError(t("usluga.customerRequired"));
    if (!activeLines.length) return setFormError(t("usluga.sizeRequired"));
    setBusy(true);
    setFormError("");
    try {
      await api.patch(`/api/usluga/orders/${order.id}`, {
        customer_name: form.customer_name.trim(),
        customer_reference: form.customer_reference.trim() || null,
        model_id: selectedModel.id,
        lines: activeLines.map((line) => ({
          color: line.color.trim(),
          size: line.size.trim(),
          quantity: Math.floor(Number(line.quantity)),
        })),
        deadline: form.deadline ? new Date(`${form.deadline}T23:59:59+05:00`).toISOString() : null,
        material_description: form.material_description.trim() || null,
        material_usage_kg: form.material_usage_kg === "" ? null : Number(form.material_usage_kg),
        material_notes: form.material_notes.trim() || null,
      });
      router.push(`/usluga/orders/${order.id}`);
      router.refresh();
    } catch (submitError: unknown) {
      setFormError(String((submitError as Error)?.message || submitError));
    } finally {
      setBusy(false);
    }
  }

  if (isLoading || !me) return <div className="p-6 text-sm text-[#8a8472]">{t("common.loading")}</div>;
  if (error || !order) return <div className="p-6 text-sm text-red-700">{t("usluga.loadFailed")}</div>;
  if (!canManage) return <div className="p-6 text-sm text-red-700">{t("usluga.accessDenied")}</div>;
  if (order.handed_over_at) return <div className="p-6 text-sm text-red-700">{t("usluga.handedOverReadOnly")}</div>;

  return <div>
    <PageHeader
      title={t("usluga.editOrder")}
      subtitle={`${order.order_no} · ${t("usluga.editOrderHint")}`}
      actions={<Link href={`/usluga/orders/${order.id}`} className="btn"><ArrowLeft className="h-4 w-4" />{t("btn.cancel")}</Link>}
    />

    <div className="mb-5 border-y border-[#dedbd0] bg-[#fbfaf6] px-4 py-3 text-sm text-[#56503f]">
      {t("usluga.inventoryBoundary")}
    </div>

    <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
      <div className="space-y-4">
        <section className="card p-4 sm:p-5">
          <h2 className="mb-4 border-b border-[#ecebe3] pb-3 text-base font-semibold text-[#242117]">{t("usluga.orderDetails")}</h2>
          <div className="grid gap-4 md:grid-cols-2">
            <label className="md:col-span-2">
              <span className="label">{t("usluga.model")}</span>
              <ModelAsyncSelect inputId="usluga-edit-model" value={modelId || null} onChange={selectModel} status="approved" endpoint="/api/usluga/model-options" placeholder={t("usluga.selectModel")} noResultsText={t("page.models.empty")} loadingText={t("common.loading")} loadMoreText={t("common.loadMore")} required />
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
          <div className="flex items-center justify-between gap-3 border-b border-[#ecebe3] p-4">
            <div><h2 className="text-base font-semibold text-[#242117]">{t("usluga.plannedLines")}</h2><p className="mt-1 text-sm text-[#8a8472]">{t("usluga.editLinesHint")}</p></div>
            <button type="button" className="btn" onClick={addLine} disabled={!selectedModel}><Plus className="h-4 w-4" />{t("usluga.addLine")}</button>
          </div>
          <div className="overflow-x-auto"><table className="table min-w-[640px]">
            <thead><tr><th>{t("common.color")}</th><th>{t("common.size")}</th><th>{t("field.quantity")}</th><th className="w-14">{t("field.actions")}</th></tr></thead>
            <tbody>
              {lines.map((line, index) => <tr key={`${index}-${line.size}`}>
                <td><input className="input min-w-36" value={line.color} onChange={(event) => updateLine(index, { color: event.target.value })} /></td>
                <td><select className="input min-w-24" value={line.size} onChange={(event) => updateLine(index, { size: event.target.value })}>{modelSizes.map((size) => <option key={size} value={size}>{size}</option>)}</select></td>
                <td><input className="input min-w-28" type="number" min="1" value={line.quantity} onChange={(event) => updateLine(index, { quantity: event.target.value })} /></td>
                <td><button className="icon-btn text-red-700" type="button" title={t("common.delete")} onClick={() => setLines((current) => current.filter((_, rowIndex) => rowIndex !== index))}><Trash2 className="h-4 w-4" /></button></td>
              </tr>)}
              {!lines.length && <tr><td colSpan={4} className="p-6 text-center text-sm text-[#8a8472]">{t("usluga.noSizes")}</td></tr>}
            </tbody>
          </table></div>
        </section>
      </div>

      <aside className="card p-4">
        <h2 className="text-base font-semibold text-[#242117]">{t("usluga.planSummary")}</h2>
        <dl className="mt-4 space-y-3 text-sm">
          <div className="flex justify-between gap-4"><dt className="text-[#8a8472]">{t("usluga.order")}</dt><dd>{order.order_no}</dd></div>
          <div className="flex justify-between gap-4"><dt className="text-[#8a8472]">{t("field.quantity")}</dt><dd className="font-semibold tabular-nums">{totalQuantity.toLocaleString()}</dd></div>
          <div className="flex justify-between gap-4"><dt className="text-[#8a8472]">{t("usluga.planLines")}</dt><dd className="tabular-nums">{activeLines.length}</dd></div>
          <div className="flex justify-between gap-4"><dt className="text-[#8a8472]">{t("usluga.routeLabel")}</dt><dd>ECT → ECO → ECP</dd></div>
        </dl>
        <p className="mt-4 border-t border-[#ecebe3] pt-4 text-sm text-[#56503f]">{t("usluga.editProductionBoundary")}</p>
        {formError && <div className="mt-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">{formError}</div>}
        <div className="mt-4 grid gap-2">
          <button className="btn btn-primary w-full justify-center" type="button" disabled={busy || !selectedModel || !activeLines.length} onClick={() => void saveOrder()}><Save className="h-4 w-4" />{busy ? t("common.saving") : t("common.save")}</button>
          <Link href={`/usluga/orders/${order.id}`} className="btn w-full justify-center">{t("btn.cancel")}</Link>
        </div>
      </aside>
    </div>
  </div>;
}
