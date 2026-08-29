"use client";
import { useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { Plus, Search, Pencil, Trash2, BookOpen } from "lucide-react";
import { fetcher, api } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import Modal from "@/components/Modal";
import { orderReference } from "@/lib/orderRef";
import { modelCodeParts } from "@/lib/modelCode";
import { useDialogs } from "@/components/DialogProvider";
import { storageThumbnailUrl } from "@/lib/modelImages";
import { useT } from "@/lib/i18n";

// ─── Types ───────────────────────────────────────────────────────────────────

type Passport = {
  id: number;
  passport_no: string;
  date: string;
  production_order_id: number | null;
  operator_id: number | null;
  model_code: string | null;
  variant: string | null;
  mold_no: string | null;
  image_ref: string | null;
  operator_name_manual: string | null;
  fabric_type: string | null;
  has_print: boolean;
  order_no: string | null;
  lot_no: string | null;
  size_range: string | null;
  rolls_count: number | null;
  layer_weight_kg: number | null;
  total_layers: number | null;
  planned_kg: number | null;
  pieces: number | null;
  fabric_width_m: number | null;
  lay_length_m: number | null;
  gramage: number | null;
  waste_pct: number | null;
  beka_per_piece_kg: number | null;
  other_beka_per_piece_kg: number | null;
  scrap_kg: number | null;
  ribana_per_piece_kg: number | null;
  notes: string | null;
  // computed
  total_beka_kg: number | null;
  other_beka_kg: number | null;
  total_ribana_kg: number | null;
  actual_kg: number | null;
  pieces_per_layer: number | null;
  size_count: number | null;
  per_piece_weight_kg: number | null;
  theoretical_kg: number | null;
  actual_kg_per_piece: number | null;
  gross_kg_per_piece: number | null;
  // joined
  production_order_no: string | null;
  model_name: string | null;
  model_image_url: string | null;
  operator_name: string | null;
};

type MaterialDefault = {
  production_order_no: string | null;
  order_no: string | null;
  sales_order_no: string | null;
  model_code: string | null;
  model_no: string | null;
  model_name: string | null;
  variant: string | null;
  mold_no: string | null;
  image_ref: string | null;
  has_print: boolean | null;
  size_range: string | null;
  sizes: string[];
  size_count: number | null;
  pieces: number | null;
  planned_kg: number | null;
  fabric_type: string | null;
  material_item_id: number | null;
  material_item_sku: string | null;
  material_item_name: string | null;
  batch_id: number | null;
  batch_no: string | null;
  lot_no: string | null;
  material_order_no: string | null;
  gramage: number | null;
  width: number | null;
  fabric_width_m: number | null;
};

// ─── Example from Excel row 2 ─────────────────────────────────────────────────

const EXCEL_EXAMPLE = {
  passport_no: "6770",
  date: "2026-06-01",
  production_order_id: "" as string | number,
  operator_id: "" as string | number,
  model_code: "R-1175",
  variant: "4685",
  mold_no: "",
  image_ref: "",
  operator_name_manual: "musi",
  fabric_type: "",
  has_print: false,
  order_no: "1588",
  lot_no: "D#11C#4",
  size_range: "44-52",
  rolls_count: 7 as string | number,
  layer_weight_kg: 2.4 as string | number,
  total_layers: 48 as string | number,
  planned_kg: 115 as string | number,
  pieces: 240 as string | number,
  fabric_width_m: 1.8 as string | number,
  lay_length_m: 3.37 as string | number,
  gramage: 0.191 as string | number,
  waste_pct: 15 as string | number,
  beka_per_piece_kg: 0.005 as string | number,
  other_beka_per_piece_kg: "" as string | number,
  scrap_kg: "" as string | number,
  ribana_per_piece_kg: "" as string | number,
  notes: "",
};

const EMPTY_FORM = {
  passport_no: "",
  date: new Date().toISOString().slice(0, 10),
  production_order_id: "" as string | number,
  operator_id: "" as string | number,
  model_code: "",
  variant: "",
  mold_no: "",
  image_ref: "",
  operator_name_manual: "",
  fabric_type: "",
  has_print: false,
  order_no: "",
  lot_no: "",
  size_range: "",
  rolls_count: "" as string | number,
  layer_weight_kg: "" as string | number,
  total_layers: "" as string | number,
  planned_kg: "" as string | number,
  pieces: "" as string | number,
  fabric_width_m: "" as string | number,
  lay_length_m: "" as string | number,
  gramage: "" as string | number,
  waste_pct: "" as string | number,
  beka_per_piece_kg: "" as string | number,
  other_beka_per_piece_kg: "" as string | number,
  scrap_kg: "" as string | number,
  ribana_per_piece_kg: "" as string | number,
  notes: "",
};

// ─── Calculations (mirrors Excel formulas) ────────────────────────────────────

function compute(f: typeof EMPTY_FORM, sizeCount: number) {
  const R = Number(f.pieces) || 0;
  const Y = Number(f.beka_per_piece_kg) || 0;
  const AA = Number(f.other_beka_per_piece_kg) || 0;
  const AD = Number(f.ribana_per_piece_kg) || 0;
  const AB = Number(f.scrap_kg) || 0;
  const M = Number(f.layer_weight_kg) || 0;
  const N = Number(f.total_layers) || 0;
  const S = Number(f.fabric_width_m) || 0;
  const T = Number(f.lay_length_m) || 0;
  const V = Number(f.gramage) || 0;
  const O = Number(f.planned_kg) || 0;

  const X = R * Y;
  const Z = R * AA;
  const AC = R * AD;
  const P = M * N + AB + X;
  const piecesPerLayer = N ? R / N : 0;
  const AE = sizeCount ? S * T * V / sizeCount + Y + AA : 0;
  const Q = AE ? AE * R + AB : 0;
  const AF = R ? P / R : 0;
  const AG = R ? O / R : 0;

  return { X, Z, AC, P, Q, AE, AF, AG, piecesPerLayer };
}

function d2(v: number | null | undefined) { return v ? v.toFixed(2) : "—"; }
function d3(v: number | null | undefined) { return v ? v.toFixed(3) : "—"; }
function d4(v: number | null | undefined) { return v ? v.toFixed(4) : "—"; }
function d6(v: number | null | undefined) { return v ? v.toFixed(6) : "—"; }

// ─── Page ────────────────────────────────────────────────────────────────────

function cleanSize(value: unknown) {
  return String(value ?? "").trim();
}

function uniqueSizes(values: unknown[]) {
  return Array.from(new Set(values.map(cleanSize).filter(Boolean)));
}

function expandSizeSelection(value: string | null | undefined) {
  const raw = cleanSize(value);
  if (!raw) return [];
  const rangeMatch = raw.match(/^(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)$/);
  if (!rangeMatch) return uniqueSizes(raw.split(","));

  const start = Number(rangeMatch[1]);
  const end = Number(rangeMatch[2]);
  if (!Number.isFinite(start) || !Number.isFinite(end) || start >= end) return [raw];

  const step = Number.isInteger(start) && Number.isInteger(end) && end - start >= 2 ? 2 : 1;
  const sizes: string[] = [];
  for (let size = start; size <= end; size += step) {
    sizes.push(Number.isInteger(size) ? String(size) : String(Number(size.toFixed(3))));
  }
  return sizes;
}

function sizeRangeLabel(sizes: string[]) {
  const unique = uniqueSizes(sizes);
  if (unique.length === 0) return "";
  const numeric = unique.map((size) => Number(size));
  if (numeric.every(Number.isFinite)) {
    const min = Math.min(...numeric);
    const max = Math.max(...numeric);
    const fmt = (n: number) => (Number.isInteger(n) ? String(n) : String(n));
    return min === max ? fmt(min) : `${fmt(min)}-${fmt(max)}`;
  }
  return unique.join(", ");
}

function sizeCountForSelection(value: string | number, sizes: string[]) {
  const selected = cleanSize(value);
  if (!selected) return 0;
  const choices = uniqueSizes(sizes);
  if (choices.length === 1 && selected === choices[0]) return 1;
  if (selected === sizeRangeLabel(choices)) return choices.length;
  return expandSizeSelection(selected).length || (choices.includes(selected) ? 1 : 0);
}

function modelQolipNo(model: any): string {
  const general = model?.details_json?.general;
  if (!general || typeof general !== "object") return "";
  return String(
    general.qolip_no
      ?? general.qolipNo
      ?? general.mold_no
      ?? general.moldNo
      ?? general.pattern_no
      ?? general.patternNo
      ?? "",
  ).trim();
}

export default function CuttingPassportsPage() {
  const dialogs = useDialogs();
  const { t } = useT();
  const searchParams = useSearchParams();
  const cuttingDepartment = searchParams.get("cutting_department") === "ECT" ? "ECT" : "CUT";
  const factoryName = cuttingDepartment === "ECT" ? t("factory.ecoCotton") : t("factory.milana");
  const [q, setQ] = useState("");
  const passportSearch = q.trim();
  const passportUrl = `/api/cutting-passports?formula_version=20260706_ishlangan_kg&limit=500&cutting_department_code=${cuttingDepartment}${
    passportSearch ? `&q=${encodeURIComponent(passportSearch)}` : ""
  }`;
  const { data: passports = [], mutate } = useSWR<Passport[]>(passportUrl, fetcher, { keepPreviousData: true });
  const { data: prodOrders = [] } = useSWR<any[]>("/api/production-orders?page_size=500", fetcher);
  const { data: users = [] } = useSWR<any[]>("/api/cutting-passports/operators", fetcher);

  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Passport | null>(null);
  const [form, setForm] = useState({ ...EMPTY_FORM });
  const [sizeChoices, setSizeChoices] = useState<string[]>([]);
  const [err, setErr] = useState("");

  const rows = passports;

  const selectedSizeCount = useMemo(
    () => sizeCountForSelection(form.size_range, sizeChoices),
    [form.size_range, sizeChoices],
  );
  const calc = compute(form, selectedSizeCount);
  const sizeSelectOptions = useMemo(() => {
    const choices = uniqueSizes(sizeChoices);
    const range = sizeRangeLabel(choices);
    const options: { value: string; label: string }[] = [];

    if (range) {
      options.push({
        value: range,
        label: choices.length > 1 ? t("page.cuttingPassports.sizeUnit", { count: choices.length, size: range }) : range,
      });
    }
    for (const size of choices) {
      if (size !== range) options.push({ value: size, label: size });
    }

    const current = cleanSize(form.size_range);
    if (current && !options.some((option) => option.value === current)) {
      const count = sizeCountForSelection(current, choices);
      options.unshift({
        value: current,
        label: count > 1 ? t("page.cuttingPassports.sizeUnit", { count, size: current }) : current,
      });
    }

    return options;
  }, [form.size_range, sizeChoices, t]);

  function openCreate() {
    setForm({ ...EMPTY_FORM, date: new Date().toISOString().slice(0, 10) });
    setSizeChoices([]);
    setEditing(null);
    setErr("");
    setShowForm(true);
  }

  function openEdit(p: Passport) {
    setSizeChoices(expandSizeSelection(p.size_range));
    setForm({
      passport_no: p.passport_no,
      date: p.date.slice(0, 10),
      production_order_id: p.production_order_id ?? "",
      operator_id: p.operator_id ?? "",
      model_code: p.model_code ?? "",
      variant: p.variant ?? "",
      mold_no: p.mold_no ?? "",
      image_ref: p.image_ref ?? "",
      operator_name_manual: p.operator_name_manual ?? "",
      fabric_type: p.fabric_type ?? "",
      has_print: p.has_print,
      order_no: p.order_no ?? p.production_order_no ?? "",
      lot_no: p.lot_no ?? "",
      size_range: p.size_range ?? "",
      rolls_count: p.rolls_count ?? "",
      layer_weight_kg: p.layer_weight_kg ?? "",
      total_layers: p.total_layers ?? "",
      planned_kg: p.planned_kg ?? "",
      pieces: p.pieces ?? "",
      fabric_width_m: p.fabric_width_m ?? "",
      lay_length_m: p.lay_length_m ?? "",
      gramage: p.gramage ?? "",
      waste_pct: p.waste_pct ?? "",
      beka_per_piece_kg: p.beka_per_piece_kg ?? "",
      other_beka_per_piece_kg: p.other_beka_per_piece_kg ?? "",
      scrap_kg: p.scrap_kg ?? "",
      ribana_per_piece_kg: p.ribana_per_piece_kg ?? "",
      notes: p.notes ?? "",
    });
    setEditing(p);
    setErr("");
    setShowForm(true);
  }

  function num(v: string | number) {
    const n = Number(v);
    return isNaN(n) || v === "" ? null : n;
  }

  function buildPayload() {
    return {
      passport_no: form.passport_no,
      date: new Date(form.date).toISOString(),
      production_order_id: num(form.production_order_id),
      operator_id: num(form.operator_id),
      model_code: form.model_code || null,
      variant: form.variant || null,
      mold_no: form.mold_no || null,
      image_ref: form.image_ref || null,
      operator_name_manual: form.operator_name_manual || null,
      fabric_type: form.fabric_type || null,
      has_print: form.has_print,
      order_no: form.order_no || null,
      lot_no: form.lot_no || null,
      size_range: form.size_range || null,
      rolls_count: num(form.rolls_count),
      layer_weight_kg: num(form.layer_weight_kg),
      total_layers: num(form.total_layers),
      planned_kg: num(form.planned_kg),
      pieces: num(form.pieces),
      fabric_width_m: num(form.fabric_width_m),
      lay_length_m: num(form.lay_length_m),
      gramage: num(form.gramage),
      waste_pct: num(form.waste_pct),
      beka_per_piece_kg: num(form.beka_per_piece_kg),
      other_beka_per_piece_kg: num(form.other_beka_per_piece_kg),
      scrap_kg: num(form.scrap_kg),
      ribana_per_piece_kg: num(form.ribana_per_piece_kg),
      notes: form.notes || null,
    };
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    if (!form.passport_no) { setErr(t("page.cuttingPassports.error.passportRequired")); return; }
    try {
      if (editing) {
        await api.patch(`/api/cutting-passports/${editing.id}`, buildPayload());
      } else {
        await api.post("/api/cutting-passports", buildPayload());
      }
      await mutate();
      setShowForm(false);
    } catch (e: any) {
      setErr(e.message || t("page.cuttingPassports.error.saveFailed"));
    }
  }

  async function del(p: Passport) {
    if (!(await dialogs.ask({ message: t("page.cuttingPassports.confirm.delete", { passport: p.passport_no }), tone: "danger" }))) return;
    await api.del(`/api/cutting-passports/${p.id}`);
    mutate();
  }

  const allProdOrders: any[] = Array.isArray(prodOrders) ? prodOrders : (prodOrders as any)?.rows ?? [];
  const prodOrdersArr = allProdOrders.filter((row: any) => (
    cuttingDepartment === "ECT"
      ? row.cutting_department_code === "ECT"
      : row.cutting_department_code !== "ECT"
  ));
  const usersArr: any[] = Array.isArray(users) ? users : [];
  const f = form;
  const sf = (k: keyof typeof EMPTY_FORM) => (e: React.ChangeEvent<any>) =>
    setForm((prev) => ({ ...prev, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));

  async function selectProductionOrder(e: React.ChangeEvent<HTMLSelectElement>) {
    const value = e.target.value;
    setSizeChoices([]);
    const po = prodOrdersArr.find((row: any) => String(row.id) === value);
    setForm((prev) => ({
      ...prev,
      production_order_id: value,
      order_no: po ? orderReference(po, po.production_no || prev.order_no) : "",
      model_code: po?.model_code || "",
      variant: "",
      mold_no: "",
      pieces: po?.planned_quantity ?? prev.pieces,
      planned_kg: po?.estimated_material_amount ?? prev.planned_kg,
    }));
    if (!value) return;
    try {
      const [defaults, model] = await Promise.all([
        api.get<MaterialDefault>(`/api/cutting-passports/material-defaults?production_order_id=${value}`),
        po?.model_id ? api.get<any>(`/api/models/${po.model_id}`).catch(() => null) : Promise.resolve(null),
      ]);
      const parts = model ? modelCodeParts(model) : null;
      const qolipNo = modelQolipNo(model);
      setSizeChoices(defaults.sizes?.length ? defaults.sizes : expandSizeSelection(defaults.size_range));
      setForm((prev) => {
        if (String(prev.production_order_id) !== value) return prev;
        return {
          ...prev,
          order_no: defaults.order_no || defaults.sales_order_no || defaults.production_order_no || prev.order_no,
          model_code: defaults.model_code || defaults.model_no || parts?.code || model?.code || prev.model_code,
          variant: defaults.variant || parts?.variantNo || prev.variant,
          mold_no: defaults.mold_no || qolipNo,
          image_ref: defaults.image_ref || prev.image_ref,
          fabric_type: defaults.fabric_type || defaults.material_item_name || prev.fabric_type,
          has_print: defaults.has_print ?? prev.has_print,
          lot_no: defaults.lot_no || defaults.batch_no || prev.lot_no,
          size_range: defaults.size_range || prev.size_range,
          pieces: defaults.pieces ?? prev.pieces,
          planned_kg: defaults.planned_kg ?? prev.planned_kg,
          gramage: defaults.gramage ?? prev.gramage,
          fabric_width_m: defaults.fabric_width_m ?? defaults.width ?? prev.fabric_width_m,
        };
      });
    } catch {
      // Some older orders may not have a received material batch yet; keep manual entry available.
    }
  }

  function imageValue(p: Passport) {
    return p.image_ref || storageThumbnailUrl(p.model_image_url, 160) || "";
  }

  function looksLikeImage(value: string) {
    return /^https?:\/\//i.test(value) || value.startsWith("/storage/");
  }

  return (
    <div>
      <PageHeader
        title={`${factoryName} - ${t("page.cuttingPassports.title")}`}
        subtitle={t("page.cuttingPassports.subtitle")}
      />

      {/* Toolbar */}
      <div className="mb-4 flex flex-col items-stretch gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-slate-400" />
          <input
            className="input pl-8"
            placeholder={t("page.cuttingPassports.searchPlaceholder")}
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        <button className="btn btn-primary flex items-center gap-1.5" onClick={openCreate}>
          <Plus className="h-4 w-4" /> {t("page.cuttingPassports.newPassport")}
        </button>
      </div>

      {/* Table */}
      <div className="card p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-max text-xs border-collapse">
            <thead>
              {/* Column group row */}
              <tr className="text-[10px] font-bold uppercase tracking-widest">
                <th colSpan={3} className="bg-slate-700 text-white px-3 py-1.5 text-left border-r-2 border-slate-500 lg:sticky lg:left-0 lg:z-30">
                  {t("page.cuttingPassports.group.basic")}
                </th>
                <th colSpan={8} className="bg-slate-600 text-slate-200 px-3 py-1.5 text-left border-r border-slate-500">
                  {t("page.cuttingPassports.group.identification")}
                </th>
                <th colSpan={6} className="bg-blue-700 text-blue-100 px-3 py-1.5 text-center border-r border-blue-500">
                  {t("page.cuttingPassports.group.layup")}
                </th>
                <th colSpan={6} className="bg-violet-700 text-violet-100 px-3 py-1.5 text-center border-r border-violet-500">
                  {t("page.cuttingPassports.group.fabric")}
                </th>
                <th colSpan={7} className="bg-orange-600 text-orange-100 px-3 py-1.5 text-center border-r border-orange-400">
                  {t("page.cuttingPassports.group.bindingRibana")}
                </th>
                <th colSpan={3} className="bg-green-700 text-green-100 px-3 py-1.5 text-center border-r border-green-500">
                  {t("page.cuttingPassports.group.result")}
                </th>
                <th className="bg-slate-700 px-2 py-1.5 lg:sticky lg:right-0 lg:z-30" />
              </tr>
              {/* Column headers */}
              <tr className="border-b-2 border-slate-200 bg-slate-50 text-[11px] font-semibold text-slate-500 uppercase tracking-wide">
                {/* Frozen left */}
                <th className="bg-slate-50 px-3 py-2 text-left whitespace-nowrap min-w-[88px] lg:sticky lg:left-0 lg:z-20 lg:shadow-[2px_0_0_0_#e2e8f0]">{t("page.cuttingPassports.field.passportNo")}</th>
                <th className="bg-slate-50 px-3 py-2 text-left whitespace-nowrap min-w-[90px] lg:sticky lg:left-[88px] lg:z-20">{t("page.cuttingPassports.field.date")}</th>
                <th className="bg-slate-50 px-3 py-2 text-left whitespace-nowrap min-w-[120px] lg:sticky lg:left-[178px] lg:z-20 lg:shadow-[2px_0_6px_-1px_rgba(0,0,0,0.12)]">{t("page.cuttingPassports.field.model")}</th>
                {/* Scrollable cols */}
                <th className="px-3 py-2 text-left whitespace-nowrap">{t("page.cuttingPassports.field.variant")}</th>
                <th className="px-3 py-2 text-left whitespace-nowrap">{t("page.cuttingPassports.field.moldNo")}</th>
                <th className="px-3 py-2 text-left whitespace-nowrap">{t("page.cuttingPassports.field.image")}</th>
                <th className="px-3 py-2 text-left whitespace-nowrap">{t("page.cuttingPassports.field.layupOperator")}</th>
                <th className="px-3 py-2 text-left whitespace-nowrap">{t("page.cuttingPassports.field.fabric")}</th>
                <th className="px-3 py-2 text-left whitespace-nowrap">{t("page.cuttingPassports.field.printing")}</th>
                <th className="px-3 py-2 text-left whitespace-nowrap">{t("page.cuttingPassports.field.order")}</th>
                <th className="px-3 py-2 text-left whitespace-nowrap">{t("page.cuttingPassports.field.lotNo")}</th>
                <th className="px-3 py-2 text-right whitespace-nowrap">{t("page.cuttingPassports.field.rolls")}</th>
                <th className="px-3 py-2 text-right whitespace-nowrap">{t("page.cuttingPassports.field.layerWeight")}</th>
                <th className="px-3 py-2 text-right whitespace-nowrap">{t("page.cuttingPassports.field.totalLayers")}</th>
                <th className="px-3 py-2 text-right whitespace-nowrap">{t("page.cuttingPassports.field.plannedKg")}</th>
                <th className="px-3 py-2 text-right bg-amber-50 text-amber-700 whitespace-nowrap">{t("page.cuttingPassports.field.actualKg")}</th>
                <th className="px-3 py-2 text-right bg-amber-50 text-amber-700 whitespace-nowrap">{t("page.cuttingPassports.field.processedKg")}</th>
                <th className="px-3 py-2 text-right whitespace-nowrap">{t("page.cuttingPassports.field.piecesCount")}</th>
                <th className="px-3 py-2 text-right whitespace-nowrap">{t("page.cuttingPassports.field.fabricWidth")}</th>
                <th className="px-3 py-2 text-right whitespace-nowrap">{t("page.cuttingPassports.field.layLength")}</th>
                <th className="px-3 py-2 text-left whitespace-nowrap">{t("page.cuttingPassports.field.size")}</th>
                <th className="px-3 py-2 text-right whitespace-nowrap">{t("page.cuttingPassports.field.gramage")}</th>
                <th className="px-3 py-2 text-right whitespace-nowrap">{t("page.cuttingPassports.field.wastePct")}</th>
                <th className="px-3 py-2 text-right bg-amber-50 text-amber-700 whitespace-nowrap">{t("page.cuttingPassports.field.bindingTotal")}</th>
                <th className="px-3 py-2 text-right whitespace-nowrap">{t("page.cuttingPassports.field.bindingPerPiece")}</th>
                <th className="px-3 py-2 text-right bg-amber-50 text-amber-700 whitespace-nowrap">{t("page.cuttingPassports.field.otherBindingTotal")}</th>
                <th className="px-3 py-2 text-right whitespace-nowrap">{t("page.cuttingPassports.field.otherBindingPerPiece")}</th>
                <th className="px-3 py-2 text-right whitespace-nowrap">{t("page.cuttingPassports.field.scrapKg")}</th>
                <th className="px-3 py-2 text-right bg-amber-50 text-amber-700 whitespace-nowrap">{t("page.cuttingPassports.field.ribanaTotal")}</th>
                <th className="px-3 py-2 text-right whitespace-nowrap">{t("page.cuttingPassports.field.ribanaPerPiece")}</th>
                <th className="px-3 py-2 text-right bg-green-50 text-green-700 whitespace-nowrap">{t("page.cuttingPassports.field.perPieceGr")}</th>
                <th className="px-3 py-2 text-right bg-green-50 text-green-700 whitespace-nowrap">{t("page.cuttingPassports.field.layerGr")}</th>
                <th className="px-3 py-2 text-right bg-green-50 text-green-700 whitespace-nowrap">{t("page.cuttingPassports.field.grossGr")}</th>
                {/* Frozen right: actions */}
                <th className="bg-slate-50 px-2 py-2 lg:sticky lg:right-0 lg:z-20 lg:shadow-[-2px_0_6px_-1px_rgba(0,0,0,0.12)]" />
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr>
                  <td colSpan={34} className="py-10 text-center text-slate-400">
                    {t("page.cuttingPassports.empty")}
                  </td>
                </tr>
              )}
              {rows.map((p) => (
                <tr key={p.id} className="border-b border-slate-100 hover:bg-stone-50 group">
                  {/* Frozen left */}
                  <td className="bg-white group-hover:bg-stone-50 px-3 py-2 font-mono font-semibold whitespace-nowrap min-w-[88px] lg:sticky lg:left-0 lg:z-10 lg:shadow-[2px_0_0_0_#f1f5f9]">{p.passport_no}</td>
                  <td className="bg-white group-hover:bg-stone-50 px-3 py-2 whitespace-nowrap min-w-[90px] lg:sticky lg:left-[88px] lg:z-10">{p.date.slice(0, 10)}</td>
                  <td className="bg-white group-hover:bg-stone-50 px-3 py-2 whitespace-nowrap min-w-[120px] lg:sticky lg:left-[178px] lg:z-10 lg:shadow-[2px_0_6px_-1px_rgba(0,0,0,0.08)]" title={p.model_name ?? ""}>{p.model_code ?? p.model_name ?? "—"}</td>
                  {/* Scrollable */}
                  <td className="px-3 py-2">{p.variant ?? "—"}</td>
                  <td className="px-3 py-2">{p.mold_no ?? "—"}</td>
                  <td className="px-3 py-2">
                    {imageValue(p) ? (
                      looksLikeImage(imageValue(p)) ? (
                        <img src={imageValue(p)} alt="" className="h-10 w-10 rounded object-cover" />
                      ) : (
                        <span className="whitespace-nowrap">{imageValue(p)}</span>
                      )
                    ) : "—"}
                  </td>
                  <td className="px-3 py-2">{p.operator_name ?? "—"}</td>
                  <td className="px-3 py-2">{p.fabric_type ?? "—"}</td>
                  <td className="px-3 py-2 text-center">{p.has_print ? "✓" : ""}</td>
                  <td className="px-3 py-2 font-mono">{p.order_no ?? p.production_order_no ?? "—"}</td>
                  <td className="px-3 py-2 font-mono">{p.lot_no ?? "—"}</td>
                  <td className="px-3 py-2 text-right">{p.rolls_count ?? "—"}</td>
                  <td className="px-3 py-2 text-right">{d3(p.layer_weight_kg)}</td>
                  <td className="px-3 py-2 text-right">{p.total_layers ?? "—"}</td>
                  <td className="px-3 py-2 text-right">{d2(p.planned_kg)}</td>
                  <td className="px-3 py-2 text-right bg-amber-50 font-medium">{d3(p.actual_kg)}</td>
                  <td className="px-3 py-2 text-right bg-amber-50 font-medium" title={t("page.cuttingPassports.formula.processedKg")}>{d3(p.theoretical_kg)}</td>
                  <td className="px-3 py-2 text-right">{p.pieces ?? "—"}</td>
                  <td className="px-3 py-2 text-right">{p.fabric_width_m ?? "—"}</td>
                  <td className="px-3 py-2 text-right">{p.lay_length_m ?? "—"}</td>
                  <td className="px-3 py-2">
                    {p.size_range ?? "—"}
                    {p.size_count ? <span className="ml-1 text-[11px] text-slate-500">{t("page.cuttingPassports.sizeCount", { count: p.size_count })}</span> : null}
                  </td>
                  <td className="px-3 py-2 text-right">{p.gramage ?? "—"}</td>
                  <td className="px-3 py-2 text-right">{p.waste_pct ?? "—"}</td>
                  <td className="px-3 py-2 text-right bg-amber-50">{d4(p.total_beka_kg)}</td>
                  <td className="px-3 py-2 text-right">{d6(p.beka_per_piece_kg)}</td>
                  <td className="px-3 py-2 text-right bg-amber-50">{d4(p.other_beka_kg)}</td>
                  <td className="px-3 py-2 text-right">{d6(p.other_beka_per_piece_kg)}</td>
                  <td className="px-3 py-2 text-right">{d3(p.scrap_kg)}</td>
                  <td className="px-3 py-2 text-right bg-amber-50">{d4(p.total_ribana_kg)}</td>
                  <td className="px-3 py-2 text-right">{d6(p.ribana_per_piece_kg)}</td>
                  <td className="px-3 py-2 text-right bg-green-50 font-semibold text-green-900">{d6(p.per_piece_weight_kg)}</td>
                  <td className="px-3 py-2 text-right bg-green-50 font-semibold text-green-900">{d6(p.actual_kg_per_piece)}</td>
                  <td className="px-3 py-2 text-right bg-green-50 font-semibold text-green-900">{d6(p.gross_kg_per_piece)}</td>
                  {/* Frozen right */}
                  <td className="bg-white group-hover:bg-stone-50 px-2 py-2 lg:sticky lg:right-0 lg:z-10 lg:shadow-[-2px_0_6px_-1px_rgba(0,0,0,0.08)]">
                    <div className="flex gap-1">
                      <button className="btn btn-ghost p-1" onClick={() => openEdit(p)}>
                        <Pencil className="h-3.5 w-3.5" />
                      </button>
                      <button className="btn btn-ghost p-1 text-red-500" onClick={() => del(p)}>
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Form modal */}
      <Modal
        open={showForm}
        onClose={() => setShowForm(false)}
        title={editing ? t("page.cuttingPassports.editTitle", { passport: editing.passport_no }) : t("page.cuttingPassports.createTitle")}
        wide
        closeOnOutsideClick={false}
      >
        <form onSubmit={save} className="space-y-5">

          {!editing && (
            <div className="flex items-center gap-2 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-700">
              <BookOpen className="h-3.5 w-3.5 shrink-0" />
              <span>{t("page.cuttingPassports.exampleLabel")}</span>
              <button type="button" className="font-semibold underline" onClick={() => setForm({ ...EXCEL_EXAMPLE })}>
                {t("page.cuttingPassports.exampleLoad")}
              </button>
            </div>
          )}

          <Sec label={t("page.cuttingPassports.section.basicInfo")}>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Field label={t("page.cuttingPassports.field.passportNoRequired")}>
                <input className="input" placeholder={t("page.cuttingPassports.placeholder.exampleNumber")} value={f.passport_no} onChange={sf("passport_no")} required />
              </Field>
              <Field label={t("page.cuttingPassports.field.date")}>
                <input className="input" type="date" value={f.date} onChange={sf("date")} />
              </Field>
            </div>
          </Sec>

          <Sec label={t("page.cuttingPassports.section.modelIdentification")}>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-3">
              <Field label={t("page.cuttingPassports.field.erpOrderModel")}>
                <select className="input" value={f.production_order_id} onChange={selectProductionOrder}>
                  <option value="">{t("page.cuttingPassports.placeholder.chooseNone")}</option>
                  {prodOrdersArr.map((po: any) => {
                    return (
                      <option key={po.id} value={po.id}>
                        {orderReference(po, po.production_no)}{po.model_code ? ` · ${po.model_code}` : ""}
                      </option>
                    );
                  })}
                </select>
              </Field>
              <Field label={t("page.cuttingPassports.field.model")}>
                <input className="input" placeholder={t("page.cuttingPassports.placeholder.exampleModel")} value={f.model_code} onChange={sf("model_code")} />
              </Field>
              <Field label={t("page.cuttingPassports.field.variant")}>
                <input className="input" placeholder={t("page.cuttingPassports.placeholder.exampleVariant")} value={f.variant} onChange={sf("variant")} />
              </Field>
              <Field label={t("page.cuttingPassports.field.moldNumber")}>
                <input className="input" placeholder={t("page.cuttingPassports.placeholder.moldNo")} value={f.mold_no} onChange={sf("mold_no")} />
              </Field>
              <Field label={t("page.cuttingPassports.field.image")}>
                <input className="input" placeholder={t("page.cuttingPassports.placeholder.imageRef")} value={f.image_ref} onChange={sf("image_ref")} />
              </Field>
              <Field label={t("page.cuttingPassports.field.operatorErp")}>
                <select className="input" value={f.operator_id} onChange={sf("operator_id")}>
                  <option value="">{t("page.cuttingPassports.placeholder.chooseNone")}</option>
                  {usersArr.map((u: any) => (
                    <option key={u.id} value={u.id}>{u.name}</option>
                  ))}
                </select>
              </Field>
              <Field label={t("page.cuttingPassports.field.operatorExcel")}>
                <input className="input" placeholder={t("page.cuttingPassports.placeholder.exampleOperator")} value={f.operator_name_manual} onChange={sf("operator_name_manual")} />
              </Field>
              <Field label={t("page.cuttingPassports.field.fabric")}>
                <input className="input" placeholder={t("page.cuttingPassports.placeholder.fabricType")} value={f.fabric_type} onChange={sf("fabric_type")} />
              </Field>
              <Field label={t("page.cuttingPassports.field.printing")}>
                <label className="flex h-9 items-center gap-2">
                  <input type="checkbox" className="h-4 w-4" checked={f.has_print} onChange={sf("has_print")} />
                  <span className="text-sm text-slate-600">{t("page.cuttingPassports.field.hasPrint")}</span>
                </label>
              </Field>
              <Field label={t("page.cuttingPassports.field.order")}>
                <input className="input" placeholder={t("page.cuttingPassports.placeholder.exampleOrder")} value={f.order_no} onChange={sf("order_no")} />
              </Field>
              <Field label={t("page.cuttingPassports.field.lotNumber")}>
                <input className="input" placeholder={t("page.cuttingPassports.placeholder.exampleLot")} value={f.lot_no} onChange={sf("lot_no")} />
              </Field>
            </div>
          </Sec>

          <Sec label={t("page.cuttingPassports.section.layupInfo")}>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-3">
              <Field label={t("page.cuttingPassports.field.rollsCount")}>
                <input className="input" type="number" placeholder="0" value={f.rolls_count} onChange={sf("rolls_count")} />
              </Field>
              <Field label={t("page.cuttingPassports.field.layerWeightKg")}>
                <input className="input" type="number" step="0.001" placeholder="2.400" value={f.layer_weight_kg} onChange={sf("layer_weight_kg")} />
              </Field>
              <Field label={t("page.cuttingPassports.field.totalLayers")}>
                <input className="input" type="number" placeholder="48" value={f.total_layers} onChange={sf("total_layers")} />
              </Field>
              <Field label={t("page.cuttingPassports.field.plannedKgLong")}>
                <input className="input" type="number" step="0.001" placeholder="115" value={f.planned_kg} onChange={sf("planned_kg")} />
              </Field>
              <CalcBox label={t("page.cuttingPassports.field.actualKgLong")} formula={t("page.cuttingPassports.formula.actualKg")}>
                {calc.P ? calc.P.toFixed(3) : "—"}
              </CalcBox>
              <CalcBox label={t("page.cuttingPassports.field.processedKg")} formula={t("page.cuttingPassports.formula.processedKg")}>
                {calc.Q ? calc.Q.toFixed(3) : "—"}
              </CalcBox>
              <Field label={t("page.cuttingPassports.field.piecesDetails")}>
                <input className="input" type="number" placeholder="240" value={f.pieces} onChange={sf("pieces")} />
              </Field>
            </div>
          </Sec>

          <Sec label={t("page.cuttingPassports.section.fabricMeasurements")}>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-3">
              <Field label={t("page.cuttingPassports.field.fabricWidthM")}>
                <input className="input" type="number" step="0.01" placeholder="1.80" value={f.fabric_width_m} onChange={sf("fabric_width_m")} />
              </Field>
              <Field label={t("page.cuttingPassports.field.layLengthM")}>
                <input className="input" type="number" step="0.01" placeholder="3.37" value={f.lay_length_m} onChange={sf("lay_length_m")} />
              </Field>
              <Field label={t("page.cuttingPassports.field.size")}>
                <select className="input" value={f.size_range} onChange={sf("size_range")} disabled={sizeSelectOptions.length === 0}>
                  <option value="">{sizeSelectOptions.length ? t("page.cuttingPassports.placeholder.selectSize") : t("page.cuttingPassports.placeholder.selectOrderModel")}</option>
                  {sizeSelectOptions.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
                {selectedSizeCount > 0 && (
                  <div className="mt-1 text-[11px] text-slate-500">
                    {t("page.cuttingPassports.sizeSelectedCount", { count: selectedSizeCount })}
                  </div>
                )}
              </Field>
              <Field label={t("page.cuttingPassports.field.gramageKgM2")}>
                <input className="input" type="number" step="0.001" placeholder="0.191" value={f.gramage} onChange={sf("gramage")} />
              </Field>
              <Field label={t("page.cuttingPassports.field.wastePct")}>
                <input className="input" type="number" step="0.1" placeholder="15" value={f.waste_pct} onChange={sf("waste_pct")} />
              </Field>
            </div>
          </Sec>

          <Sec label={t("page.cuttingPassports.section.bindingRibanaPerPiece")}>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-3">
              <CalcBox label={t("page.cuttingPassports.field.bindingTotal")} formula={t("page.cuttingPassports.formula.bindingTotal")}>
                {calc.X ? calc.X.toFixed(4) : "—"}
              </CalcBox>
              <Field label={t("page.cuttingPassports.field.bindingPerPieceKg")}>
                <input className="input" type="number" step="0.0001" placeholder="0.0050" value={f.beka_per_piece_kg} onChange={sf("beka_per_piece_kg")} />
              </Field>
              <CalcBox label={t("page.cuttingPassports.field.otherBindingTotal")} formula={t("page.cuttingPassports.formula.otherBindingTotal")}>
                {calc.Z ? calc.Z.toFixed(4) : "—"}
              </CalcBox>
              <Field label={t("page.cuttingPassports.field.otherBindingPerPieceKg")}>
                <input className="input" type="number" step="0.0001" placeholder="0.0000" value={f.other_beka_per_piece_kg} onChange={sf("other_beka_per_piece_kg")} />
              </Field>
              <Field label={t("page.cuttingPassports.field.scrapCuttingKg")}>
                <input className="input" type="number" step="0.001" placeholder="0.000" value={f.scrap_kg} onChange={sf("scrap_kg")} />
              </Field>
              <CalcBox label={t("page.cuttingPassports.field.ribanaTotal")} formula={t("page.cuttingPassports.formula.ribanaTotal")}>
                {calc.AC ? calc.AC.toFixed(4) : "—"}
              </CalcBox>
              <Field label={t("page.cuttingPassports.field.ribanaPerPieceKg")}>
                <input className="input" type="number" step="0.0001" placeholder="0.0000" value={f.ribana_per_piece_kg} onChange={sf("ribana_per_piece_kg")} />
              </Field>
            </div>
          </Sec>

          <Sec label={t("page.cuttingPassports.section.results")}>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-3">
              <CalcBox label={t("page.cuttingPassports.field.perPieceGr")} formula={t("page.cuttingPassports.formula.perPieceGr")} highlight>
                {calc.AE ? calc.AE.toFixed(6) : "—"}
              </CalcBox>
              <CalcBox label={t("page.cuttingPassports.field.layerGrLong")} formula={t("page.cuttingPassports.formula.layerGr")} highlight>
                {calc.AF ? calc.AF.toFixed(6) : "—"}
              </CalcBox>
              <CalcBox label={t("page.cuttingPassports.field.grossGr")} formula={t("page.cuttingPassports.formula.grossGr")} highlight>
                {calc.AG ? calc.AG.toFixed(6) : "—"}
              </CalcBox>
            </div>
          </Sec>

          <Field label={t("page.cuttingPassports.field.notes")}>
            <textarea className="input" rows={2} placeholder={t("page.cuttingPassports.placeholder.notes")} value={f.notes} onChange={sf("notes")} />
          </Field>

          {err && <p className="text-sm text-red-600">{err}</p>}

          <div className="flex flex-col-reverse gap-2 pt-1 sm:flex-row sm:justify-end">
            <button type="button" className="btn" onClick={() => setShowForm(false)}>{t("common.cancel")}</button>
            <button type="submit" className="btn btn-primary">
              {editing ? t("common.save") : t("common.create")}
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function Sec({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-2 text-[11px] font-semibold uppercase tracking-widest text-slate-400">{label}</p>
      {children}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="mb-1 block text-xs font-medium text-slate-600">{label}</label>
      {children}
    </div>
  );
}

function CalcBox({ label, formula, children, highlight }: {
  label: string; formula: string; children: React.ReactNode; highlight?: boolean;
}) {
  return (
    <div className={`rounded-lg border px-3 py-2.5 ${highlight ? "border-green-200 bg-green-50" : "border-amber-200 bg-amber-50"}`}>
      <p className={`mb-0.5 text-[10px] font-semibold ${highlight ? "text-green-700" : "text-amber-700"}`}>{label}</p>
      <p className={`text-lg font-bold ${highlight ? "text-green-900" : "text-amber-900"}`}>{children}</p>
      <p className="mt-0.5 text-[9px] text-slate-400">{formula}</p>
    </div>
  );
}
