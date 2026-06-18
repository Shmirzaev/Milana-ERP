"use client";
import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { Plus, Trash2 } from "lucide-react";
import { fetcher, api } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";
import { statusLabel } from "@/components/StagePipeline";
import {
  createPaidOperation,
  paidOperationsFromDetails,
  serializePaidOperations,
  withPaidOperations,
  type PaidOperation,
  type SectionCode,
} from "@/lib/modelPaidOperations";

type ModelDetails = {
  general?: {
    full_name?: string;
    brand?: string;
    brand_id?: number;
    product_type?: string;
    season?: string;
    designer?: string;
    designer_employee_id?: number;
    constructor?: string;
    constructor_employee_id?: number;
    note?: string;
  };
  sewing?: {
    complexity_level?: string;
    one_person_norm?: number;
    note?: string;
  };
  translation?: {
    uz?: string;
    ru?: string;
    en?: string;
  };
  costing?: {
    labor_pct?: number;
    electricity_pct?: number;
    other_pct?: number;
    target_margin_pct?: number;
  };
  paid_operations?: PaidOperation[];
  paidOperations?: PaidOperation[];
  features?: Record<string, boolean>;
};

type ImageUploadType = "model" | "material";

const IMAGE_UPLOAD_TYPES: ImageUploadType[] = ["model", "material"];

const TAB_KEYS = [
  "page.modelDetail.tab.general",
  "page.modelDetail.tab.materials",
  "page.modelDetail.tab.variants",
  "page.modelDetail.tab.pattern",
  "page.modelDetail.tab.other",
  "page.modelDetail.tab.miniPost",
  "page.modelDetail.tab.sizeChart",
  "page.modelDetail.tab.sewingGuide",
  "page.modelDetail.tab.paidOperations",
  "page.modelDetail.tab.translation",
  "page.modelDetail.tab.costing",
] as const;

function n(v: unknown): number {
  const x = Number(v ?? 0);
  return Number.isFinite(x) ? x : 0;
}

function buildMeasurementJson(fields: { chest: string; waist: string; hip: string; length: string; sleeve: string }) {
  const out: Record<string, number> = {};
  if (fields.chest.trim()) out.chest = n(fields.chest);
  if (fields.waist.trim()) out.waist = n(fields.waist);
  if (fields.hip.trim()) out.hip = n(fields.hip);
  if (fields.length.trim()) out.length = n(fields.length);
  if (fields.sleeve.trim()) out.sleeve = n(fields.sleeve);
  return out;
}

function withoutModelQuantities(rows: PaidOperation[]): PaidOperation[] {
  return rows.map((row) => ({ ...row, quantityMode: "batch", customQuantity: 0 }));
}

export default function ModelDetail() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const { t, lang } = useT();
  const isNumericId = /^\d+$/.test(String(id || ""));
  const { data: m, error: modelError, isLoading: modelLoading, mutate } = useSWR<any>(isNumericId ? `/api/models/${id}` : null, fetcher);
  const { data: variantsData, mutate: mutateVariants } = useSWR<any[]>(isNumericId ? `/api/models/${id}/variants` : null, fetcher);
  const { data: items } = useSWR<any[]>("/api/inventory/items", fetcher);
  const { data: brands } = useSWR<any[]>("/api/brands", fetcher);
  const { data: seasons } = useSWR<string[]>("/api/collections/seasons", fetcher);
  const { data: employees } = useSWR<any[]>("/api/employees", fetcher);
  const { data: depts } = useSWR<any[]>("/api/departments", fetcher);
  const { data: appSettings } = useSWR<any>("/api/settings", fetcher);
  const tabs = TAB_KEYS.map((k) => t(k));

  const [tab, setTab] = useState(1);
  const [msg, setMsg] = useState("");

  const [modelForm, setModelForm] = useState({
    code: "",
    name: "",
    category: "",
    description: "",
    brand_id: 0,
    collection_id: 0,
    product_type: "",
    season: "",
    constructor_employee_id: 0,
    designer_employee_id: 0,
    status: "draft",
    sam_minutes: 0,
  });
  const [details, setDetails] = useState<ModelDetails>({});

  const [bomRow, setBomRow] = useState({ item_id: 0, size: "", color: "", quantity_per_piece: 1, unit: "kg", waste_percent: 5 });
  const [color, setColor] = useState({ color_name: "", color_code: "" });
  const [size, setSize] = useState({ size: "", measurement_json: "" });
  const [measurementFields, setMeasurementFields] = useState({ chest: "", waist: "", hip: "", length: "", sleeve: "" });
  const [imageForms, setImageForms] = useState<Record<ImageUploadType, { file_url: string }>>({
    model: { file_url: "" },
    material: { file_url: "" },
  });
  const [imageFiles, setImageFiles] = useState<Record<ImageUploadType, File | null>>({
    model: null,
    material: null,
  });
  const [uploadingImageType, setUploadingImageType] = useState<ImageUploadType | null>(null);

  useEffect(() => {
    if (!m) return;
    setModelForm({
      code: m.code ?? "",
      name: m.name ?? "",
      category: m.category ?? "",
      description: m.description ?? "",
      brand_id: Number(m.brand_id || m.details_json?.general?.brand_id || 0),
      collection_id: Number(m.collection_id || 0),
      product_type: m.product_type ?? m.details_json?.general?.product_type ?? "",
      season: m.season ?? m.details_json?.general?.season ?? "",
      constructor_employee_id: Number(m.constructor_employee_id || m.details_json?.general?.constructor_employee_id || 0),
      designer_employee_id: Number(m.designer_employee_id || m.details_json?.general?.designer_employee_id || 0),
      status: m.status ?? "draft",
      sam_minutes: n(m.sam_minutes),
    });
    const nextDetails: ModelDetails = { ...(m.details_json || {}) };
    if (!nextDetails.translation?.ru) {
      nextDetails.translation = { ...(nextDetails.translation || {}), ru: m.name ?? "" };
    }
    setDetails(nextDetails);
  }, [m]);

  const measurementJson = useMemo(() => buildMeasurementJson(measurementFields), [measurementFields]);

  useEffect(() => {
    setSize((prev) => ({ ...prev, measurement_json: JSON.stringify(measurementJson) }));
  }, [measurementJson]);

  const itemMap = useMemo(() => {
    const map = new Map<number, any>();
    for (const i of items || []) map.set(i.id, i);
    return map;
  }, [items]);

  const bomWithItem = useMemo(() => {
    return (m?.bom || []).map((b: any) => {
      const item = itemMap.get(b.item_id);
      const unitCost = n(item?.default_cost);
      const requiredPerPiece = n(b.quantity_per_piece) * (1 + n(b.waste_percent) / 100);
      const costPerPiece = requiredPerPiece * unitCost;
      return { ...b, item, unitCost, requiredPerPiece, costPerPiece };
    });
  }, [m?.bom, itemMap]);

  const materialRows = bomWithItem.filter((r: any) => ["fabric", "semi_finished", ""].includes(String(r.item?.category || "").toLowerCase()));
  const accessoryRows = bomWithItem.filter((r: any) => ["accessory", "packaging"].includes(String(r.item?.category || "").toLowerCase()));
  const baseCostPerPiece = bomWithItem.reduce((s: number, r: any) => s + n(r.costPerPiece), 0);

  const laborPct = n(details.costing?.labor_pct ?? 12);
  const electricityPct = n(details.costing?.electricity_pct ?? 4);
  const otherPct = n(details.costing?.other_pct ?? 3);
  const marginPct = n(details.costing?.target_margin_pct ?? 20);
  const laborCost = baseCostPerPiece * laborPct / 100;
  const electricityCost = baseCostPerPiece * electricityPct / 100;
  const otherCost = baseCostPerPiece * otherPct / 100;
  const netCost = baseCostPerPiece + laborCost + electricityCost + otherCost;
  const targetPrice = netCost * (1 + marginPct / 100);

  const variants = useMemo(() => (Array.isArray(variantsData) ? variantsData : []), [variantsData]);
  const modelingDepartmentIds = useMemo(() => {
    return new Set(
      (depts || [])
        .filter((d: any) => /model|plm|mod/i.test(`${d.name || ""} ${d.code || ""}`))
        .map((d: any) => Number(d.id)),
    );
  }, [depts]);
  const modelingEmployees = useMemo(() => {
    const rows = employees || [];
    if (!modelingDepartmentIds.size) return rows;
    return rows.filter((e: any) => modelingDepartmentIds.has(Number(e.department_id)));
  }, [employees, modelingDepartmentIds]);
  const modelTypeOptions: string[] = appSettings?.preferences?.model_types || [];
  const sizeRows = m?.sizes || [];
  const colorRows = m?.colors || [];
  const primaryImage = (m?.images || []).find((img: any) => img.image_type === "model") || (m?.images || []).find((img: any) => img.is_primary) || (m?.images || [])[0];
  const translatedName = details.translation?.[lang] || (lang === "ru" ? details.translation?.ru : "") || m?.name || "";
  const paidOperations = useMemo(() => withoutModelQuantities(paidOperationsFromDetails(details)), [details]);

  if (!isNumericId) {
    return (
      <div className="card p-4 text-sm text-red-700">
        {t("page.modelDetail.invalidId")}
      </div>
    );
  }
  if (modelError) {
    return (
      <div className="card p-4 text-sm text-red-700">
        <div>{t("page.modelDetail.loadError")}</div>
        <button className="btn mt-3" onClick={() => mutate()}>{t("common.retry")}</button>
      </div>
    );
  }
  if (modelLoading || !m) return <div className="card p-4 text-sm text-slate-500">{t("common.loading")}</div>;

  function updatePaidOperation(id: string, patch: Partial<PaidOperation>) {
    setDetails((current) => {
      const rows = withoutModelQuantities(paidOperationsFromDetails(current)).map((operation) => (
        operation.id === id ? { ...operation, ...patch } : operation
      ));
      return withPaidOperations(current, rows);
    });
  }

  function addPaidOperation() {
    setDetails((current) => {
      const rows = [...withoutModelQuantities(paidOperationsFromDetails(current)), createPaidOperation("model-op")];
      return withPaidOperations(current, rows);
    });
  }

  function removePaidOperation(id: string) {
    setDetails((current) => {
      const rows = withoutModelQuantities(paidOperationsFromDetails(current));
      if (rows.length <= 1) return current;
      return withPaidOperations(current, rows.filter((operation) => operation.id !== id));
    });
  }

  async function saveModel() {
    const selectedBrand = (brands || []).find((b) => Number(b.id) === Number(modelForm.brand_id));
    const constructor = (employees || []).find((e) => Number(e.id) === Number(modelForm.constructor_employee_id));
    const designer = (employees || []).find((e) => Number(e.id) === Number(modelForm.designer_employee_id));
    const normalizedDetails: ModelDetails = {
      ...details,
      general: {
        ...details.general,
        brand: selectedBrand?.name || "",
        brand_id: modelForm.brand_id || undefined,
        product_type: modelForm.product_type || "",
        season: modelForm.season || "",
        constructor: constructor?.full_name || "",
        constructor_employee_id: modelForm.constructor_employee_id || undefined,
        designer: designer?.full_name || "",
        designer_employee_id: modelForm.designer_employee_id || undefined,
      },
      translation: {
        ...(details.translation || {}),
        ru: details.translation?.ru || modelForm.name,
      },
      paid_operations: serializePaidOperations(withoutModelQuantities(paidOperations)),
    };
    await api.patch(`/api/models/${id}`, {
      ...modelForm,
      category: modelForm.category || null,
      description: modelForm.description || null,
      brand_id: modelForm.brand_id || null,
      collection_id: modelForm.collection_id || null,
      product_type: modelForm.product_type || null,
      season: modelForm.season || null,
      constructor_employee_id: modelForm.constructor_employee_id || null,
      designer_employee_id: modelForm.designer_employee_id || null,
      details_json: normalizedDetails,
    });
    setDetails(normalizedDetails);
    setMsg(t("msg.saved"));
    mutate();
    mutateVariants();
  }

  async function addBom(e?: { preventDefault?: () => void }, expectedCategory?: "material" | "accessory") {
    e?.preventDefault?.();
    const item = itemMap.get(bomRow.item_id);
    const category = String(item?.category || "").toLowerCase();
    if (!bomRow.item_id) {
      alert(t("page.modelDetail.alert.pickItemFirst"));
      return;
    }
    const target: "material" | "accessory" = expectedCategory || "material";
    if (target === "material" && !["fabric", "semi_finished"].includes(category)) {
      alert(t("page.modelDetail.alert.materialItemType"));
      return;
    }
    if (target === "accessory" && !["accessory", "packaging"].includes(category)) {
      alert(t("page.modelDetail.alert.accessoryItemType"));
      return;
    }
    await api.post(`/api/models/${id}/bom`, {
      item_id: bomRow.item_id,
      size: bomRow.size || null,
      color: bomRow.color || null,
      quantity_per_piece: n(bomRow.quantity_per_piece),
      unit: bomRow.unit,
      waste_percent: n(bomRow.waste_percent),
    });
    setBomRow({ item_id: 0, size: "", color: "", quantity_per_piece: 1, unit: "kg", waste_percent: 5 });
    setMsg(target === "material" ? t("page.modelDetail.msg.addedToFabrics") : t("page.modelDetail.msg.addedToAccessories"));
    mutate();
  }

  async function addColor(e: React.FormEvent) {
    e.preventDefault();
    await api.post(`/api/models/${id}/colors`, color);
    setColor({ color_name: "", color_code: "" });
    mutate();
    mutateVariants();
  }

  async function addSize(e: React.FormEvent) {
    e.preventDefault();
    await api.post(`/api/models/${id}/sizes`, {
      size: size.size,
      measurement_json: Object.keys(measurementJson).length ? measurementJson : null,
    });
    setSize({ size: "", measurement_json: "" });
    setMeasurementFields({ chest: "", waist: "", hip: "", length: "", sleeve: "" });
    mutate();
    mutateVariants();
  }

  async function addImage(e: React.FormEvent, imageType: ImageUploadType) {
    e.preventDefault();
    const imageFile = imageFiles[imageType];
    const imageForm = imageForms[imageType];
    if (imageFile) {
      setUploadingImageType(imageType);
      try {
        const form = new FormData();
        form.append("file", imageFile);
        form.append("image_type", imageType);
        await api.postForm(`/api/models/${id}/images/upload`, form);
      } finally {
        setUploadingImageType(null);
      }
      setImageFiles((prev) => ({ ...prev, [imageType]: null }));
      setImageForms((prev) => ({ ...prev, [imageType]: { file_url: "" } }));
      mutate();
      return;
    }
    if (!imageForm.file_url.trim()) return;
    await api.post(`/api/models/${id}/images`, {
      file_url: imageForm.file_url,
      image_type: imageType,
      is_primary: imageType === "model",
    });
    setImageForms((prev) => ({ ...prev, [imageType]: { file_url: "" } }));
    mutate();
  }

  async function deleteImage(imageId: number) {
    if (!confirm(t("page.modelDetail.deletePatternConfirm"))) return;
    await api.del(`/api/models/${id}/images/${imageId}`);
    mutate();
  }

  async function deleteSize(sizeId: number) {
    if (!confirm(t("page.modelDetail.deleteSizeConfirm"))) return;
    await api.del(`/api/models/${id}/sizes/${sizeId}`);
    mutate();
    mutateVariants();
  }

  function tabButton(index: number, label: string, badgeValue: number) {
    const active = tab === index;
    return (
      <button
        type="button"
        key={index}
        onClick={() => setTab(index)}
        className={`px-3 py-1.5 text-xs border-b-2 ${active ? "border-[#14110b] text-[#14110b] font-semibold" : "border-transparent text-slate-500"}`}
      >
        {label} <span className="badge">{badgeValue}</span>
      </button>
    );
  }

  function imageTypeLabel(value?: string | null) {
    const key = `page.workOrder.imageType.${value || "pattern"}`;
    return t(key);
  }

  function uploadOptionTitle(type: ImageUploadType) {
    return type === "model" ? t("page.modelDetail.attachModelPicture") : t("page.modelDetail.attachMaterialPattern");
  }

  return (
    <div>
      <PageHeader
        title={t("page.modelDetail.viewTitle", { code: m.code })}
        subtitle={t("page.modelDetail.subtitle", { name: translatedName, status: statusLabel(m.status, t) })}
      />
      <div className="card p-4 space-y-4">
        <div className="flex flex-wrap gap-1 border-b border-[#ecebe3] pb-2">
          {tabs.map((label, i) => {
            const counts = [0, bomWithItem.length, variants.length, (m.images || []).length, 0, 0, sizeRows.length, 0, paidOperations.length, 0, 0];
            return tabButton(i + 1, label, counts[i] || 0);
          })}
        </div>

        {tab === 1 && (
          <div className="space-y-3">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div><label className="label">{t("common.code")}</label><input className="input" value={modelForm.code} onChange={(e) => setModelForm({ ...modelForm, code: e.target.value })} /></div>
              <div><label className="label">{t("common.name")}</label><input className="input" value={modelForm.name} onChange={(e) => setModelForm({ ...modelForm, name: e.target.value })} /></div>
              <div><label className="label">{t("field.category")}</label><input className="input" value={modelForm.category} onChange={(e) => setModelForm({ ...modelForm, category: e.target.value })} /></div>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
              <div>
                <label className="label">{t("field.brand")}</label>
                <select className="input" value={modelForm.brand_id} onChange={(e) => setModelForm({ ...modelForm, brand_id: n(e.target.value) })}>
                  <option value={0}>{t("ph.brand")}</option>
                  {(brands || []).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
                </select>
              </div>
              <div>
                <label className="label">{t("field.type")}</label>
                {modelTypeOptions.length ? (
                  <select className="input" value={modelForm.product_type} onChange={(e) => setModelForm({ ...modelForm, product_type: e.target.value })}>
                    <option value="">-</option>
                    {modelTypeOptions.map((type) => <option key={type} value={type}>{type}</option>)}
                  </select>
                ) : (
                  <input className="input" value={modelForm.product_type} onChange={(e) => setModelForm({ ...modelForm, product_type: e.target.value })} />
                )}
              </div>
              <div>
                <label className="label">{t("field.season")}</label>
                <select className="input" value={modelForm.season} onChange={(e) => setModelForm({ ...modelForm, season: e.target.value })}>
                  <option value="">-</option>
                  {(seasons || []).map((season) => <option key={season} value={season}>{season}</option>)}
                </select>
              </div>
              <div><label className="label">{t("field.samMinutes")}</label><input className="input" type="number" step="0.1" value={modelForm.sam_minutes} onChange={(e) => setModelForm({ ...modelForm, sam_minutes: n(e.target.value) })} /></div>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <label className="label">{t("page.modelDetail.constructor")}</label>
                <select className="input" value={modelForm.constructor_employee_id} onChange={(e) => setModelForm({ ...modelForm, constructor_employee_id: n(e.target.value) })}>
                  <option value={0}>-</option>
                  {modelingEmployees.map((e) => <option key={e.id} value={e.id}>{e.full_name}</option>)}
                </select>
              </div>
              <div>
                <label className="label">{t("page.modelDetail.designer")}</label>
                <select className="input" value={modelForm.designer_employee_id} onChange={(e) => setModelForm({ ...modelForm, designer_employee_id: n(e.target.value) })}>
                  <option value={0}>-</option>
                  {modelingEmployees.map((e) => <option key={e.id} value={e.id}>{e.full_name}</option>)}
                </select>
              </div>
            </div>
            <div><label className="label">{t("field.description")}</label><textarea className="input min-h-24" value={modelForm.description} onChange={(e) => setModelForm({ ...modelForm, description: e.target.value })} /></div>
          </div>
        )}

        {tab === 2 && (
          <div className="space-y-5">
            <div>
              <div className="flex items-center justify-between mb-2">
                <h3 className="font-semibold">{t("page.modelDetail.fabrics")}</h3>
                <button className="btn btn-primary" type="button" onClick={() => addBom(undefined, "material")}>+ {t("page.modelDetail.addToFabrics")}</button>
              </div>
              <table className="table">
                <thead><tr><th>{t("common.code")}</th><th>{t("common.name")}</th><th>{t("page.modelDetail.sizeColor")}</th><th>{t("field.usage")}</th><th>{t("field.unitCost")}</th><th>{t("page.modelDetail.costPerPiece")}</th></tr></thead>
                <tbody>
                  {materialRows.map((r: any) => (
                    <tr key={r.id}>
                      <td>{r.item?.sku || r.item_id}</td>
                      <td>{r.item?.name || "-"}</td>
                      <td>{r.size || t("common.all")} / {r.color || t("common.all")}</td>
                      <td>{n(r.quantity_per_piece).toFixed(4)} {r.unit} (+{n(r.waste_percent).toFixed(1)}%)</td>
                      <td>${n(r.unitCost).toFixed(4)}</td>
                      <td>${n(r.costPerPiece).toFixed(4)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <form onSubmit={(e) => addBom(e, "material")} className="grid grid-cols-1 md:grid-cols-9 gap-2 mt-2">
                <select className="input" value={bomRow.item_id} onChange={(e) => setBomRow({ ...bomRow, item_id: n(e.target.value) })} required>
                  <option value={0}>{t("page.modelDetail.selectItem")}</option>
                  {(items || []).map((i) => <option key={i.id} value={i.id}>{i.sku} - {i.name} ({i.category})</option>)}
                </select>
                <input className="input" placeholder={t("page.modelDetail.colorOptional")} value={bomRow.color} onChange={(e) => setBomRow({ ...bomRow, color: e.target.value })} />
                <input className="input" placeholder={t("page.modelDetail.sizeOptional")} value={bomRow.size} onChange={(e) => setBomRow({ ...bomRow, size: e.target.value })} />
                <input className="input" type="number" step="0.0001" placeholder={t("page.modelDetail.qtyPerPieceShort")} value={bomRow.quantity_per_piece} onChange={(e) => setBomRow({ ...bomRow, quantity_per_piece: n(e.target.value) })} required />
                <input className="input" placeholder={t("field.unit")} value={bomRow.unit} onChange={(e) => setBomRow({ ...bomRow, unit: e.target.value })} required />
                <input className="input" type="number" step="0.1" placeholder={t("page.modelDetail.wastePctShort")} value={bomRow.waste_percent} onChange={(e) => setBomRow({ ...bomRow, waste_percent: n(e.target.value) })} />
                <button className="btn btn-primary" type="submit">{t("btn.add")}</button>
              </form>
            </div>
            <div>
              <div className="flex items-center justify-between mb-2">
                <h3 className="font-semibold">{t("page.modelDetail.accessories")}</h3>
                <button className="btn" type="button" onClick={() => addBom(undefined, "accessory")}>+ {t("page.modelDetail.addToAccessories")}</button>
              </div>
              <table className="table">
                <thead><tr><th>{t("common.code")}</th><th>{t("common.name")}</th><th>{t("page.modelDetail.sizeColor")}</th><th>{t("field.usage")}</th><th>{t("field.unitCost")}</th><th>{t("page.modelDetail.costPerPiece")}</th></tr></thead>
                <tbody>
                  {accessoryRows.map((r: any) => (
                    <tr key={r.id}>
                      <td>{r.item?.sku || r.item_id}</td>
                      <td>{r.item?.name || "-"}</td>
                      <td>{r.size || t("common.all")} / {r.color || t("common.all")}</td>
                      <td>{n(r.quantity_per_piece).toFixed(4)} {r.unit} (+{n(r.waste_percent).toFixed(1)}%)</td>
                      <td>${n(r.unitCost).toFixed(4)}</td>
                      <td>${n(r.costPerPiece).toFixed(4)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <form onSubmit={(e) => addBom(e, "accessory")} className="grid grid-cols-1 md:grid-cols-9 gap-2">
              <select className="input" value={bomRow.item_id} onChange={(e) => setBomRow({ ...bomRow, item_id: n(e.target.value) })} required>
                <option value={0}>{t("page.modelDetail.selectItem")}</option>
                {(items || []).map((i) => <option key={i.id} value={i.id}>{i.sku} - {i.name} ({i.category})</option>)}
              </select>
              <input className="input" placeholder={t("page.modelDetail.colorOptional")} value={bomRow.color} onChange={(e) => setBomRow({ ...bomRow, color: e.target.value })} />
              <input className="input" placeholder={t("page.modelDetail.sizeOptional")} value={bomRow.size} onChange={(e) => setBomRow({ ...bomRow, size: e.target.value })} />
              <input className="input" type="number" step="0.0001" placeholder={t("page.modelDetail.qtyPerPieceShort")} value={bomRow.quantity_per_piece} onChange={(e) => setBomRow({ ...bomRow, quantity_per_piece: n(e.target.value) })} required />
              <input className="input" placeholder={t("field.unit")} value={bomRow.unit} onChange={(e) => setBomRow({ ...bomRow, unit: e.target.value })} required />
              <input className="input" type="number" step="0.1" placeholder={t("page.modelDetail.wastePctShort")} value={bomRow.waste_percent} onChange={(e) => setBomRow({ ...bomRow, waste_percent: n(e.target.value) })} />
              <button className="btn btn-primary" type="submit">{t("btn.add")}</button>
            </form>
          </div>
        )}

        {tab === 3 && (
          <div className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <form onSubmit={addColor} className="card p-3 space-y-2">
                <div className="font-medium">{t("page.modelDetail.addColor")}</div>
                <div className="flex gap-2">
                  <input className="input" placeholder={t("page.modelDetail.colorName")} value={color.color_name} onChange={(e) => setColor({ ...color, color_name: e.target.value })} required />
                  <input className="input w-24" placeholder={t("page.modelDetail.colorCodeHex")} value={color.color_code} onChange={(e) => setColor({ ...color, color_code: e.target.value })} />
                  <button className="btn btn-primary">{t("btn.add")}</button>
                </div>
              </form>
              <form onSubmit={addSize} className="card p-3 space-y-2">
                <div className="font-medium">{t("page.modelDetail.addSize")}</div>
                <div className="flex gap-2">
                  <input className="input" placeholder={t("page.modelDetail.sizeListExample")} value={size.size} onChange={(e) => setSize({ ...size, size: e.target.value })} required />
                  <button className="btn btn-primary" type="submit">{t("btn.view")}</button>
                </div>
                <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
                  <input className="input" placeholder={t("page.modelDetail.measurement.chest")} value={measurementFields.chest} onChange={(e) => setMeasurementFields({ ...measurementFields, chest: e.target.value })} />
                  <input className="input" placeholder={t("page.modelDetail.measurement.waist")} value={measurementFields.waist} onChange={(e) => setMeasurementFields({ ...measurementFields, waist: e.target.value })} />
                  <input className="input" placeholder={t("page.modelDetail.measurement.hip")} value={measurementFields.hip} onChange={(e) => setMeasurementFields({ ...measurementFields, hip: e.target.value })} />
                  <input className="input" placeholder={t("page.modelDetail.measurement.length")} value={measurementFields.length} onChange={(e) => setMeasurementFields({ ...measurementFields, length: e.target.value })} />
                  <input className="input" placeholder={t("page.modelDetail.measurement.sleeve")} value={measurementFields.sleeve} onChange={(e) => setMeasurementFields({ ...measurementFields, sleeve: e.target.value })} />
                </div>
              </form>
            </div>
            <table className="table">
              <thead><tr><th>{t("page.modelDetail.variant")}</th><th>{t("field.color")}</th><th>{t("field.size")}</th><th>{t("page.modelDetail.estimatedNetCostPerPiece")}</th></tr></thead>
              <tbody>
                {variants.map((v, idx) => (
                  <tr key={`${v.color}-${v.size}-${idx}`}>
                    <td>{idx + 1}</td><td>{v.color}</td><td>{v.size}</td><td>${Number(v.estimated_net_cost_pc ?? netCost).toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <table className="table">
              <thead><tr><th>{t("field.size")}</th><th>{t("page.modelDetail.measurement.chest")}</th><th>{t("page.modelDetail.measurement.waist")}</th><th>{t("page.modelDetail.measurement.hip")}</th><th>{t("page.modelDetail.measurement.length")}</th><th>{t("page.modelDetail.measurement.sleeve")}</th><th>{t("field.actions")}</th></tr></thead>
              <tbody>
                {sizeRows.map((s: any) => {
                  const mm = s.measurement_json || {};
                  return (
                    <tr key={s.id}>
                      <td>{s.size}</td>
                      <td>{mm.chest ?? "-"}</td>
                      <td>{mm.waist ?? "-"}</td>
                      <td>{mm.hip ?? "-"}</td>
                      <td>{mm.length ?? "-"}</td>
                      <td>{mm.sleeve ?? "-"}</td>
                      <td><button className="text-red-600 hover:underline" onClick={() => deleteSize(s.id)}>{t("btn.delete")}</button></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {tab === 4 && (
          <div className="space-y-3">
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              {IMAGE_UPLOAD_TYPES.map((imageType) => {
                const imageFile = imageFiles[imageType];
                const imageForm = imageForms[imageType];
                const isUploading = uploadingImageType === imageType;
                return (
                  <form
                    key={imageType}
                    onSubmit={(e) => addImage(e, imageType)}
                    className="rounded-md border border-[#ecebe3] bg-[#fdfcf8] p-3"
                  >
                    <div className="mb-2 text-sm font-semibold text-[#14110b]">{uploadOptionTitle(imageType)}</div>
                    <div className="grid grid-cols-1 gap-2 md:grid-cols-[minmax(0,1fr)_minmax(180px,0.55fr)_auto]">
                      <input
                        className="input"
                        type="file"
                        accept="image/png,image/jpeg,image/webp,image/gif,.pdf,.dxf,.ai"
                        onChange={(e) => setImageFiles((prev) => ({ ...prev, [imageType]: e.target.files?.[0] || null }))}
                      />
                      <input
                        className="input"
                        placeholder={t("page.modelDetail.orImageUrl")}
                        value={imageForm.file_url}
                        onChange={(e) => setImageForms((prev) => ({ ...prev, [imageType]: { file_url: e.target.value } }))}
                      />
                      <button className="btn btn-primary" disabled={isUploading || (!imageFile && !imageForm.file_url.trim())}>
                        {isUploading ? t("common.uploading") : uploadOptionTitle(imageType)}
                      </button>
                    </div>
                  </form>
                );
              })}
            </div>
            <table className="table">
              <thead><tr><th>{t("field.preview")}</th><th>{t("page.workOrder.imageType")}</th><th>{t("field.filename")}</th><th>{t("field.uploaded")}</th><th>{t("field.actions")}</th></tr></thead>
              <tbody>
                {(m.images || []).map((img: any) => {
                  const name = img.file_name || String(img.file_url || "").split("/").pop() || `file-${img.id}`;
                  const isImage = String(img.content_type || "").startsWith("image/") || /\.(png|jpe?g|webp|gif)$/i.test(name);
                  return (
                    <tr key={img.id}>
                      <td>{isImage ? <img src={img.file_url} alt={name} className="h-14 w-14 rounded object-cover" /> : <span className="badge">{t("page.modelDetail.file")}</span>}</td>
                      <td><span className="badge">{imageTypeLabel(img.image_type)}</span></td>
                      <td>{name}</td>
                      <td>{img.created_at ? new Date(img.created_at).toLocaleString() : "-"}</td>
                      <td className="flex gap-3">
                        <a className="text-brand-600 hover:underline" href={img.file_url} download>{t("common.download")}</a>
                        <button className="text-red-600 hover:underline" onClick={() => deleteImage(img.id)}>{t("btn.delete")}</button>
                      </td>
                    </tr>
                  );
                })}
                {(m.images || []).length === 0 && <tr><td colSpan={5} className="text-sm text-slate-500">{t("page.modelDetail.noPatternFiles")}</td></tr>}
              </tbody>
            </table>
          </div>
        )}

        {tab === 5 && (
          <div className="space-y-3">
            <label className="label">{t("page.modelDetail.additionalNote")}</label>
            <textarea className="input min-h-28" value={details.general?.note || ""} onChange={(e) => setDetails({ ...details, general: { ...details.general, note: e.target.value } })} />
          </div>
        )}

        {tab === 6 && (
          <div className="max-w-3xl rounded-md border border-[#ded9ca] bg-white p-5 shadow-sm print:shadow-none">
            <div className="grid grid-cols-[140px_1fr] gap-5">
              <div className="h-40 rounded-md border border-[#ecebe3] bg-[#f8f6ef]">
                {primaryImage ? (
                  <img src={primaryImage.file_url} alt={translatedName} className="h-full w-full rounded-md object-cover" />
                ) : (
                  <div className="flex h-full items-center justify-center text-xs text-slate-400">{t("page.models.noPreview")}</div>
                )}
              </div>
              <div className="space-y-3">
                <div>
                  <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{m.code}</div>
                  <div className="text-2xl font-semibold text-[#14110b]">{translatedName}</div>
                  <div className="text-sm text-slate-600">{modelForm.category || "-"} · {modelForm.product_type || "-"}</div>
                </div>
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div><span className="text-slate-500">{t("page.modelDetail.sizeRange")}</span> {sizeRows.map((s: any) => s.size).join(", ") || "-"}</div>
                  <div><span className="text-slate-500">{t("page.modelDetail.colorsLabel")}</span> {colorRows.map((c: any) => c.color_name).join(", ") || "-"}</div>
                </div>
                <div>
                  <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">{t("page.modelDetail.bomSummary")}</div>
                  <div className="grid grid-cols-1 gap-2 text-sm md:grid-cols-2">
                    <div>
                      <div className="font-medium">{t("page.modelDetail.fabrics")}</div>
                      <ul className="mt-1 space-y-1">
                        {materialRows.map((r: any) => <li key={r.id}>{r.item?.sku || r.item_id} · {n(r.quantity_per_piece).toFixed(4)} {r.unit}</li>)}
                        {materialRows.length === 0 && <li className="text-slate-400">-</li>}
                      </ul>
                    </div>
                    <div>
                      <div className="font-medium">{t("page.modelDetail.accessories")}</div>
                      <ul className="mt-1 space-y-1">
                        {accessoryRows.map((r: any) => <li key={r.id}>{r.item?.sku || r.item_id} · {n(r.quantity_per_piece).toFixed(4)} {r.unit}</li>)}
                        {accessoryRows.length === 0 && <li className="text-slate-400">-</li>}
                      </ul>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {tab === 7 && (
          <div className="space-y-2">
            <form onSubmit={addSize} className="grid grid-cols-1 md:grid-cols-7 gap-2">
              <input className="input" placeholder={t("page.modelDetail.sizeExample")} value={size.size} onChange={(e) => setSize({ ...size, size: e.target.value })} required />
              <input className="input" placeholder={t("page.modelDetail.measurement.chest")} value={measurementFields.chest} onChange={(e) => setMeasurementFields({ ...measurementFields, chest: e.target.value })} />
              <input className="input" placeholder={t("page.modelDetail.measurement.waist")} value={measurementFields.waist} onChange={(e) => setMeasurementFields({ ...measurementFields, waist: e.target.value })} />
              <input className="input" placeholder={t("page.modelDetail.measurement.hip")} value={measurementFields.hip} onChange={(e) => setMeasurementFields({ ...measurementFields, hip: e.target.value })} />
              <input className="input" placeholder={t("page.modelDetail.measurement.length")} value={measurementFields.length} onChange={(e) => setMeasurementFields({ ...measurementFields, length: e.target.value })} />
              <input className="input" placeholder={t("page.modelDetail.measurement.sleeve")} value={measurementFields.sleeve} onChange={(e) => setMeasurementFields({ ...measurementFields, sleeve: e.target.value })} />
              <button className="btn btn-primary" type="submit">{t("btn.add")}</button>
            </form>
            <table className="table">
              <thead><tr><th>{t("field.size")}</th><th>{t("page.modelDetail.measurement.chest")}</th><th>{t("page.modelDetail.measurement.waist")}</th><th>{t("page.modelDetail.measurement.hip")}</th><th>{t("page.modelDetail.measurement.length")}</th><th>{t("page.modelDetail.measurement.sleeve")}</th><th>{t("field.actions")}</th></tr></thead>
              <tbody>
                {(m.sizes || []).map((s: any) => (
                  <tr key={s.id}>
                    <td>{s.size}</td>
                    <td>{s.measurement_json?.chest ?? "-"}</td>
                    <td>{s.measurement_json?.waist ?? "-"}</td>
                    <td>{s.measurement_json?.hip ?? "-"}</td>
                    <td>{s.measurement_json?.length ?? "-"}</td>
                    <td>{s.measurement_json?.sleeve ?? "-"}</td>
                    <td><button className="text-red-600 hover:underline" onClick={() => deleteSize(s.id)}>{t("btn.delete")}</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {tab === 8 && (
          <div className="space-y-3">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div><label className="label">{t("page.modelDetail.complexityLevel")}</label><input className="input" value={details.sewing?.complexity_level || ""} onChange={(e) => setDetails({ ...details, sewing: { ...details.sewing, complexity_level: e.target.value } })} /></div>
              <div><label className="label">{t("page.modelDetail.onePersonNorm")}</label><input className="input" type="number" step="0.01" value={n(details.sewing?.one_person_norm)} onChange={(e) => setDetails({ ...details, sewing: { ...details.sewing, one_person_norm: n(e.target.value) } })} /></div>
              <div><label className="label">{t("field.samMinutes")}</label><input className="input" type="number" step="0.1" value={modelForm.sam_minutes} onChange={(e) => setModelForm({ ...modelForm, sam_minutes: n(e.target.value) })} /></div>
            </div>
            <label className="label">{t("page.modelDetail.sewingNote")}</label>
            <textarea className="input min-h-24" value={details.sewing?.note || ""} onChange={(e) => setDetails({ ...details, sewing: { ...details.sewing, note: e.target.value } })} />
          </div>
        )}

        {tab === 9 && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="font-semibold">{t("page.modelDetail.paidOperations")}</h3>
              <button type="button" className="btn" onClick={addPaidOperation}>
                <Plus className="h-4 w-4" />
                <span>{t("page.modelDetail.addPaidOperation")}</span>
              </button>
            </div>
            <div className="overflow-x-auto">
              <table className="table min-w-[760px]">
                <thead>
                  <tr>
                    <th className="w-12">Use</th>
                    <th>{t("page.modelDetail.operationSection")}</th>
                    <th>{t("common.code")}</th>
                    <th>{t("page.modelDetail.operationName")}</th>
                    <th>{t("page.modelDetail.ratePerPiece")}</th>
                    <th>{t("page.modelDetail.copies")}</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {paidOperations.map((operation) => (
                    <tr key={operation.id}>
                      <td>
                        <input
                          type="checkbox"
                          className="h-4 w-4"
                          checked={operation.selected}
                          onChange={(e) => updatePaidOperation(operation.id, { selected: e.target.checked })}
                        />
                      </td>
                      <td>
                        <select
                          className="input min-w-[130px]"
                          value={operation.section}
                          onChange={(e) => updatePaidOperation(operation.id, { section: e.target.value as SectionCode })}
                        >
                          <option value="sewing">{t("page.modelDetail.sectionSewing")}</option>
                          <option value="pressing">{t("page.modelDetail.sectionPressing")}</option>
                          <option value="packaging">{t("page.modelDetail.sectionPackaging")}</option>
                        </select>
                      </td>
                      <td>
                        <input
                          className="input min-w-[120px] font-mono"
                          value={operation.code}
                          onChange={(e) => updatePaidOperation(operation.id, { code: e.target.value.toUpperCase() })}
                        />
                      </td>
                      <td>
                        <input
                          className="input min-w-[190px]"
                          value={operation.name}
                          onChange={(e) => updatePaidOperation(operation.id, { name: e.target.value })}
                        />
                      </td>
                      <td>
                        <input
                          className="input min-w-[110px]"
                          type="number"
                          min={0}
                          step="0.01"
                          placeholder="0"
                          value={operation.rate}
                          onChange={(e) => updatePaidOperation(operation.id, { rate: e.target.value })}
                        />
                      </td>
                      <td>
                        <input
                          className="input w-20"
                          type="number"
                          min={1}
                          value={operation.copies}
                          onChange={(e) => updatePaidOperation(operation.id, { copies: n(e.target.value) })}
                        />
                      </td>
                      <td>
                        <button
                          type="button"
                          className="icon-btn"
                          title={t("page.modelDetail.removePaidOperation")}
                          onClick={() => removePaidOperation(operation.id)}
                          disabled={paidOperations.length <= 1}
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {tab === 10 && (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div><label className="label">{t("page.modelDetail.langUz")}</label><input className="input" value={details.translation?.uz || ""} onChange={(e) => setDetails({ ...details, translation: { ...details.translation, uz: e.target.value } })} /></div>
            <div><label className="label">{t("page.modelDetail.langRu")}</label><input className="input" value={details.translation?.ru || ""} onChange={(e) => setDetails({ ...details, translation: { ...details.translation, ru: e.target.value } })} /></div>
            <div><label className="label">{t("page.modelDetail.langEn")}</label><input className="input" value={details.translation?.en || ""} onChange={(e) => setDetails({ ...details, translation: { ...details.translation, en: e.target.value } })} /></div>
          </div>
        )}

        {tab === 11 && (
          <div className="space-y-3">
            <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
              <div><label className="label">{t("page.modelDetail.laborPct")}</label><input className="input" type="number" step="0.1" value={laborPct} onChange={(e) => setDetails({ ...details, costing: { ...details.costing, labor_pct: n(e.target.value) } })} /></div>
              <div><label className="label">{t("page.modelDetail.electricityPct")}</label><input className="input" type="number" step="0.1" value={electricityPct} onChange={(e) => setDetails({ ...details, costing: { ...details.costing, electricity_pct: n(e.target.value) } })} /></div>
              <div><label className="label">{t("page.modelDetail.otherPct")}</label><input className="input" type="number" step="0.1" value={otherPct} onChange={(e) => setDetails({ ...details, costing: { ...details.costing, other_pct: n(e.target.value) } })} /></div>
              <div><label className="label">{t("page.modelDetail.targetMarginPct")}</label><input className="input" type="number" step="0.1" value={marginPct} onChange={(e) => setDetails({ ...details, costing: { ...details.costing, target_margin_pct: n(e.target.value) } })} /></div>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
              <div className="card p-3"><div className="text-xs text-slate-500">{t("page.modelDetail.materialAccessoryCostPerPiece")}</div><div className="text-lg font-semibold">${baseCostPerPiece.toFixed(2)}</div></div>
              <div className="card p-3"><div className="text-xs text-slate-500">{t("page.modelDetail.extraCostsPerPiece")}</div><div className="text-lg font-semibold">${(laborCost + electricityCost + otherCost).toFixed(2)}</div></div>
              <div className="card p-3"><div className="text-xs text-slate-500">{t("page.modelDetail.netCostPerPiece")}</div><div className="text-lg font-semibold">${netCost.toFixed(2)}</div></div>
              <div className="card p-3"><div className="text-xs text-slate-500">{t("page.modelDetail.targetPricePerPiece")}</div><div className="text-lg font-semibold">${targetPrice.toFixed(2)}</div></div>
            </div>
          </div>
        )}

        <div className="flex justify-end gap-2 border-t border-[#ecebe3] pt-3">
          {msg && <div className="text-sm text-green-700 self-center">{msg}</div>}
          <button className="btn btn-primary" onClick={saveModel}>{t("common.save")}</button>
        </div>
      </div>
    </div>
  );
}


