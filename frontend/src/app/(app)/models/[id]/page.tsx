"use client";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import useSWR from "swr";
import useSWRInfinite from "swr/infinite";
import { Edit3, Plus, Trash2 } from "lucide-react";
import { fetcher, api } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import SearchableSelect from "@/components/SearchableSelect";
import { useT } from "@/lib/i18n";
import { statusLabel } from "@/components/StagePipeline";
import { useDialogs } from "@/components/DialogProvider";
import { buildModelCode, modelCodeParts } from "@/lib/modelCode";
import { compositionTotal, formatComposition, type MaterialComposition } from "@/lib/materialComposition";
import { formatModelComposition } from "@/lib/modelComposition";
import { oldErpModelInfoFromDetails } from "@/lib/oldErpModelInfo";
import { imagePreviewHref, storageThumbnailUrl } from "@/lib/modelImages";
import { prepareModelImageUpload } from "@/lib/imageUpload";
import { MATERIAL_COLOR_OPTIONS } from "@/lib/materialColors";
import { GARMENT_SIZE_OPTIONS } from "@/lib/garmentSizes";
import { parseNumberInput, type NumberInputValue } from "@/lib/numberInput";
import VerticalModelPhoto from "@/components/VerticalModelPhoto";
import PaidOperationsEditor from "@/components/PaidOperationsEditor";
import { useMe } from "@/lib/auth";
import {
  createPaidOperation,
  materializeLegacyPaidOperations,
  PAID_OPERATION_FACTORIES,
  paidOperationFactoryFromDepartmentCode,
  paidOperationsFromDetails,
  serializePaidOperations,
  withPaidOperations,
  type PaidOperation,
  type PaidOperationFactory,
} from "@/lib/modelPaidOperations";

type ModelDetails = {
  general?: {
    full_name?: string;
    model_no?: string;
    variant_no?: string;
    brand?: string;
    brand_id?: number;
    product_type?: string;
    season?: string;
    designer?: string;
    designer_employee_id?: number;
    constructor?: string;
    constructor_employee_id?: number;
    qolip_no?: string;
    qolipNo?: string;
    mold_no?: string;
    moldNo?: string;
    pattern_no?: string;
    patternNo?: string;
    note?: string;
  };
  sewing?: {
    complexity_level?: string;
    one_person_norm?: NumberInputValue;
    note?: string;
  };
  translation?: {
    uz?: string;
    ru?: string;
    en?: string;
  };
  costing?: {
    labor_pct?: NumberInputValue;
    electricity_pct?: NumberInputValue;
    other_pct?: NumberInputValue;
    target_margin_pct?: NumberInputValue;
  };
  paid_operations?: PaidOperation[];
  paidOperations?: PaidOperation[];
  composition?: MaterialComposition[];
  features?: Record<string, boolean>;
};

type ImageUploadType = "model" | "pattern";
type BomSection = "material" | "accessory";
type BomFormState = {
  item_id: number;
  material_name: string;
  material_role: "main" | "secondary";
  stock_batch_id: number;
  size: string;
  color: string;
  photo_url: string;
  quantity_per_piece: NumberInputValue;
  unit: string;
  waste_percent: NumberInputValue;
};
type ModelFormState = {
  code: string;
  model_no: string;
  variant_no: string;
  name: string;
  category: string;
  description: string;
  brand_id: number;
  collection_id: number;
  product_type: string;
  season: string;
  constructor_employee_id: number;
  designer_employee_id: number;
  status: string;
  sam_minutes: NumberInputValue;
};
type FabricVariant = {
  id: number;
  model_id?: number;
  code?: string | null;
  variant_no?: string | null;
  fabric?: string | null;
  picture_url?: string | null;
  fabric_item_id?: number | null;
  color?: string | null;
};

const MODEL_SIZE_OPTIONS = GARMENT_SIZE_OPTIONS;

const TAB_KEYS = [
  "page.modelDetail.tab.general",
  "page.modelDetail.tab.composition",
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

function normalizeSizeToken(value: unknown): string {
  return String(value || "").trim().toLowerCase();
}

function emptyBomRow(): BomFormState {
  return { item_id: 0, material_name: "", material_role: "main", stock_batch_id: 0, size: "", color: "", photo_url: "", quantity_per_piece: 1, unit: "kg", waste_percent: 5 };
}

export default function ModelDetail() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { t, lang } = useT();
  const dialogs = useDialogs();
  const { me } = useMe();
  const isUsluga = pathname.startsWith("/usluga/models");
  const modelApiBase = isUsluga ? "/api/usluga/models" : "/api/models";
  const modelPageBase = isUsluga ? "/usluga/models" : "/models";
  const visiblePaidOperationFactories = useMemo<PaidOperationFactory[]>(() => {
    if (isUsluga) return ["eco_cotton"];
    const scopedFactory = (me?.role || "").trim().toLowerCase().includes("sewing") && !me?.permissions.includes("*")
      ? paidOperationFactoryFromDepartmentCode(me?.department_code)
      : undefined;
    return scopedFactory ? [scopedFactory] : [...PAID_OPERATION_FACTORIES];
  }, [isUsluga, me?.department_code, me?.permissions, me?.role]);
  const isNewModel = String(id || "") === "new";
  const isEditable = isNewModel || searchParams.get("mode") === "edit";
  const isNumericId = /^\d+$/.test(String(id || ""));
  const { data: loadedModel, error: modelError, isLoading: modelLoading, mutate } = useSWR<any>(isNumericId ? `${modelApiBase}/${id}` : null, fetcher);
  const {
    data: variantPages,
    mutate: mutateVariants,
    size: variantPageCount,
    setSize: setVariantPageCount,
    isValidating: variantsLoading,
  } = useSWRInfinite<any[]>(
    (pageIndex, previousPage) => {
      if (!isNumericId) return null;
      if (previousPage && previousPage.length < 50) return null;
      return `${modelApiBase}/${id}/variants?page=${pageIndex + 1}&page_size=50`;
    },
    fetcher,
  );
  const { data: items } = useSWR<any[]>(`${modelApiBase}/bom-items`, fetcher);
  const { data: brands } = useSWR<any[]>("/api/brands", fetcher);
  const { data: seasons } = useSWR<string[]>("/api/collections/seasons", fetcher);
  const { data: employees } = useSWR<any[]>("/api/employees", fetcher);
  const { data: depts } = useSWR<any[]>("/api/departments", fetcher);
  const tabs = TAB_KEYS.map((k) => t(k));

  const [tab, setTab] = useState(1);
  const [msg, setMsg] = useState("");
  const [isCloning, setIsCloning] = useState(false);
  const [showVariantForm, setShowVariantForm] = useState(false);
  const [loadingVariantNumber, setLoadingVariantNumber] = useState(false);
  const [savingVariant, setSavingVariant] = useState(false);
  const [editingVariantId, setEditingVariantId] = useState<number | null>(null);
  const [deletingVariantId, setDeletingVariantId] = useState<number | null>(null);
  const [variantForm, setVariantForm] = useState({ variant_no: "", color: "", picture_url: "" });
  const [suggestedVariantNo, setSuggestedVariantNo] = useState("");
  const [variantPictureFile, setVariantPictureFile] = useState<File | null>(null);

  const [modelForm, setModelForm] = useState<ModelFormState>({
    code: "",
    model_no: "",
    variant_no: "",
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
    sam_minutes: "",
  });
  const [details, setDetails] = useState<ModelDetails>({});

  const [bomRow, setBomRow] = useState<BomFormState>(() => emptyBomRow());
  const [editingBom, setEditingBom] = useState<{ id: number; section: BomSection } | null>(null);
  const [size, setSize] = useState({ size: "", measurement_json: "" });
  const [modelSizeFrom, setModelSizeFrom] = useState("46");
  const [modelSizeTo, setModelSizeTo] = useState("56");
  const [generatingSizeRange, setGeneratingSizeRange] = useState(false);
  const [measurementFields, setMeasurementFields] = useState({ chest: "", waist: "", hip: "", length: "", sleeve: "" });
  const [imageForms, setImageForms] = useState<Record<ImageUploadType, { file_url: string }>>({
    model: { file_url: "" },
    pattern: { file_url: "" },
  });
  const [imageFiles, setImageFiles] = useState<Record<ImageUploadType, File | null>>({
    model: null,
    pattern: null,
  });
  const [uploadingImageType, setUploadingImageType] = useState<ImageUploadType | null>(null);
  const blankModel = useMemo(() => ({
    id: 0,
    code: "",
    name: "",
    category: "",
    description: "",
    status: "draft",
    sam_minutes: "",
    details_json: { paid_operations: [] },
    images: [],
    sizes: [],
    colors: [],
    bom: [],
    created_at: new Date().toISOString(),
  }), []);
  const m = isNewModel ? blankModel : loadedModel;

  useEffect(() => {
    if (!m) return;
    const codeParts = modelCodeParts(m);
    setModelForm({
      code: m.code ?? "",
      model_no: codeParts.modelNo,
      variant_no: codeParts.variantNo,
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
      sam_minutes: m.sam_minutes === "" ? "" : n(m.sam_minutes),
    });
    const nextDetails: ModelDetails = { ...(m.details_json || {}) };
    if (!nextDetails.translation?.ru) {
      nextDetails.translation = { ...(nextDetails.translation || {}), ru: m.name ?? "" };
    }
    const existingQolipNo = String(
      nextDetails.general?.qolip_no
        ?? nextDetails.general?.qolipNo
        ?? nextDetails.general?.mold_no
        ?? nextDetails.general?.moldNo
        ?? nextDetails.general?.pattern_no
        ?? nextDetails.general?.patternNo
        ?? "",
    ).trim();
    if (existingQolipNo) {
      nextDetails.general = {
        ...(nextDetails.general || {}),
        qolip_no: existingQolipNo,
        mold_no: existingQolipNo,
      };
    }
    nextDetails.paid_operations = serializePaidOperations(materializeLegacyPaidOperations(
      withoutModelQuantities(paidOperationsFromDetails(nextDetails)),
      visiblePaidOperationFactories,
    ));
    delete nextDetails.paidOperations;
    setDetails(nextDetails);
  }, [m, visiblePaidOperationFactories]);

  const measurementJson = useMemo(() => buildMeasurementJson(measurementFields), [measurementFields]);

  useEffect(() => {
    setSize((prev) => ({ ...prev, measurement_json: JSON.stringify(measurementJson) }));
  }, [measurementJson]);

  const itemMap = useMemo(() => {
    const map = new Map<number, any>();
    for (const i of items || []) map.set(i.id, i);
    return map;
  }, [items]);
  const materialItems = useMemo(() => {
    return (items || [])
      .filter((item: any) => item.is_active !== false)
      .filter((item: any) => ["fabric", "semi_finished"].includes(String(item.category || "").toLowerCase()));
  }, [items]);
  const materialBomOptions = useMemo(() => {
    return materialItems
      .map((item: any) => ({
        value: Number(item.id),
        item_id: Number(item.id),
        label: String(item.name || item.sku || ""),
        searchText: String(item.sku || ""),
        unit: item.unit || "kg",
      }))
      .sort((a, b) => a.label.localeCompare(b.label));
  }, [materialItems]);
  const selectedVariantPictureUrl = variantForm.picture_url || "";
  const accessoryItems = useMemo(() => {
    return (items || []).filter((item: any) => ["accessory", "packaging"].includes(String(item.category || "").toLowerCase()));
  }, [items]);
  const selectedMaterialBomValue = bomRow.item_id || null;

  function selectMaterialBomOption(value: number) {
    const option = materialBomOptions.find((row) => row.value === Number(value));
    if (!option) {
      setBomRow({ ...bomRow, item_id: 0, stock_batch_id: 0, color: "", photo_url: "" });
      return;
    }
    setBomRow({
      ...bomRow,
      item_id: option.item_id,
      stock_batch_id: 0,
      unit: option.unit || bomRow.unit,
      photo_url: "",
    });
  }

  function resetBomForm() {
    setBomRow(emptyBomRow());
    setEditingBom(null);
  }

  function editBom(row: any, section: BomSection) {
    setEditingBom({ id: Number(row.id), section });
    setBomRow({
      item_id: isUsluga && section === "material" ? 0 : Number(row.item_id || 0),
      material_name: isUsluga && section === "material" ? String(row.material_name || row.item?.name || "") : "",
      material_role: isUsluga && section === "material" && row.material_role === "secondary" ? "secondary" : "main",
      stock_batch_id: section === "material" ? 0 : Number(row.stock_batch_id || 0),
      size: row.size || "",
      color: row.color || "",
      photo_url: bomPhotoUrl(row),
      quantity_per_piece: n(row.quantity_per_piece) || 1,
      unit: row.unit || row.item?.unit || "kg",
      waste_percent: n(row.waste_percent),
    });
  }

  function bomPhotoUrl(row: any) {
    return row.photo_url || row.item?.image_url || row.stock_batch_image_url || "";
  }

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

  const variants = useMemo<FabricVariant[]>(() => {
    const byId = new Map<number, FabricVariant>();
    for (const page of variantPages || []) {
      for (const variant of page || []) byId.set(Number(variant.model_id || variant.id), variant);
    }
    return Array.from(byId.values());
  }, [variantPages]);
  const variantsHaveMore = Boolean(variantPages?.length && variantPages[variantPages.length - 1]?.length === 50);
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
  const brandOptions = useMemo(() => [
    { value: 0, label: t("ph.brand") },
    ...(brands || []).map((brand: any) => ({ value: Number(brand.id), label: String(brand.name || `#${brand.id}`) })),
  ], [brands, t]);
  const seasonOptions = useMemo(() => [
    { value: "", label: "-" },
    ...(seasons || []).map((season) => ({ value: season, label: season })),
  ], [seasons]);
  const modelingEmployeeOptions = useMemo(() => [
    { value: 0, label: "-" },
    ...modelingEmployees.map((employee: any) => ({
      value: Number(employee.id),
      label: String(employee.full_name || `#${employee.id}`),
      searchText: [employee.position, employee.employee_no, employee.department_name].filter(Boolean).join(" "),
    })),
  ], [modelingEmployees]);
  const accessoryItemOptions = useMemo(() => accessoryItems.map((item: any) => ({
    value: Number(item.id),
    label: `${item.sku} - ${item.name} (${item.category})`,
  })), [accessoryItems]);
  const sizeRows = m?.sizes || [];
  const colorRows = m?.colors || [];
  const primaryImage = (m?.images || []).find((img: any) => img.is_primary && img.image_type === "model")
    || (m?.images || []).find((img: any) => img.is_primary)
    || (m?.images || []).find((img: any) => img.image_type === "model")
    || (m?.images || [])[0];
  const translatedName = details.translation?.[lang] || (lang === "ru" ? details.translation?.ru : "") || m?.name || "";
  const qolipNoValue = String(
    details.general?.qolip_no
      ?? details.general?.qolipNo
      ?? details.general?.mold_no
      ?? details.general?.moldNo
      ?? details.general?.pattern_no
      ?? details.general?.patternNo
      ?? "",
  ).trim();
  const patternFiles = useMemo(
    () => (m?.images || []).filter((img: any) => String(img.image_type || "").toLowerCase() === "pattern"),
    [m?.images],
  );
  const paidOperations = useMemo(() => withoutModelQuantities(paidOperationsFromDetails(details)), [details]);
  const modelCompositionRows = useMemo(
    () => (details.composition || []).length ? details.composition || [] : [{ name: "", percentage: "" }],
    [details.composition],
  );
  const modelCompositionTotal = compositionTotal(details.composition);
  const modelCompositionOverLimit = modelCompositionTotal > 100.0001;
  const modelCompositionText = formatModelComposition({ details_json: details, material_composition: m?.material_composition });
  const oldErpModelInfo = useMemo(() => oldErpModelInfoFromDetails(details), [details]);
  const oldErpGeneralRows = oldErpModelInfo.general
    ? [
        [t("page.modelDetail.oldErpSourceDate"), oldErpModelInfo.general.sourceDate],
        [t("page.modelDetail.oldErpOriginalName"), oldErpModelInfo.general.originalName],
        [t("page.modelDetail.oldErpProduct"), oldErpModelInfo.general.product],
        [t("page.modelDetail.oldErpStyle"), oldErpModelInfo.general.style],
        [t("page.modelDetail.oldErpCompany"), oldErpModelInfo.general.company],
        [t("page.modelDetail.oldErpPlanningType"), oldErpModelInfo.general.planningType],
        [t("page.modelDetail.oldErpParentSewModel"), oldErpModelInfo.general.parentSewModel],
        [t("page.modelDetail.oldErpEmbroidery"), oldErpModelInfo.general.embroidery],
        [t("page.modelDetail.oldErpThermalPrint"), oldErpModelInfo.general.thermalPrint],
      ] as const
    : [];

  function oldErpDisplayValue(value: string | boolean | null): string {
    if (typeof value === "boolean") return t(value ? "field.yes" : "field.no");
    return value || "-";
  }

  if (!isNewModel && !isNumericId) {
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
  if (!isNewModel && (modelLoading || !m)) return <div className="card p-4 text-sm text-slate-500">{t("common.loading")}</div>;

  function updatePaidOperation(id: string, patch: Partial<PaidOperation>) {
    setDetails((current) => {
      const rows = withoutModelQuantities(paidOperationsFromDetails(current)).map((operation) => (
        operation.id === id ? { ...operation, ...patch } : operation
      ));
      return withPaidOperations(current, rows);
    });
  }

  function addPaidOperation(sewingFactory: PaidOperationFactory) {
    setDetails((current) => {
      const rows = [
        ...withoutModelQuantities(paidOperationsFromDetails(current)),
        createPaidOperation("model-op", 0, sewingFactory),
      ];
      return withPaidOperations(current, rows);
    });
  }

  function removePaidOperation(id: string) {
    setDetails((current) => {
      const rows = withoutModelQuantities(paidOperationsFromDetails(current));
      return withPaidOperations(current, rows.filter((operation) => operation.id !== id));
    });
  }

  function updateModelCompositionRow(index: number, patch: Partial<MaterialComposition>) {
    const rows = modelCompositionRows.map((row, rowIndex) => rowIndex === index ? { ...row, ...patch } : row);
    setDetails((current) => ({ ...current, composition: rows }));
  }

  function addModelCompositionRow() {
    setDetails((current) => ({ ...current, composition: [...modelCompositionRows, { name: "", percentage: "" }] }));
  }

  function removeModelCompositionRow(index: number) {
    const rows = modelCompositionRows.filter((_, rowIndex) => rowIndex !== index);
    setDetails((current) => ({ ...current, composition: rows.length ? rows : [{ name: "", percentage: "" }] }));
  }

  function updateQolipNo(value: string) {
    setDetails((current) => ({
      ...current,
      general: {
        ...(current.general || {}),
        qolip_no: value,
        mold_no: value,
      },
    }));
  }

  async function saveModel() {
    const selectedBrand = (brands || []).find((b) => Number(b.id) === Number(modelForm.brand_id));
    const constructor = (employees || []).find((e) => Number(e.id) === Number(modelForm.constructor_employee_id));
    const designer = (employees || []).find((e) => Number(e.id) === Number(modelForm.designer_employee_id));
    const nextCode = buildModelCode(modelForm.model_no, modelForm.variant_no) || modelForm.code;
    if (!nextCode || !modelForm.name.trim()) {
      await dialogs.notify(t("page.modelDetail.modelNoNameRequired"));
      return;
    }
    const normalizedComposition = (details.composition || [])
      .map((row) => ({ name: String(row.name || "").trim(), percentage: n(row.percentage) }))
      .filter((row) => row.name && row.percentage > 0);
    if (compositionTotal(normalizedComposition) > 100.0001) {
      await dialogs.notify(t("page.modelDetail.compositionOverLimit"));
      setTab(2);
      return;
    }
    const normalizedQolipNo = String(
      details.general?.qolip_no
        ?? details.general?.qolipNo
        ?? details.general?.mold_no
        ?? details.general?.moldNo
        ?? details.general?.pattern_no
        ?? details.general?.patternNo
        ?? "",
    ).trim();
    const normalizedVariantNo = modelForm.variant_no.trim();
    const normalizedGeneral = {
      ...details.general,
      model_no: modelForm.model_no.trim(),
      variant_no: normalizedVariantNo || undefined,
      brand: selectedBrand?.name || "",
      brand_id: modelForm.brand_id || undefined,
      product_type: modelForm.product_type || "",
      season: modelForm.season || "",
      constructor: constructor?.full_name || "",
      constructor_employee_id: modelForm.constructor_employee_id || undefined,
      designer: designer?.full_name || "",
      designer_employee_id: modelForm.designer_employee_id || undefined,
      qolip_no: normalizedQolipNo,
      mold_no: normalizedQolipNo,
    };
    if (!normalizedVariantNo) {
      delete normalizedGeneral.variant_no;
      delete (normalizedGeneral as Record<string, unknown>).variantNo;
    }
    const normalizedDetails: ModelDetails = {
      ...details,
      composition: normalizedComposition,
      general: normalizedGeneral,
      sewing: details.sewing
        ? {
            ...details.sewing,
            one_person_norm: details.sewing.one_person_norm === "" ? undefined : n(details.sewing.one_person_norm),
          }
        : details.sewing,
      costing: details.costing
        ? {
            ...details.costing,
            labor_pct: details.costing.labor_pct === "" ? 0 : n(details.costing.labor_pct ?? 12),
            electricity_pct: details.costing.electricity_pct === "" ? 0 : n(details.costing.electricity_pct ?? 4),
            other_pct: details.costing.other_pct === "" ? 0 : n(details.costing.other_pct ?? 3),
            target_margin_pct: details.costing.target_margin_pct === "" ? 0 : n(details.costing.target_margin_pct ?? 20),
          }
        : details.costing,
      translation: {
        ...(details.translation || {}),
        ru: details.translation?.ru || modelForm.name,
      },
      paid_operations: serializePaidOperations(withoutModelQuantities(paidOperations)),
    };
    const payload = {
      code: nextCode,
      name: modelForm.name,
      category: modelForm.category || null,
      description: modelForm.description || null,
      brand_id: modelForm.brand_id || null,
      collection_id: modelForm.collection_id || null,
      product_type: modelForm.product_type || null,
      season: modelForm.season || null,
      constructor_employee_id: modelForm.constructor_employee_id || null,
      designer_employee_id: modelForm.designer_employee_id || null,
      details_json: normalizedDetails,
      status: modelForm.status,
      sam_minutes: n(modelForm.sam_minutes),
    };
    if (isNewModel) {
      const created = await api.post<any>(modelApiBase, payload);
      setDetails(normalizedDetails);
      router.replace(`${modelPageBase}/${created.id}?mode=edit`);
      return;
    }
    await api.patch(`${modelApiBase}/${id}`, payload);
    setModelForm((current) => ({ ...current, code: nextCode }));
    setDetails(normalizedDetails);
    setMsg(t("msg.saved"));
    mutate();
    mutateVariants();
  }

  async function cloneModel() {
    if (isNewModel) return;
    setIsCloning(true);
    try {
      const cloned = await api.post<any>(`${modelApiBase}/${id}/clone`);
      router.push(`${modelPageBase}/${cloned.id}?mode=edit`);
    } catch (e: any) {
      await dialogs.notify(e.message);
    } finally {
      setIsCloning(false);
    }
  }

  function resetVariantForm() {
    setVariantForm({ variant_no: "", color: "", picture_url: "" });
    setSuggestedVariantNo("");
    setVariantPictureFile(null);
    setEditingVariantId(null);
    setShowVariantForm(false);
  }

  async function openNewVariantForm() {
    if (isNewModel) {
      await dialogs.notify(t("page.modelDetail.saveGeneralFirst"));
      setTab(1);
      return;
    }
    setLoadingVariantNumber(true);
    try {
      const next = await api.get<{ variant_no: string }>(`${modelApiBase}/${id}/variants/next-number`);
      const nextVariantNo = String(next.variant_no || "").trim();
      setVariantForm({
        variant_no: nextVariantNo,
        color: "",
        picture_url: "",
      });
      setSuggestedVariantNo(nextVariantNo);
      setVariantPictureFile(null);
      setEditingVariantId(null);
      setShowVariantForm(true);
    } catch (e: any) {
      await dialogs.notify(e.message);
    } finally {
      setLoadingVariantNumber(false);
    }
  }

  function startEditVariant(variant: FabricVariant) {
    const variantId = Number(variant.model_id || variant.id || 0);
    if (!variantId) return;
    setSuggestedVariantNo("");
    setVariantForm({
      variant_no: String(variant.variant_no || "").trim(),
      color: String(variant.color || "").trim(),
      picture_url: String(variant.picture_url || ""),
    });
    setVariantPictureFile(null);
    setEditingVariantId(variantId);
    setShowVariantForm(true);
  }

  async function submitVariant(e: React.FormEvent) {
    e.preventDefault();
    if (isNewModel) {
      await dialogs.notify(t("page.modelDetail.saveGeneralFirst"));
      setTab(1);
      return;
    }
    const variantNo = variantForm.variant_no.trim();
    if (!variantNo) {
      await dialogs.notify(t("page.modelDetail.variantRequired"));
      return;
    }
    setSavingVariant(true);
    try {
      let createdVariantId: number | null = null;
      let uploadedPictureUrl = "";
      if (variantPictureFile) {
        const form = new FormData();
        form.append("file", variantPictureFile);
        const uploadModelId = editingVariantId || Number(id);
        const uploaded = await api.postForm<{ file_url: string }>(`${modelApiBase}/${uploadModelId}/bom-photo/upload`, form);
        uploadedPictureUrl = String(uploaded.file_url || "").trim();
      }
      const payload: { variant_no?: string; color?: string; picture_url?: string } = {};
      const useAutomaticVariantNumber = !editingVariantId && variantNo === suggestedVariantNo;
      if (!useAutomaticVariantNumber) payload.variant_no = variantNo;
      if (variantForm.color.trim()) payload.color = variantForm.color.trim();
      if (uploadedPictureUrl) payload.picture_url = uploadedPictureUrl;
      if (editingVariantId) {
        await api.patch(`${modelApiBase}/${id}/variants/${editingVariantId}`, payload);
      } else {
        const created = await api.post<{ id: number }>(`${modelApiBase}/${id}/variants`, payload);
        createdVariantId = Number(created.id || 0) || null;
      }
      const wasEditing = Boolean(editingVariantId);
      const editedCurrentModel = editingVariantId === Number(id);
      resetVariantForm();
      setMsg(wasEditing ? t("page.modelDetail.variantUpdated") : t("page.modelDetail.variantCreated"));
      mutateVariants();
      if (!wasEditing && isUsluga && createdVariantId) {
        router.push(`${modelPageBase}/${createdVariantId}?mode=edit`);
        return;
      }
      // Creating or editing a sibling changes only the bounded variant table.
      // Reload the much larger model detail payload only when this page's own
      // variant identity was edited.
      if (editedCurrentModel) mutate();
    } catch (e: any) {
      await dialogs.notify(e.message);
    } finally {
      setSavingVariant(false);
    }
  }

  async function deleteVariant(variant: FabricVariant) {
    const variantId = Number(variant.model_id || variant.id || 0);
    if (!variantId) return;
    if (!(await dialogs.ask({ message: t("page.modelDetail.deleteVariantConfirm"), tone: "danger" }))) return;
    setDeletingVariantId(variantId);
    try {
      await api.del(`${modelApiBase}/${id}/variants/${variantId}`);
      if (editingVariantId === variantId) resetVariantForm();
      setMsg(t("page.modelDetail.variantDeleted"));
      if (Number(id) === variantId) {
        router.push("/models");
        return;
      }
      mutateVariants();
      mutate();
    } catch (e: any) {
      await dialogs.notify(e.message);
    } finally {
      setDeletingVariantId(null);
    }
  }

  async function addBom(e?: { preventDefault?: () => void }, expectedCategory?: BomSection) {
    e?.preventDefault?.();
    if (isNewModel) {
      await dialogs.notify(t("page.modelDetail.saveGeneralFirst"));
      setTab(1);
      return;
    }
    const target: BomSection = expectedCategory || "material";
    const isManualUslugaMaterial = isUsluga && target === "material";
    if (isManualUslugaMaterial) {
      if (!bomRow.material_name.trim()) {
        await dialogs.notify(t("page.modelDetail.alert.enterFabricName"));
        return;
      }
    } else {
      const item = itemMap.get(bomRow.item_id);
      const category = String(item?.category || "").toLowerCase();
      if (!bomRow.item_id) {
        await dialogs.notify(t("page.modelDetail.alert.pickItemFirst"));
        return;
      }
      if (target === "material" && !["fabric", "semi_finished"].includes(category)) {
        await dialogs.notify(t("page.modelDetail.alert.materialItemType"));
        return;
      }
      if (target === "accessory" && !["accessory", "packaging"].includes(category)) {
        await dialogs.notify(t("page.modelDetail.alert.accessoryItemType"));
        return;
      }
    }
    const payload: Record<string, unknown> = {
      item_id: isManualUslugaMaterial ? null : bomRow.item_id,
      stock_batch_id: target === "material" ? null : (bomRow.stock_batch_id || null),
      size: bomRow.size || null,
      color: bomRow.color || null,
      photo_url: target === "material" ? null : (bomRow.photo_url || null),
      quantity_per_piece: n(bomRow.quantity_per_piece),
      unit: bomRow.unit,
      waste_percent: n(bomRow.waste_percent),
    };
    if (isManualUslugaMaterial) payload.material_name = bomRow.material_name.trim();
    if (isManualUslugaMaterial) payload.material_role = bomRow.material_role;
    const activeEdit = editingBom?.section === target ? editingBom : null;
    if (activeEdit) {
      await api.patch(`${modelApiBase}/${id}/bom/${activeEdit.id}`, payload);
    } else {
      await api.post(`${modelApiBase}/${id}/bom`, payload);
    }
    resetBomForm();
    setMsg(activeEdit ? t("page.modelDetail.msg.updatedBom") : target === "material" ? t("page.modelDetail.msg.addedToFabrics") : t("page.modelDetail.msg.addedToAccessories"));
    mutate();
    mutateVariants();
  }

  async function addSize(e: React.FormEvent) {
    e.preventDefault();
    if (isNewModel) {
      await dialogs.notify(t("page.modelDetail.saveGeneralFirst"));
      setTab(1);
      return;
    }
    await api.post(`${modelApiBase}/${id}/sizes`, {
      size: size.size,
      measurement_json: Object.keys(measurementJson).length ? measurementJson : null,
    });
    setSize({ size: "", measurement_json: "" });
    setMeasurementFields({ chest: "", waist: "", hip: "", length: "", sleeve: "" });
    mutate();
    mutateVariants();
  }

  async function generateModelSizeRange() {
    if (isNewModel) {
      await dialogs.notify(t("page.modelDetail.saveGeneralFirst"));
      setTab(1);
      return;
    }
    const startIdx = MODEL_SIZE_OPTIONS.indexOf(modelSizeFrom);
    const endIdx = MODEL_SIZE_OPTIONS.indexOf(modelSizeTo);
    if (startIdx < 0 || endIdx < 0 || startIdx > endIdx) {
      await dialogs.notify(t("newso.invalidSizeRange"));
      return;
    }

    const selectedSizes = MODEL_SIZE_OPTIONS.slice(startIdx, endIdx + 1);
    const existingSizes = new Set(sizeRows.map((row: any) => normalizeSizeToken(row.size)));
    const missingSizes = selectedSizes.filter((value) => !existingSizes.has(normalizeSizeToken(value)));
    const collapsedRange = `${modelSizeFrom}-${modelSizeTo}`;
    const collapsedRows = sizeRows.filter((row: any) => (
      normalizeSizeToken(row.size).replace(/[\u2013\u2014]/g, "-") === normalizeSizeToken(collapsedRange)
    ));
    if (!missingSizes.length && !collapsedRows.length) {
      setMsg(t("page.modelDetail.sizeRangeAlreadyExists"));
      return;
    }

    setGeneratingSizeRange(true);
    try {
      await Promise.all(
        [
          ...missingSizes.map((value) => api.post(`${modelApiBase}/${id}/sizes`, {
            size: value,
            measurement_json: null,
          })),
          ...collapsedRows.map((row: any) => api.del(`${modelApiBase}/${id}/sizes/${row.id}`)),
        ],
      );
      setMsg(t("page.modelDetail.sizeRangeAdded", {
        count: missingSizes.length,
        from: selectedSizes[0],
        to: selectedSizes[selectedSizes.length - 1],
      }));
      mutate();
      mutateVariants();
    } catch (e: any) {
      await dialogs.notify(e.message);
    } finally {
      setGeneratingSizeRange(false);
    }
  }

  async function addImage(e: React.FormEvent, imageType: ImageUploadType) {
    e.preventDefault();
    if (isNewModel) {
      await dialogs.notify(t("page.modelDetail.saveGeneralFirst"));
      setTab(1);
      return;
    }
    const imageFile = imageFiles[imageType];
    const imageForm = imageForms[imageType];
    if (imageFile) {
      setUploadingImageType(imageType);
      try {
        const uploadFile = imageType === "model" ? await prepareModelImageUpload(imageFile) : imageFile;
        const form = new FormData();
        form.append("file", uploadFile);
        form.append("image_type", imageType);
        await api.postForm(`${modelApiBase}/${id}/images/upload`, form);
        setImageFiles((prev) => ({ ...prev, [imageType]: null }));
        setImageForms((prev) => ({ ...prev, [imageType]: { file_url: "" } }));
        await Promise.all([mutate(), mutateVariants()]);
      } catch (error: any) {
        await dialogs.notify(String(error?.message || "Image upload failed"));
      } finally {
        setUploadingImageType(null);
      }
      return;
    }
    if (!imageForm.file_url.trim()) return;
    await api.post(`${modelApiBase}/${id}/images`, {
      file_url: imageForm.file_url,
      image_type: imageType,
      is_primary: imageType === "model",
    });
    setImageForms((prev) => ({ ...prev, [imageType]: { file_url: "" } }));
    mutate();
    mutateVariants();
  }

  async function deleteImage(imageId: number) {
    if (!(await dialogs.ask({ message: t("page.modelDetail.deletePatternConfirm"), tone: "danger" }))) return;
    await api.del(`${modelApiBase}/${id}/images/${imageId}`);
    mutate();
    mutateVariants();
  }

  async function deleteSize(sizeId: number) {
    if (!(await dialogs.ask({ message: t("page.modelDetail.deleteSizeConfirm"), tone: "danger" }))) return;
    await api.del(`${modelApiBase}/${id}/sizes/${sizeId}`);
    mutate();
    mutateVariants();
  }

  async function deleteBom(row: any) {
    if (!(await dialogs.ask({ message: t("page.modelDetail.deleteBomConfirm"), tone: "danger" }))) return;
    await api.del(`${modelApiBase}/${id}/bom/${row.id}`);
    if (editingBom?.id === Number(row.id)) resetBomForm();
    setMsg(t("page.modelDetail.msg.deletedBom"));
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
    if (type === "model") return t("page.modelDetail.attachModelPicture");
    return t("page.modelDetail.attachQolipFile");
  }

  function imageUploadForm(imageType: ImageUploadType) {
    const imageFile = imageFiles[imageType];
    const imageForm = imageForms[imageType];
    const isUploading = uploadingImageType === imageType;
    return (
      <form
        onSubmit={(e) => addImage(e, imageType)}
        className="rounded-md border border-[#ecebe3] bg-[#fdfcf8] p-3"
      >
        <div className="mb-2 text-sm font-semibold text-[#14110b]">{uploadOptionTitle(imageType)}</div>
        <div className="grid grid-cols-1 gap-2 md:grid-cols-[minmax(0,1fr)_minmax(180px,0.55fr)_auto]">
          <input
            className="input"
            type="file"
            accept={imageType === "model" ? "image/png,image/jpeg,image/webp,image/gif" : "image/png,image/jpeg,image/webp,image/gif,.pdf,.dxf,.ai"}
            onChange={(e) => setImageFiles((prev) => ({ ...prev, [imageType]: e.target.files?.[0] || null }))}
          />
          <input
            className="input"
            placeholder={imageType === "pattern" ? t("page.modelDetail.qolipUrl") : t("page.modelDetail.orImageUrl")}
            value={imageForm.file_url}
            onChange={(e) => setImageForms((prev) => ({ ...prev, [imageType]: { file_url: e.target.value } }))}
          />
          <button className="btn btn-primary" disabled={isUploading || (!imageFile && !imageForm.file_url.trim())}>
            {isUploading ? t("common.uploading") : uploadOptionTitle(imageType)}
          </button>
        </div>
      </form>
    );
  }

  function modelSizeRangeHelper() {
    return (
      <div className="rounded-md border border-[#ecebe3] bg-[#fdfcf8] p-3">
        <div className="mb-2 text-sm font-semibold text-[#14110b]">{t("page.modelDetail.sizeRangeHelper")}</div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-[140px_140px_auto] sm:items-end">
          <div>
            <label className="label">{t("newso.sizeFrom")}</label>
            <select className="input" value={modelSizeFrom} onChange={(e) => setModelSizeFrom(e.target.value)}>
              {MODEL_SIZE_OPTIONS.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </div>
          <div>
            <label className="label">{t("newso.sizeTo")}</label>
            <select className="input" value={modelSizeTo} onChange={(e) => setModelSizeTo(e.target.value)}>
              {MODEL_SIZE_OPTIONS.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </div>
          <button type="button" className="btn btn-primary" onClick={generateModelSizeRange} disabled={generatingSizeRange}>
            {generatingSizeRange ? t("common.saving") : t("page.modelDetail.generateSizeRange")}
          </button>
        </div>
      </div>
    );
  }

  const pageTitle = isNewModel
    ? t("page.modelDetail.createTitle")
    : isEditable
      ? t("page.modelDetail.editTitle", { code: m.code })
      : t("page.modelDetail.viewTitle", { code: m.code });
  const pageSubtitle = isNewModel
    ? t("page.modelDetail.createSubtitle")
    : t("page.modelDetail.subtitle", { name: translatedName, status: statusLabel(m.status, t) });

  return (
    <div>
      <PageHeader
        title={pageTitle}
        subtitle={pageSubtitle}
        actions={(
          <>
            <Link href={modelPageBase} className="btn">{isUsluga ? t("usluga.backToModels") : t("page.modelDetail.backToModels")}</Link>
            {!isNewModel && (
              <>
                <button type="button" className="btn" onClick={cloneModel} disabled={isCloning}>
                  {isCloning ? t("page.models.cloning") : t("btn.clone")}
                </button>
                {isEditable
                  ? <Link href={`${modelPageBase}/${id}`} className="btn">{t("btn.view")}</Link>
                  : <Link href={`${modelPageBase}/${id}?mode=edit`} className="btn btn-primary">{t("btn.edit")}</Link>}
              </>
            )}
          </>
        )}
      />
      {isUsluga && <div className="mb-4 border-y border-[#dedbd0] bg-[#fbfaf6] px-4 py-3 text-sm text-[#56503f]">{t("usluga.modelBoundary")}</div>}
      <div className="card p-4 space-y-4">
        <div className="flex flex-wrap gap-1 border-b border-[#ecebe3] pb-2">
          {tabs.map((label, i) => {
            const counts = [primaryImage ? 1 : 0, (details.composition || []).filter((row) => String(row.name || "").trim()).length, bomWithItem.length + oldErpModelInfo.recipes.length, variants.length, patternFiles.length + (qolipNoValue ? 1 : 0), 0, 0, sizeRows.length, 0, paidOperations.length, 0, 0];
            return tabButton(i + 1, label, counts[i] || 0);
          })}
        </div>

        <fieldset
          disabled={!isEditable}
          className={`space-y-4 ${!isEditable ? "[&_.input]:bg-[#f8f6ef] [&_.input]:text-[#56503f] [&_.input]:opacity-100" : ""}`}
        >

        {tab === 1 && (
          <div className="space-y-3">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div><label className="label">{t("field.modelNo")}</label><input className="input" value={modelForm.model_no} onChange={(e) => setModelForm({ ...modelForm, model_no: e.target.value })} /></div>
              <div><label className="label">{t("common.name")}</label><input className="input" value={modelForm.name} onChange={(e) => setModelForm({ ...modelForm, name: e.target.value })} /></div>
              <div><label className="label">{t("field.category")}</label><input className="input" value={modelForm.category} onChange={(e) => setModelForm({ ...modelForm, category: e.target.value })} /></div>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
              <div>
                <label className="label" htmlFor="model-brand">{t("field.brand")}</label>
                <SearchableSelect
                  inputId="model-brand"
                  value={modelForm.brand_id}
                  options={brandOptions}
                  onChange={(brandId) => setModelForm({ ...modelForm, brand_id: Number(brandId) })}
                  placeholder={t("ph.brand")}
                  noResultsText={t("page.search.noMatches")}
                />
              </div>
              <div>
                <label className="label">{t("field.type")}</label>
                <input
                  className="input"
                  value={modelForm.product_type}
                  onChange={(e) => setModelForm({ ...modelForm, product_type: e.target.value })}
                />
              </div>
              <div>
                <label className="label" htmlFor="model-season">{t("field.season")}</label>
                <SearchableSelect
                  inputId="model-season"
                  value={modelForm.season}
                  options={seasonOptions}
                  onChange={(season) => setModelForm({ ...modelForm, season: String(season) })}
                  placeholder={t("field.season")}
                  noResultsText={t("page.search.noMatches")}
                />
              </div>
              <div><label className="label">{t("field.samMinutes")}</label><input className="input" type="number" step="0.1" value={modelForm.sam_minutes} onChange={(e) => setModelForm({ ...modelForm, sam_minutes: parseNumberInput(e.target.value) })} /></div>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <label className="label" htmlFor="model-constructor">{t("page.modelDetail.constructor")}</label>
                <SearchableSelect
                  inputId="model-constructor"
                  value={modelForm.constructor_employee_id}
                  options={modelingEmployeeOptions}
                  onChange={(employeeId) => setModelForm({ ...modelForm, constructor_employee_id: Number(employeeId) })}
                  placeholder={t("page.modelDetail.constructor")}
                  noResultsText={t("page.search.noMatches")}
                />
              </div>
              <div>
                <label className="label" htmlFor="model-designer">{t("page.modelDetail.designer")}</label>
                <SearchableSelect
                  inputId="model-designer"
                  value={modelForm.designer_employee_id}
                  options={modelingEmployeeOptions}
                  onChange={(employeeId) => setModelForm({ ...modelForm, designer_employee_id: Number(employeeId) })}
                  placeholder={t("page.modelDetail.designer")}
                  noResultsText={t("page.search.noMatches")}
                />
              </div>
            </div>
            <div><label className="label">{t("field.description")}</label><textarea className="input min-h-24" value={modelForm.description} onChange={(e) => setModelForm({ ...modelForm, description: e.target.value })} /></div>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-[72px_minmax(0,1fr)] md:items-start">
              {primaryImage?.file_url ? (
                <a
                  href={imagePreviewHref(primaryImage.file_url, primaryImage.file_name || modelForm.name || t("field.picture"))}
                  target="_blank"
                  rel="noreferrer"
                  className="block w-[72px] overflow-hidden rounded-md border border-[#ded9ca] bg-white"
                >
                  <VerticalModelPhoto
                    src={storageThumbnailUrl(primaryImage.file_url, 320)}
                    alt={primaryImage.file_name || modelForm.name || t("field.picture")}
                    className="w-full"
                    width={120}
                    height={160}
                  />
                </a>
              ) : (
                <div className="flex aspect-[3/4] w-[72px] items-center justify-center rounded-md border border-dashed border-[#ded9ca] bg-[#f8f6ef] text-[10px] text-[#8a8472]">
                  {t("page.models.noPreview")}
                </div>
              )}
              {imageUploadForm("model")}
            </div>
            {oldErpModelInfo.general && (
              <section className="border-t border-[#ecebe3] pt-3">
                <h3 className="mb-2 font-semibold text-[#14110b]">{t("page.modelDetail.oldErpInformation")}</h3>
                <div className="overflow-x-auto">
                  <table className="table">
                    <tbody>
                      {oldErpGeneralRows.map(([label, value]) => (
                        <tr key={label}>
                          <th
                            scope="row"
                            className="w-52 whitespace-nowrap border-b border-[#ecebe3] px-3 py-3 text-left font-medium text-[#56503f] sm:px-4"
                          >
                            {label}
                          </th>
                          <td className="min-w-56 break-words">{oldErpDisplayValue(value)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}
          </div>
        )}

        {tab === 2 && (
          <div className="space-y-3">
            <div className={`text-sm ${modelCompositionOverLimit ? "text-red-700" : "text-[#56503f]"}`}>
              {t("page.modelDetail.compositionTotal", { total: Number(modelCompositionTotal.toFixed(2)) })}
            </div>
            <div className="overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>{t("page.modelDetail.compositionName")}</th>
                    <th className="w-36">%</th>
                    <th className="w-16"></th>
                  </tr>
                </thead>
                <tbody>
                  {modelCompositionRows.map((row, index) => (
                    <tr key={index}>
                      <td>
                        <input
                          className="input"
                          value={String(row.name || "")}
                          onChange={(e) => updateModelCompositionRow(index, { name: e.target.value })}
                        />
                      </td>
                      <td>
                        <input
                          className="input"
                          type="number"
                          min={0}
                          max={100}
                          step="0.01"
                          value={String(row.percentage || "")}
                          onChange={(e) => updateModelCompositionRow(index, { percentage: e.target.value })}
                        />
                      </td>
                      <td>
                        <button
                          type="button"
                          className="icon-btn"
                          onClick={() => removeModelCompositionRow(index)}
                          title={t("common.remove")}
                          aria-label={t("common.remove")}
                        >
                          <Trash2 />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <button type="button" className="btn" onClick={addModelCompositionRow}>
              <Plus className="h-4 w-4" />
              {t("page.modelDetail.addCompositionRow")}
            </button>
          </div>
        )}

        {tab === 3 && (
          <div className="space-y-5">
            <div>
              <div className="flex items-center justify-between mb-2">
                <h3 className="font-semibold">{t("page.modelDetail.fabrics")}</h3>
                <button className="btn btn-primary" type="button" onClick={resetBomForm}>+ {t("page.modelDetail.addToFabrics")}</button>
              </div>
              <div className="overflow-x-auto">
                <table className="table">
                <thead><tr><th>{t("common.name")}</th>{isUsluga && <th>{t("usluga.fabricRole")}</th>}<th>{t("field.composition")}</th><th>{t("page.modelDetail.sizeColor")}</th><th>{t("field.usage")}</th><th>{t("field.unitCost")}</th><th>{t("page.modelDetail.costPerPiece")}</th>{isEditable && <th className="text-right">{t("field.actions")}</th>}</tr></thead>
                <tbody>
                  {materialRows.map((r: any) => (
                    <tr key={r.id}>
                      <td>{r.material_name || r.item?.name || "-"}</td>
                      {isUsluga && <td>{r.material_role === "main" ? t("usluga.mainFabric") : t("usluga.secondaryFabric")}</td>}
                      <td className="max-w-[260px] text-xs text-[#56503f]">{formatComposition(r.item?.composition) || "-"}</td>
                      <td>{r.size || t("common.all")} / {r.color || t("common.all")}</td>
                      <td>{n(r.quantity_per_piece).toFixed(4)} {r.unit} (+{n(r.waste_percent).toFixed(1)}%)</td>
                      <td>${n(r.unitCost).toFixed(4)}</td>
                      <td>${n(r.costPerPiece).toFixed(4)}</td>
                      {isEditable && (
                        <td>
                          <div className="flex justify-end gap-2">
                            <button type="button" className="icon-btn" onClick={() => editBom(r, "material")} title={t("btn.edit")}>
                              <Edit3 />
                            </button>
                            <button type="button" className="icon-btn text-red-700" onClick={() => deleteBom(r)} title={t("btn.delete")}>
                              <Trash2 />
                            </button>
                          </div>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
                </table>
              </div>
              <form onSubmit={(e) => addBom(e, "material")} className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-[minmax(220px,2fr)_repeat(6,minmax(86px,1fr))_auto_auto]">
                {isUsluga ? (
                  <input
                    className="input"
                    value={bomRow.material_name}
                    onChange={(e) => setBomRow({ ...bomRow, material_name: e.target.value })}
                    placeholder={t("page.modelDetail.manualFabricName")}
                    maxLength={255}
                    required
                  />
                ) : (
                  <SearchableSelect
                    value={selectedMaterialBomValue || null}
                    options={materialBomOptions}
                    onChange={(optionValue) => selectMaterialBomOption(Number(optionValue))}
                    placeholder={t("page.modelDetail.selectItem")}
                    noResultsText={t("page.search.noMatches")}
                    required
                  />
                )}
                {isUsluga && (
                  <select
                    className="input"
                    value={bomRow.material_role}
                    onChange={(e) => setBomRow({ ...bomRow, material_role: e.target.value === "secondary" ? "secondary" : "main" })}
                  >
                    <option value="main">{t("usluga.mainFabric")}</option>
                    <option value="secondary">{t("usluga.secondaryFabric")}</option>
                  </select>
                )}
                <input className="input" placeholder={t("page.modelDetail.colorOptional")} value={bomRow.color} onChange={(e) => setBomRow({ ...bomRow, color: e.target.value })} />
                <input className="input" placeholder={t("page.modelDetail.sizeOptional")} value={bomRow.size} onChange={(e) => setBomRow({ ...bomRow, size: e.target.value })} />
                <input className="input" type="number" step="0.0001" placeholder={t("page.modelDetail.qtyPerPieceShort")} value={bomRow.quantity_per_piece} onChange={(e) => setBomRow({ ...bomRow, quantity_per_piece: parseNumberInput(e.target.value) })} required />
                <input className="input" placeholder={t("field.unit")} value={bomRow.unit} onChange={(e) => setBomRow({ ...bomRow, unit: e.target.value })} required />
                <input className="input" type="number" step="0.1" placeholder={t("page.modelDetail.wastePctShort")} value={bomRow.waste_percent} onChange={(e) => setBomRow({ ...bomRow, waste_percent: parseNumberInput(e.target.value) })} />
                <button className="btn btn-primary" type="submit">{editingBom?.section === "material" ? t("btn.save") : t("btn.add")}</button>
                {editingBom?.section === "material" && <button className="btn" type="button" onClick={resetBomForm}>{t("btn.cancel")}</button>}
              </form>
            </div>
            <div>
              <div className="flex items-center justify-between mb-2">
                <h3 className="font-semibold">{t("page.modelDetail.accessories")}</h3>
                <button className="btn" type="button" onClick={resetBomForm}>+ {t("page.modelDetail.addToAccessories")}</button>
              </div>
              <div className="overflow-x-auto">
                <table className="table">
                <thead><tr><th>{t("common.code")}</th><th>{t("common.name")}</th><th>{t("page.modelDetail.sizeColor")}</th><th>{t("field.usage")}</th><th>{t("field.unitCost")}</th><th>{t("page.modelDetail.costPerPiece")}</th>{isEditable && <th className="text-right">{t("field.actions")}</th>}</tr></thead>
                <tbody>
                  {accessoryRows.map((r: any) => (
                    <tr key={r.id}>
                      <td>{r.item?.sku || r.item_id}</td>
                      <td>{r.item?.name || "-"}</td>
                      <td>{r.size || t("common.all")} / {r.color || t("common.all")}</td>
                      <td>{n(r.quantity_per_piece).toFixed(4)} {r.unit} (+{n(r.waste_percent).toFixed(1)}%)</td>
                      <td>${n(r.unitCost).toFixed(4)}</td>
                      <td>${n(r.costPerPiece).toFixed(4)}</td>
                      {isEditable && (
                        <td>
                          <div className="flex justify-end gap-2">
                            <button type="button" className="icon-btn" onClick={() => editBom(r, "accessory")} title={t("btn.edit")}>
                              <Edit3 />
                            </button>
                            <button type="button" className="icon-btn text-red-700" onClick={() => deleteBom(r)} title={t("btn.delete")}>
                              <Trash2 />
                            </button>
                          </div>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
                </table>
              </div>
            </div>

            <form onSubmit={(e) => addBom(e, "accessory")} className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-[minmax(220px,2fr)_repeat(5,minmax(86px,1fr))_auto_auto]">
              <SearchableSelect
                value={bomRow.item_id || null}
                options={accessoryItemOptions}
                onChange={(itemId) => setBomRow({ ...bomRow, item_id: Number(itemId), stock_batch_id: 0, photo_url: "" })}
                placeholder={t("page.modelDetail.selectItem")}
                noResultsText={t("page.search.noMatches")}
                required
              />
              <input className="input" placeholder={t("page.modelDetail.colorOptional")} value={bomRow.color} onChange={(e) => setBomRow({ ...bomRow, color: e.target.value })} />
              <input className="input" placeholder={t("page.modelDetail.sizeOptional")} value={bomRow.size} onChange={(e) => setBomRow({ ...bomRow, size: e.target.value })} />
              <input className="input" type="number" step="0.0001" placeholder={t("page.modelDetail.qtyPerPieceShort")} value={bomRow.quantity_per_piece} onChange={(e) => setBomRow({ ...bomRow, quantity_per_piece: parseNumberInput(e.target.value) })} required />
              <input className="input" placeholder={t("field.unit")} value={bomRow.unit} onChange={(e) => setBomRow({ ...bomRow, unit: e.target.value })} required />
              <input className="input" type="number" step="0.1" placeholder={t("page.modelDetail.wastePctShort")} value={bomRow.waste_percent} onChange={(e) => setBomRow({ ...bomRow, waste_percent: parseNumberInput(e.target.value) })} />
              <button className="btn btn-primary" type="submit">{editingBom?.section === "accessory" ? t("btn.save") : t("btn.add")}</button>
              {editingBom?.section === "accessory" && <button className="btn" type="button" onClick={resetBomForm}>{t("btn.cancel")}</button>}
            </form>
            {oldErpModelInfo.recipes.length > 0 && (
              <section className="border-t border-[#ecebe3] pt-4">
                <h3 className="mb-2 font-semibold text-[#14110b]">{t("page.modelDetail.oldErpRecipe")}</h3>
                <div className="overflow-x-auto">
                  <table className="table">
                    <thead>
                      <tr>
                        <th className="w-20">{t("page.modelDetail.oldErpRecipeOrder")}</th>
                        <th>{t("page.modelDetail.oldErpProduct")}</th>
                        <th className="w-36">{t("page.modelDetail.oldErpRecipeQuantity")}</th>
                        <th>{t("page.modelDetail.oldErpRecipeSewingType")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {oldErpModelInfo.recipes.map((row, index) => (
                        <tr key={`${row.order}-${index}`}>
                          <td>{row.order}</td>
                          <td>{row.product || "-"}</td>
                          <td>{row.quantity || "-"}</td>
                          <td>{row.sewingTypeList || "-"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}
          </div>
        )}

        {tab === 4 && (
          <div className="space-y-3">
            {isEditable && (
              <div className="rounded-md border border-[#ecebe3] bg-[#fdfcf8] p-3">
                {showVariantForm ? (
                  <form onSubmit={submitVariant} className="grid grid-cols-1 gap-2 md:grid-cols-2 md:items-end xl:grid-cols-[150px_180px_minmax(220px,1fr)_64px_auto_auto]">
                    <div>
                      <label className="label">{t("field.variantNo")}</label>
                      <input
                        className="input"
                        value={variantForm.variant_no}
                        onChange={(e) => setVariantForm((prev) => ({ ...prev, variant_no: e.target.value }))}
                        placeholder="V-5648"
                      />
                    </div>
                    <div>
                      <label className="label" htmlFor="variant-material-color">{t("field.materialColor")}</label>
                      <select
                        id="variant-material-color"
                        className="input"
                        value={variantForm.color}
                        onChange={(event) => setVariantForm((prev) => ({ ...prev, color: event.target.value }))}
                      >
                        <option value="">{t("page.receiveStock.selectMaterialColor")}</option>
                        {MATERIAL_COLOR_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>{t(option.labelKey)}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="label" htmlFor="variant-material-picture">{t("page.modelDetail.variantMaterialPicture")}</label>
                      <input
                        id="variant-material-picture"
                        className="input text-sm"
                        type="file"
                        accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp"
                        onChange={(e) => setVariantPictureFile(e.target.files?.[0] || null)}
                      />
                    </div>
                    <div>
                      <label className="label">{t("field.picture")}</label>
                      {selectedVariantPictureUrl ? (
                        <a
                          href={imagePreviewHref(selectedVariantPictureUrl, variantForm.variant_no || t("field.picture"))}
                          target="_blank"
                          rel="noreferrer"
                          className="block h-10 w-10 overflow-hidden rounded-md border border-[#ded9ca] bg-white"
                        >
                          <img
                            src={storageThumbnailUrl(selectedVariantPictureUrl, 160)}
                            alt={variantForm.variant_no || t("field.picture")}
                            className="h-full w-full object-cover"
                          />
                        </a>
                      ) : (
                        <div className="flex h-10 w-10 items-center justify-center rounded-md border border-dashed border-[#ded9ca] bg-[#f8f6ef] text-[10px] text-[#8a8472]">
                          {t("page.models.noPreview")}
                        </div>
                      )}
                    </div>
                    <button className="btn btn-primary" type="submit" disabled={savingVariant}>
                      {savingVariant ? t("common.saving") : editingVariantId ? t("page.modelDetail.saveVariant") : t("page.modelDetail.createVariant")}
                    </button>
                    <button className="btn" type="button" onClick={resetVariantForm} disabled={savingVariant}>
                      {t("btn.cancel")}
                    </button>
                  </form>
                ) : (
                  <button
                    className="btn btn-primary"
                    type="button"
                    onClick={openNewVariantForm}
                    disabled={loadingVariantNumber}
                  >
                    <Plus className="h-4 w-4" />
                    <span>{loadingVariantNumber ? t("common.loading") : t("page.modelDetail.addVariant")}</span>
                  </button>
                )}
              </div>
            )}
            <div className="overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>{t("field.picture")}</th>
                    <th>{t("field.variantNo")}</th>
                    <th>{t("page.cuttingPassports.field.fabric")}</th>
                    {isEditable && <th className="text-right">{t("field.actions")}</th>}
                  </tr>
                </thead>
                <tbody>
                  {variants.map((v) => {
                    const imageUrl = storageThumbnailUrl(v.picture_url || "", 160);
                    const variantId = Number(v.model_id || v.id);
                    return (
                      <tr key={variantId || v.code}>
                        <td>
                          {imageUrl ? (
                            <a href={imagePreviewHref(v.picture_url, v.variant_no || v.code || "")} target="_blank" rel="noreferrer" className="block h-14 w-14 overflow-hidden rounded-md border border-[#ded9ca] bg-white">
                              <img src={imageUrl} alt={v.variant_no || v.code || t("field.picture")} className="h-full w-full object-cover" />
                            </a>
                          ) : (
                            <div className="flex h-14 w-14 items-center justify-center rounded-md border border-dashed border-[#ded9ca] bg-[#f8f6ef] text-[10px] text-[#8a8472]">
                              {t("page.models.noPreview")}
                            </div>
                          )}
                        </td>
                        <td>
                          {variantId ? (
                            <Link href={`${modelPageBase}/${variantId}`} className="font-medium text-brand-600 hover:underline">
                              {v.variant_no || v.code || "-"}
                            </Link>
                          ) : (
                            v.variant_no || v.code || "-"
                          )}
                        </td>
                        <td>{v.fabric || "-"}</td>
                        {isEditable && (
                          <td>
                            <div className="flex justify-end gap-2">
                              <button
                                type="button"
                                className="icon-btn"
                                onClick={() => startEditVariant(v)}
                                title={t("btn.edit")}
                                aria-label={t("btn.edit")}
                              >
                                <Edit3 />
                              </button>
                              <button
                                type="button"
                                className="icon-btn text-red-700"
                                onClick={() => deleteVariant(v)}
                                title={t("btn.delete")}
                                aria-label={t("btn.delete")}
                                disabled={deletingVariantId === variantId}
                              >
                                <Trash2 />
                              </button>
                            </div>
                          </td>
                        )}
                      </tr>
                    );
                  })}
                  {variants.length === 0 && (
                    <tr>
                      <td colSpan={isEditable ? 4 : 3} className="text-sm text-slate-500">{t("page.models.empty")}</td>
                    </tr>
                  )}
                </tbody>
              </table>
              {variantsHaveMore && (
                <div className="border-t border-[#ece8dc] p-3 text-center">
                  <button
                    type="button"
                    className="btn"
                    disabled={variantsLoading}
                    onClick={() => setVariantPageCount(variantPageCount + 1)}
                  >
                    {variantsLoading ? t("common.loading") : t("common.loadMore")}
                  </button>
                </div>
              )}
            </div>
          </div>
        )}

        {tab === 5 && (
          <div className="space-y-3">
            <div className="rounded-md border border-[#ecebe3] bg-[#fdfcf8] p-3">
              <label className="label">{t("page.modelDetail.qolipNo")}</label>
              <input
                className="input max-w-md"
                value={qolipNoValue}
                onChange={(e) => updateQolipNo(e.target.value)}
                placeholder="4220"
              />
            </div>
            {imageUploadForm("pattern")}
            <div className="overflow-x-auto">
              <table className="table">
              <thead><tr><th>{t("field.preview")}</th><th>{t("page.workOrder.imageType")}</th><th>{t("field.filename")}</th><th>{t("field.uploaded")}</th><th>{t("field.actions")}</th></tr></thead>
              <tbody>
                {patternFiles.map((img: any) => {
                  const name = img.file_name || String(img.file_url || "").split("/").pop() || `file-${img.id}`;
                  const isImage = String(img.content_type || "").startsWith("image/") || /\.(png|jpe?g|webp|gif)$/i.test(name);
                  return (
                    <tr key={img.id}>
                      <td>
                        {isImage ? (
                          <a href={imagePreviewHref(img.file_url, name)} target="_blank" rel="noreferrer" className="block h-14 w-14 overflow-hidden rounded">
                            <img src={storageThumbnailUrl(img.file_url, 160)} alt={name} className="h-full w-full object-cover" />
                          </a>
                        ) : (
                          <span className="badge">{t("page.modelDetail.file")}</span>
                        )}
                      </td>
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
                {patternFiles.length === 0 && <tr><td colSpan={5} className="text-sm text-slate-500">{t("page.modelDetail.noPatternFiles")}</td></tr>}
              </tbody>
              </table>
            </div>
          </div>
        )}

        {tab === 6 && (
          <div className="space-y-3">
            <label className="label">{t("page.modelDetail.additionalNote")}</label>
            <textarea className="input min-h-28" value={details.general?.note || ""} onChange={(e) => setDetails({ ...details, general: { ...details.general, note: e.target.value } })} />
          </div>
        )}

        {tab === 7 && (
          <div className="max-w-3xl rounded-md border border-[#ded9ca] bg-white p-5 shadow-sm print:shadow-none">
            <div className="grid grid-cols-1 gap-5 sm:grid-cols-[140px_minmax(0,1fr)]">
              <div className="aspect-[3/4] rounded-md border border-[#ecebe3] bg-[#f8f6ef]">
                {primaryImage ? (
                  <a href={imagePreviewHref(primaryImage.file_url, translatedName)} target="_blank" rel="noreferrer" className="block h-full w-full overflow-hidden rounded-md">
                    <VerticalModelPhoto src={storageThumbnailUrl(primaryImage.file_url, 640)} alt={translatedName} className="h-full w-full" width={480} height={640} />
                  </a>
                ) : (
                  <div className="flex h-full items-center justify-center text-xs text-slate-400">{t("page.models.noPreview")}</div>
                )}
              </div>
              <div className="space-y-3">
                <div>
                  <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    {t("field.modelNo")} {modelForm.model_no || "-"} / {t("field.variantNo")} {modelForm.variant_no || "-"}
                  </div>
                  <div className="text-2xl font-semibold text-[#14110b]">{translatedName}</div>
                  <div className="text-sm text-slate-600">{modelForm.category || "-"} · {modelForm.product_type || "-"}</div>
                </div>
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div><span className="text-slate-500">{t("page.modelDetail.sizeRange")}</span> {sizeRows.map((s: any) => s.size).join(", ") || "-"}</div>
                  <div><span className="text-slate-500">{t("page.modelDetail.colorsLabel")}</span> {colorRows.map((c: any) => c.color_name).join(", ") || "-"}</div>
                </div>
                {modelCompositionText && (
                  <div className="text-sm">
                    <span className="text-slate-500">{t("field.composition")}</span> {modelCompositionText}
                  </div>
                )}
                <div>
                  <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">{t("page.modelDetail.bomSummary")}</div>
                  <div className="grid grid-cols-1 gap-2 text-sm md:grid-cols-2">
                    <div>
                      <div className="font-medium">{t("page.modelDetail.fabrics")}</div>
                      <ul className="mt-1 space-y-1">
                        {materialRows.map((r: any) => <li key={r.id}>{r.material_name || r.item?.name || "-"} · {n(r.quantity_per_piece).toFixed(4)} {r.unit}</li>)}
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

        {tab === 8 && (
          <div className="space-y-2">
            {modelSizeRangeHelper()}
            <form onSubmit={addSize} className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-7">
              <input className="input" placeholder={t("page.modelDetail.sizeExample")} value={size.size} onChange={(e) => setSize({ ...size, size: e.target.value })} required />
              <input className="input" placeholder={t("page.modelDetail.measurement.chest")} value={measurementFields.chest} onChange={(e) => setMeasurementFields({ ...measurementFields, chest: e.target.value })} />
              <input className="input" placeholder={t("page.modelDetail.measurement.waist")} value={measurementFields.waist} onChange={(e) => setMeasurementFields({ ...measurementFields, waist: e.target.value })} />
              <input className="input" placeholder={t("page.modelDetail.measurement.hip")} value={measurementFields.hip} onChange={(e) => setMeasurementFields({ ...measurementFields, hip: e.target.value })} />
              <input className="input" placeholder={t("page.modelDetail.measurement.length")} value={measurementFields.length} onChange={(e) => setMeasurementFields({ ...measurementFields, length: e.target.value })} />
              <input className="input" placeholder={t("page.modelDetail.measurement.sleeve")} value={measurementFields.sleeve} onChange={(e) => setMeasurementFields({ ...measurementFields, sleeve: e.target.value })} />
              <button className="btn btn-primary" type="submit">{t("btn.add")}</button>
            </form>
            <div className="overflow-x-auto">
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
          </div>
        )}

        {tab === 9 && (
          <div className="space-y-3">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div><label className="label">{t("page.modelDetail.complexityLevel")}</label><input className="input" value={details.sewing?.complexity_level || ""} onChange={(e) => setDetails({ ...details, sewing: { ...details.sewing, complexity_level: e.target.value } })} /></div>
              <div><label className="label">{t("page.modelDetail.onePersonNorm")}</label><input className="input" type="number" step="0.01" value={details.sewing?.one_person_norm ?? ""} onChange={(e) => setDetails({ ...details, sewing: { ...details.sewing, one_person_norm: parseNumberInput(e.target.value) } })} /></div>
              <div><label className="label">{t("field.samMinutes")}</label><input className="input" type="number" step="0.1" value={modelForm.sam_minutes} onChange={(e) => setModelForm({ ...modelForm, sam_minutes: parseNumberInput(e.target.value) })} /></div>
            </div>
            <label className="label">{t("page.modelDetail.sewingNote")}</label>
            <textarea className="input min-h-24" value={details.sewing?.note || ""} onChange={(e) => setDetails({ ...details, sewing: { ...details.sewing, note: e.target.value } })} />
          </div>
        )}

        {tab === 10 && (
          <PaidOperationsEditor
            operations={paidOperations}
            visibleFactories={visiblePaidOperationFactories}
            onAdd={addPaidOperation}
            onUpdate={updatePaidOperation}
            onRemove={removePaidOperation}
          />
        )}

        {tab === 11 && (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div><label className="label">{t("page.modelDetail.langUz")}</label><input className="input" value={details.translation?.uz || ""} onChange={(e) => setDetails({ ...details, translation: { ...details.translation, uz: e.target.value } })} /></div>
            <div><label className="label">{t("page.modelDetail.langRu")}</label><input className="input" value={details.translation?.ru || ""} onChange={(e) => setDetails({ ...details, translation: { ...details.translation, ru: e.target.value } })} /></div>
            <div><label className="label">{t("page.modelDetail.langEn")}</label><input className="input" value={details.translation?.en || ""} onChange={(e) => setDetails({ ...details, translation: { ...details.translation, en: e.target.value } })} /></div>
          </div>
        )}

        {tab === 12 && (
          <div className="space-y-3">
            <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
              <div><label className="label">{t("page.modelDetail.laborPct")}</label><input className="input" type="number" step="0.1" value={details.costing?.labor_pct ?? 12} onChange={(e) => setDetails({ ...details, costing: { ...details.costing, labor_pct: parseNumberInput(e.target.value) } })} /></div>
              <div><label className="label">{t("page.modelDetail.electricityPct")}</label><input className="input" type="number" step="0.1" value={details.costing?.electricity_pct ?? 4} onChange={(e) => setDetails({ ...details, costing: { ...details.costing, electricity_pct: parseNumberInput(e.target.value) } })} /></div>
              <div><label className="label">{t("page.modelDetail.otherPct")}</label><input className="input" type="number" step="0.1" value={details.costing?.other_pct ?? 3} onChange={(e) => setDetails({ ...details, costing: { ...details.costing, other_pct: parseNumberInput(e.target.value) } })} /></div>
              <div><label className="label">{t("page.modelDetail.targetMarginPct")}</label><input className="input" type="number" step="0.1" value={details.costing?.target_margin_pct ?? 20} onChange={(e) => setDetails({ ...details, costing: { ...details.costing, target_margin_pct: parseNumberInput(e.target.value) } })} /></div>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
              <div className="card p-3"><div className="text-xs text-slate-500">{t("page.modelDetail.materialAccessoryCostPerPiece")}</div><div className="text-lg font-semibold">${baseCostPerPiece.toFixed(2)}</div></div>
              <div className="card p-3"><div className="text-xs text-slate-500">{t("page.modelDetail.extraCostsPerPiece")}</div><div className="text-lg font-semibold">${(laborCost + electricityCost + otherCost).toFixed(2)}</div></div>
              <div className="card p-3"><div className="text-xs text-slate-500">{t("page.modelDetail.netCostPerPiece")}</div><div className="text-lg font-semibold">${netCost.toFixed(2)}</div></div>
              <div className="card p-3"><div className="text-xs text-slate-500">{t("page.modelDetail.targetPricePerPiece")}</div><div className="text-lg font-semibold">${targetPrice.toFixed(2)}</div></div>
            </div>
          </div>
        )}

        </fieldset>

        <div className="flex justify-end gap-2 border-t border-[#ecebe3] pt-3">
          {msg && <div className="text-sm text-green-700 self-center">{msg}</div>}
          {isEditable && <button className="btn btn-primary" onClick={saveModel}>{isNewModel ? t("page.models.createNew") : t("common.save")}</button>}
        </div>
      </div>
    </div>
  );
}


