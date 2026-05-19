"use client";
import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { fetcher, api } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";
import { statusLabel } from "@/components/StagePipeline";

type ModelDetails = {
  general?: {
    full_name?: string;
    brand?: string;
    product_type?: string;
    season?: string;
    designer?: string;
    constructor?: string;
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
  features?: Record<string, boolean>;
};

const TAB_KEYS = [
  "page.modelDetail.tab.general",
  "page.modelDetail.tab.materials",
  "page.modelDetail.tab.variants",
  "page.modelDetail.tab.pattern",
  "page.modelDetail.tab.other",
  "page.modelDetail.tab.miniPost",
  "page.modelDetail.tab.sizeChart",
  "page.modelDetail.tab.sewingGuide",
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

export default function ModelDetail() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const { t } = useT();
  const { data: m, mutate } = useSWR<any>(`/api/models/${id}`, fetcher);
  const { data: items } = useSWR<any[]>("/api/inventory/items", fetcher);
  const tabs = TAB_KEYS.map((k) => t(k));

  const [tab, setTab] = useState(1);
  const [msg, setMsg] = useState("");

  const [modelForm, setModelForm] = useState({
    code: "",
    name: "",
    category: "",
    description: "",
    status: "draft",
    sam_minutes: 0,
  });
  const [details, setDetails] = useState<ModelDetails>({});

  const [bomRow, setBomRow] = useState({ item_id: 0, size: "", color: "", quantity_per_piece: 1, unit: "kg", waste_percent: 5 });
  const [color, setColor] = useState({ color_name: "", color_code: "" });
  const [size, setSize] = useState({ size: "", measurement_json: "" });
  const [measurementFields, setMeasurementFields] = useState({ chest: "", waist: "", hip: "", length: "", sleeve: "" });
  const [sizePreview, setSizePreview] = useState<{ size: string; measurement_json: Record<string, number> | null } | null>(null);
  const [imageForm, setImageForm] = useState({ file_url: "", is_primary: false });
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [isUploadingImage, setIsUploadingImage] = useState(false);

  useEffect(() => {
    if (!m) return;
    setModelForm({
      code: m.code ?? "",
      name: m.name ?? "",
      category: m.category ?? "",
      description: m.description ?? "",
      status: m.status ?? "draft",
      sam_minutes: n(m.sam_minutes),
    });
    setDetails(m.details_json || {});
  }, [m]);

  useEffect(() => {
    const generated = buildMeasurementJson(measurementFields);
    setSize((prev) => ({ ...prev, measurement_json: JSON.stringify(generated) }));
  }, [measurementFields.chest, measurementFields.waist, measurementFields.hip, measurementFields.length, measurementFields.sleeve]);

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

  const variants = useMemo(() => {
    const colors = m?.colors || [];
    const sizes = m?.sizes || [];
    const rows: Array<{ color: string; size: string }> = [];
    for (const c of colors) for (const s of sizes) rows.push({ color: c.color_name, size: s.size });
    return rows;
  }, [m?.colors, m?.sizes]);

  if (!m) return <div>{t("common.loading")}</div>;

  async function saveModel() {
    await api.patch(`/api/models/${id}`, {
      ...modelForm,
      category: modelForm.category || null,
      description: modelForm.description || null,
      details_json: details,
    });
    setMsg(t("msg.saved"));
    mutate();
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
  }

  async function addSize(e: React.FormEvent) {
    e.preventDefault();
    const generated = buildMeasurementJson(measurementFields);
    const baseJson = Object.keys(generated).length ? generated : null;
    let measurementJson: any = baseJson;
    if (size.measurement_json.trim()) {
      try {
        measurementJson = JSON.parse(size.measurement_json.trim());
      } catch {
        alert(t("page.modelDetail.alert.invalidMeasurementJson"));
        return;
      }
    }
    setSizePreview({ size: size.size, measurement_json: measurementJson });
  }

  async function confirmAddSize() {
    if (!sizePreview) return;
    await api.post(`/api/models/${id}/sizes`, { size: sizePreview.size, measurement_json: sizePreview.measurement_json });
    setSize({ size: "", measurement_json: "" });
    setMeasurementFields({ chest: "", waist: "", hip: "", length: "", sleeve: "" });
    setSizePreview(null);
    mutate();
  }

  async function addImage(e: React.FormEvent) {
    e.preventDefault();
    if (imageFile) {
      setIsUploadingImage(true);
      try {
        const form = new FormData();
        form.append("file", imageFile);
        await api.postForm(`/api/models/${id}/images/upload`, form);
      } finally {
        setIsUploadingImage(false);
      }
      setImageFile(null);
      setImageForm({ file_url: "", is_primary: false });
      mutate();
      return;
    }
    if (!imageForm.file_url.trim()) return;
    await api.post(`/api/models/${id}/images`, imageForm);
    setImageForm({ file_url: "", is_primary: false });
    mutate();
  }

  function tabButton(index: number, label: string) {
    const active = tab === index;
    return (
      <button
        type="button"
        key={index}
        onClick={() => setTab(index)}
        className={`px-3 py-1.5 text-xs border-b-2 ${active ? "border-[#14110b] text-[#14110b] font-semibold" : "border-transparent text-slate-500"}`}
      >
        {label} <span className="badge">{index}</span>
      </button>
    );
  }

  return (
    <div>
      <PageHeader
        title={t("page.modelDetail.viewTitle", { code: m.code })}
        subtitle={t("page.modelDetail.subtitle", { name: m.name, status: statusLabel(m.status, t) })}
      />
      <div className="card p-4 space-y-4">
        <div className="flex flex-wrap gap-1 border-b border-[#ecebe3] pb-2">
          {tabs.map((label, i) => tabButton(i + 1, label))}
        </div>

        {tab === 1 && (
          <div className="space-y-3">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div><label className="label">{t("common.code")}</label><input className="input" value={modelForm.code} onChange={(e) => setModelForm({ ...modelForm, code: e.target.value })} /></div>
              <div><label className="label">{t("common.name")}</label><input className="input" value={modelForm.name} onChange={(e) => setModelForm({ ...modelForm, name: e.target.value })} /></div>
              <div><label className="label">{t("field.category")}</label><input className="input" value={modelForm.category} onChange={(e) => setModelForm({ ...modelForm, category: e.target.value })} /></div>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
              <div><label className="label">{t("field.brand")}</label><input className="input" value={details.general?.brand || ""} onChange={(e) => setDetails({ ...details, general: { ...details.general, brand: e.target.value } })} /></div>
              <div><label className="label">{t("field.type")}</label><input className="input" value={details.general?.product_type || ""} onChange={(e) => setDetails({ ...details, general: { ...details.general, product_type: e.target.value } })} /></div>
              <div><label className="label">{t("field.season")}</label><input className="input" value={details.general?.season || ""} onChange={(e) => setDetails({ ...details, general: { ...details.general, season: e.target.value } })} /></div>
              <div><label className="label">{t("field.samMinutes")}</label><input className="input" type="number" step="0.1" value={modelForm.sam_minutes} onChange={(e) => setModelForm({ ...modelForm, sam_minutes: n(e.target.value) })} /></div>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div><label className="label">{t("page.modelDetail.constructor")}</label><input className="input" value={details.general?.constructor || ""} onChange={(e) => setDetails({ ...details, general: { ...details.general, constructor: e.target.value } })} /></div>
              <div><label className="label">{t("page.modelDetail.designer")}</label><input className="input" value={details.general?.designer || ""} onChange={(e) => setDetails({ ...details, general: { ...details.general, designer: e.target.value } })} /></div>
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
                <textarea className="input min-h-20" placeholder={t("page.modelDetail.measurementJsonHelp")} value={size.measurement_json} onChange={(e) => setSize({ ...size, measurement_json: e.target.value })} />
              </form>
            </div>
            {sizePreview && (
              <div className="card p-3 flex items-center justify-between gap-2">
                <div className="text-sm">
                  <div><span className="text-slate-500">{t("field.size")}:</span> {sizePreview.size}</div>
                  <div><span className="text-slate-500">{t("page.modelDetail.measurementJson")}:</span> <code>{JSON.stringify(sizePreview.measurement_json || {})}</code></div>
                </div>
                <div className="flex gap-2">
                  <button type="button" className="btn" onClick={() => setSizePreview(null)}>{t("btn.cancel")}</button>
                  <button type="button" className="btn btn-primary" onClick={confirmAddSize}>{t("page.modelDetail.confirmAdd")}</button>
                </div>
              </div>
            )}
            <table className="table">
              <thead><tr><th>{t("page.modelDetail.variant")}</th><th>{t("field.color")}</th><th>{t("field.size")}</th><th>{t("page.modelDetail.estimatedNetCostPerPiece")}</th></tr></thead>
              <tbody>
                {variants.map((v, idx) => (
                  <tr key={`${v.color}-${v.size}-${idx}`}>
                    <td>{idx + 1}</td><td>{v.color}</td><td>{v.size}</td><td>${netCost.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {tab === 4 && (
          <div className="space-y-3">
            <form onSubmit={addImage} className="grid grid-cols-1 md:grid-cols-5 gap-2">
              <input
                className="input md:col-span-3"
                type="file"
                accept="image/*"
                onChange={(e) => setImageFile(e.target.files?.[0] || null)}
              />
              <input
                className="input"
                placeholder={t("page.modelDetail.orImageUrl")}
                value={imageForm.file_url}
                onChange={(e) => setImageForm({ ...imageForm, file_url: e.target.value })}
              />
              <button className="btn btn-primary" disabled={isUploadingImage || (!imageFile && !imageForm.file_url.trim())}>
                {isUploadingImage ? t("common.uploading") : t("page.modelDetail.attachOrAdd")}
              </button>
            </form>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
              {(m.images || []).map((img: any) => (
                <div key={img.id} className="card p-2">
                  <img src={img.file_url} alt={`model-${img.id}`} className="w-full h-28 object-cover rounded" />
                </div>
              ))}
            </div>
          </div>
        )}

        {tab === 5 && (
          <div className="space-y-3">
            <label className="label">{t("page.modelDetail.additionalNote")}</label>
            <textarea className="input min-h-28" value={details.general?.note || ""} onChange={(e) => setDetails({ ...details, general: { ...details.general, note: e.target.value } })} />
          </div>
        )}

        {tab === 6 && (
          <div className="card p-3">
            <div className="text-sm text-slate-600">{t("page.modelDetail.miniPostNote")}</div>
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
            <textarea className="input min-h-16" placeholder={t("page.modelDetail.measurementJsonAutoEditable")} value={size.measurement_json} onChange={(e) => setSize({ ...size, measurement_json: e.target.value })} />
            {sizePreview && (
              <div className="card p-3 flex items-center justify-between gap-2">
                <div className="text-sm">
                  <div><span className="text-slate-500">{t("field.size")}:</span> {sizePreview.size}</div>
                  <div><span className="text-slate-500">{t("page.modelDetail.measurementJson")}:</span> <code>{JSON.stringify(sizePreview.measurement_json || {})}</code></div>
                </div>
                <div className="flex gap-2">
                  <button type="button" className="btn" onClick={() => setSizePreview(null)}>{t("btn.cancel")}</button>
                  <button type="button" className="btn btn-primary" onClick={confirmAddSize}>{t("page.modelDetail.confirmAdd")}</button>
                </div>
              </div>
            )}
            <table className="table">
              <thead><tr><th>{t("field.size")}</th><th>{t("page.modelDetail.measurementJson")}</th></tr></thead>
              <tbody>
                {(m.sizes || []).map((s: any) => (
                  <tr key={s.id}>
                    <td>{s.size}</td>
                    <td><code>{JSON.stringify(s.measurement_json || {})}</code></td>
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
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div><label className="label">{t("page.modelDetail.langUz")}</label><input className="input" value={details.translation?.uz || ""} onChange={(e) => setDetails({ ...details, translation: { ...details.translation, uz: e.target.value } })} /></div>
            <div><label className="label">{t("page.modelDetail.langRu")}</label><input className="input" value={details.translation?.ru || ""} onChange={(e) => setDetails({ ...details, translation: { ...details.translation, ru: e.target.value } })} /></div>
            <div><label className="label">{t("page.modelDetail.langEn")}</label><input className="input" value={details.translation?.en || ""} onChange={(e) => setDetails({ ...details, translation: { ...details.translation, en: e.target.value } })} /></div>
          </div>
        )}

        {tab === 10 && (
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


