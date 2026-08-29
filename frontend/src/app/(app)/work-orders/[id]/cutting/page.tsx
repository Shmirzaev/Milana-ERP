"use client";
import { useParams } from "next/navigation";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";
import { ChevronDown, ChevronRight } from "lucide-react";
import { api, fetcher } from "@/lib/api";
import { formatBatchLabel, formatBatchSerial } from "@/lib/batchSerial";
import { useDialogs } from "@/components/DialogProvider";
import PageHeader from "@/components/PageHeader";
import { operationLabel, statusLabel } from "@/components/StagePipeline";
import WorkOrderProductInfo from "@/components/WorkOrderProductInfo";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { orderReference } from "@/lib/orderRef";
import { numberOrFallback, numberOrZero, type NumberInputValue } from "@/lib/numberInput";
import {
  beikaKgFromPassport,
  cuttingPassportAutofillValues,
  wasteKgFromPassport,
  type CuttingPassportAutofillSource,
} from "@/lib/cuttingPassportAutofill";

type SewingFactory = "milana" | "besttex" | "eco_cotton";

function sewingFactoryFromCode(value: unknown, fallback: SewingFactory): SewingFactory {
  const code = String(value || "").trim().toUpperCase();
  if (code === "BST") return "besttex";
  if (code === "ECO") return "eco_cotton";
  if (code === "MIL" || code === "SEW") return "milana";
  return fallback;
}
type BundlePlan = {
  color: string;
  size: string;
  quantity: NumberInputValue;
  count: NumberInputValue;
  next: "sewing" | "printing";
  sewing_factory: SewingFactory;
};
type BundleAdjustment = {
  bundleId: number;
  recordId: number;
  quantity: NumberInputValue;
  color: string;
  size: string;
};
type BundleQuantityResponseRow = {
  id: number;
  quantity: number;
  color?: string;
  size?: string;
};
type CuttingRecordDetailsEdit = {
  recordId: number;
  layer_material_kg: NumberInputValue;
  beika_kg: NumberInputValue;
  material_rolls_used: NumberInputValue;
  layup_operator_name: string;
  notes: string;
};
type CuttingSheetOption = {
  recordId: number;
  batchId: number;
  label: string;
  bundleIds: number[];
};
type CuttingForm = {
  production_batch_id: number;
  fabric_batch_id: number;
  model_bom_id: number;
  input_quantity: NumberInputValue;
  input_unit: string;
  cut_pieces: NumberInputValue;
  report_piece_count: NumberInputValue;
  waste_quantity: NumberInputValue;
  waste_unit: string;
  layer_material_kg: NumberInputValue;
  beika_kg: NumberInputValue;
  material_rolls_used: NumberInputValue;
  layup_operator_name: string;
  notes: string;
};
type CuttingMaterialForm = {
  stock_batch_id: number;
  planned_quantity: number;
  quantity: NumberInputValue;
  unit: string;
};
type PassportAutofillField = "input_quantity" | "layer_material_kg" | "material_rolls_used" | "layup_operator_name" | "cut_pieces" | "notes";
type ReplacementCompletionForm = {
  production_batch_id: number;
  completed_pieces: NumberInputValue;
  input_quantity: NumberInputValue;
};
function canAdjustCuttingInventoryBundle(bundle: any): boolean {
  return Number(bundle?.cutting_record_id || 0) > 0;
}
type SplitRow = { name: string; planned_quantity: NumberInputValue; start_date: string; deadline: string; notes: string };
type BatchPlanEdit = SplitRow;
type UslugaSizeCountEdit = {
  color: string;
  size: string;
  quantity: NumberInputValue;
  bundle_count: number;
};
type StockBatchReservation = {
  production_order_id?: number | null;
  remaining_quantity?: number | null;
  reserved_quantity?: number | null;
  unit?: string | null;
  status?: string | null;
};
type StockBatchOption = {
  id: number;
  item_id: number;
  item_sku?: string | null;
  item_name?: string | null;
  item_category?: string | null;
  batch_no?: string | null;
  color?: string | null;
  color_code?: string | null;
  width?: number | null;
  gsm?: number | null;
  quantity?: number | null;
  reserved_quantity?: number | null;
  available_quantity?: number | null;
  unit?: string | null;
  cost_per_unit?: number | null;
  warehouse_name?: string | null;
  qc_status?: string | null;
  received_date?: string | null;
  active_reservations?: StockBatchReservation[];
};
type CuttingPassportSummary = CuttingPassportAutofillSource & {
  id: number;
  production_order_id?: number | null;
  lot_no?: string | null;
  passport_no?: string | null;
  date?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

const MATERIAL_BATCH_CATEGORIES = new Set(["fabric", "semi_finished", ""]);

function itemKey(color: string, size: string) {
  return `${String(color || "").trim().toLowerCase()}||${String(size || "").trim().toLowerCase()}`;
}

function parseDecimalInput(value: string | number, fallback: NumberInputValue = ""): NumberInputValue {
  const normalized = String(value ?? "").replace(",", ".").trim();
  if (!normalized) return fallback;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function parseWholeInput(value: string | number, fallback: NumberInputValue = ""): NumberInputValue {
  const parsed = parseDecimalInput(value, fallback);
  return parsed === "" ? "" : Math.max(0, Math.floor(parsed));
}

function fmtQty(value: number | string | null | undefined): string {
  const parsed = Number(value || 0);
  if (!Number.isFinite(parsed)) return "0";
  return parsed.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

function dateInputValue(value: string | null | undefined): string {
  return String(value || "").slice(0, 10);
}

function compactParts(parts: Array<string | number | null | undefined | false>): string {
  return parts
    .map((part) => String(part || "").trim())
    .filter(Boolean)
    .join(", ");
}

function batchAvailableQty(batch: StockBatchOption | null | undefined): number {
  const available = Number(batch?.available_quantity);
  if (Number.isFinite(available)) return available;
  const quantity = Number(batch?.quantity);
  return Number.isFinite(quantity) ? quantity : 0;
}

function reservationForOrder(batch: StockBatchOption | null | undefined, productionOrderId: number | null | undefined) {
  const orderId = Number(productionOrderId || 0);
  if (!orderId) return null;
  return (batch?.active_reservations || []).find(
    (reservation) => Number(reservation?.production_order_id || 0) === orderId
      && Number(reservation?.remaining_quantity || 0) > 0,
  ) || null;
}

function fabricBatchCompactLabel(batch: StockBatchOption): string {
  const itemLabel = compactParts([batch.item_sku, batch.item_name]) || `Item #${batch.item_id}`;
  const unit = String(batch.unit || "").trim();
  return compactParts([
    itemLabel,
    batch.batch_no ? `Batch ${batch.batch_no}` : `Batch #${batch.id}`,
    `${fmtQty(batchAvailableQty(batch))} ${unit}`.trim(),
  ]).replace(/, /g, " - ");
}

function fabricBatchSearchText(batch: StockBatchOption): string {
  return [
    batch.item_sku,
    batch.item_name,
    batch.item_category,
    batch.batch_no,
    batch.color,
    batch.color_code,
    batch.warehouse_name,
    batch.qc_status,
    batch.unit,
  ].map((value) => String(value || "").toLowerCase()).join(" ");
}

function batchMatchesSearch(batch: StockBatchOption, query: string): boolean {
  const terms = query.toLowerCase().split(/\s+/).map((term) => term.trim()).filter(Boolean);
  if (terms.length === 0) return true;
  const haystack = fabricBatchSearchText(batch);
  return terms.every((term) => haystack.includes(term));
}

function normalizeRef(value: unknown): string {
  return String(value || "").trim().toLowerCase();
}

function passportMatchesFabricBatch(passport: CuttingPassportSummary, batch: StockBatchOption | null): boolean {
  if (!batch) return false;
  const lotNo = normalizeRef(passport.lot_no);
  if (!lotNo) return false;
  const refs = [
    batch.batch_no,
    batch.color_code,
    batch.color,
    batch.id ? `batch ${batch.id}` : null,
    batch.id,
  ].map(normalizeRef).filter(Boolean);
  return refs.includes(lotNo);
}

function uniqueBatchOptions(...groups: StockBatchOption[][]): StockBatchOption[] {
  const byId = new Map<number, StockBatchOption>();
  for (const group of groups) {
    for (const batch of group || []) {
      const id = Number(batch?.id || 0);
      if (id > 0 && !byId.has(id)) byId.set(id, batch);
    }
  }
  return [...byId.values()];
}

function mergeBundleRows(...groups: any[][]): any[] {
  const byId = new Map<number, any>();
  for (const group of groups) {
    for (const row of group || []) {
      const id = Number(row?.id || 0);
      if (id > 0) byId.set(id, { ...byId.get(id), ...row });
    }
  }
  return [...byId.values()].sort((a, b) => Number(a.id || 0) - Number(b.id || 0));
}

function distributeBundleTargets(items: any[], totalQty: number): Map<string, number> {
  const rows = (items || [])
    .map((it: any, index: number) => ({
      index,
      color: String(it?.color || "").trim() || "-",
      size: String(it?.size || "").trim() || "-",
      planned: Math.max(0, Number(it?.planned_quantity || 0)),
      qty: 0,
      remainder: 0,
    }))
    .filter((it) => it.planned > 0);
  const targetTotal = Math.max(0, Math.floor(Number(totalQty || 0)));
  const plannedTotal = rows.reduce((sum, it) => sum + it.planned, 0);
  const out = new Map<string, number>();
  if (rows.length === 0 || plannedTotal <= 0 || targetTotal <= 0) return out;

  let used = 0;
  for (const row of rows) {
    const exact = (targetTotal * row.planned) / plannedTotal;
    row.qty = Math.floor(exact);
    row.remainder = exact - row.qty;
    used += row.qty;
  }
  let left = targetTotal - used;
  const ranked = [...rows].sort((a, b) => b.remainder - a.remainder || a.index - b.index);
  for (let i = 0; i < left; i += 1) {
    ranked[i % ranked.length].qty += 1;
  }
  for (const row of rows) out.set(itemKey(row.color, row.size), row.qty);
  return out;
}

function autoSplitRows(totalQty: number, maxPerBatch: number): SplitRow[] {
  const safeTotal = Math.max(0, Number(totalQty || 0));
  const safeMax = Math.max(1, Number(maxPerBatch || 1));
  if (safeTotal <= 0) return [{ name: "Batch 1", planned_quantity: "", start_date: "", deadline: "", notes: "" }];
  const rows: SplitRow[] = [];
  let left = safeTotal;
  let idx = 1;
  while (left > 0) {
    const qty = Math.min(safeMax, left);
    rows.push({ name: `Batch ${idx}`, planned_quantity: qty, start_date: "", deadline: "", notes: "" });
    left -= qty;
    idx += 1;
  }
  return rows;
}

export default function CuttingPage() {
  const { t } = useT();
  const dialogs = useDialogs();
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const fabricListboxId = `fabric-batch-options-${id || "new"}`;
  const { me } = useMe();
  const { data: wo, mutate: mutateWo } = useSWR<any>(`/api/work-orders/${id}`, fetcher);
  const { data: po, mutate: mutatePo } = useSWR<any>(wo ? `/api/production-orders/${wo.production_order_id}` : null, fetcher);
  const isUsluga = po?.source_type === "usluga";
  const { data: so } = useSWR<any>(po?.sales_order_id ? `/api/sales-orders/${po.sales_order_id}` : null, fetcher);
  const { data: model } = useSWR<any>(
    po?.model_id ? `/api/${isUsluga ? "usluga/models" : "models"}/${po.model_id}` : null,
    fetcher,
  );
  const canReadCustomers = can(me, "*", "sales.customers", "sales.orders", "finance.view");
  const { data: customers = [] } = useSWR<any[]>(canReadCustomers ? "/api/customers" : null, fetcher);
  const { data: departments = [] } = useSWR<any[]>("/api/departments", fetcher);
  const { data: bundlePage, mutate: mutateBundles } = useSWR<any>(
    po?.id ? `/api/bundles?production_order_id=${po.id}&include_total=true&page=1&page_size=2000` : null,
    fetcher,
  );
  const { data: batchProgress, mutate: mutateBatchProgress } = useSWR<any>(
    wo ? `/api/work-orders/${id}/cutting-batch-progress` : null,
    fetcher,
  );
  const { data: replacementStatus, mutate: mutateReplacementStatus } = useSWR<any>(
    wo ? `/api/work-orders/${id}/replacement-status` : null,
    fetcher,
  );
  const { data: uslugaCuttingData, mutate: mutateUslugaCutting } = useSWR<any>(
    isUsluga && wo ? `/api/work-orders/${id}/usluga-cutting-batches` : null,
    fetcher,
  );
  const customerMap = useMemo(() => new Map(customers.map((c) => [c.id, c.name])), [customers]);
  const isEcoCottonCutting = departments.some(
    (department) => Number(department.id) === Number(wo?.department_id) && String(department.code).toUpperCase() === "ECT",
  );
  const plannedSewingFactory = sewingFactoryFromCode(
    po?.sewing_factory_code,
    isEcoCottonCutting ? "eco_cotton" : "milana",
  );
  const canEditBreakdown = can(me, "*", "planning.production", "cutting.records");
  const materialBomRows = useMemo(() => {
    return (Array.isArray(model?.bom) ? model.bom : []).filter((row: any) => {
      if (isUsluga) {
        return Boolean(String(row?.material_name || "").trim())
          && ["main", "secondary"].includes(String(row?.material_role || ""));
      }
      const category = String(row?.item?.category || "").toLowerCase();
      return MATERIAL_BATCH_CATEGORIES.has(category);
    });
  }, [isUsluga, model?.bom]);
  const materialItemIds = useMemo(() => {
    return Array.from(
      new Set(
        materialBomRows
          .map((row: any) => Number(row?.item_id || row?.item?.id || 0))
          .filter((itemId) => itemId > 0),
      ),
    );
  }, [materialBomRows]);
  const materialItemParam = materialItemIds.join(",");
  const fabricBatchUrl = useMemo(() => {
    if (!po || isUsluga) return null;
    const params = new URLSearchParams({ page_size: "1000" });
    if (materialItemParam) {
      params.set("item_ids", materialItemParam);
    } else {
      params.set("group", "materials");
    }
    return `/api/inventory/batches?${params.toString()}`;
  }, [isUsluga, materialItemParam, po]);
  const { data: batches = [] } = useSWR<StockBatchOption[]>(fabricBatchUrl, fetcher);
  const { data: allMaterialBatches = [] } = useSWR<StockBatchOption[]>(
    po && !isUsluga ? "/api/inventory/batches?group=materials&page_size=1000" : null,
    fetcher,
  );
  const { data: cuttingPassports = [] } = useSWR<CuttingPassportSummary[]>(
    po?.id ? `/api/cutting-passports?production_order_id=${po.id}&limit=50` : null,
    fetcher,
    { refreshInterval: 15_000, revalidateOnFocus: true },
  );

  const [form, setForm] = useState<CuttingForm>({
    production_batch_id: 0,
    fabric_batch_id: 0,
    model_bom_id: 0,
    input_quantity: "",
    input_unit: "kg",
    cut_pieces: "",
    report_piece_count: "",
    waste_quantity: "",
    waste_unit: "kg",
    layer_material_kg: "",
    beika_kg: "",
    material_rolls_used: "",
    layup_operator_name: "",
    notes: "",
  });
  const [cuttingMaterials, setCuttingMaterials] = useState<CuttingMaterialForm[]>([]);
  const [bundles, setBundles] = useState<BundlePlan[]>([]);
  const [bundlesAutofilled, setBundlesAutofilled] = useState(false);
  const [applyBundleColumnToAll, setApplyBundleColumnToAll] = useState(false);
  const [createdBundles, setCreatedBundles] = useState<any[]>([]);
  const [lastCuttingRecordId, setLastCuttingRecordId] = useState(0);
  const [selectedPrintCuttingRecordId, setSelectedPrintCuttingRecordId] = useState(0);
  const [createdBundlesExpanded, setCreatedBundlesExpanded] = useState(true);
  const [doneMsg, setDoneMsg] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState("");
  const [replacementCompletion, setReplacementCompletion] = useState<ReplacementCompletionForm>({
    production_batch_id: 0,
    completed_pieces: "",
    input_quantity: "",
  });
  const [replacementCompletionBusy, setReplacementCompletionBusy] = useState(false);
  const [replacementCompletionErr, setReplacementCompletionErr] = useState("");
  const [replacementCompletionDone, setReplacementCompletionDone] = useState("");
  const [adjustingBundle, setAdjustingBundle] = useState<BundleAdjustment | null>(null);
  const [adjustingBundleBusy, setAdjustingBundleBusy] = useState(false);
  const [adjustingBundleErr, setAdjustingBundleErr] = useState("");
  const [editingCuttingDetails, setEditingCuttingDetails] = useState<CuttingRecordDetailsEdit | null>(null);
  const [editingCuttingDetailsBusy, setEditingCuttingDetailsBusy] = useState(false);
  const [editingCuttingDetailsErr, setEditingCuttingDetailsErr] = useState("");
  const [deletingBundleId, setDeletingBundleId] = useState(0);
  const [splitMax, setSplitMax] = useState<NumberInputValue>(600);
  const [splitRows, setSplitRows] = useState<SplitRow[]>([]);
  const [splitBusy, setSplitBusy] = useState(false);
  const [splitErr, setSplitErr] = useState("");
  const [extraBatchOpen, setExtraBatchOpen] = useState(false);
  const [extraBatch, setExtraBatch] = useState<SplitRow>({ name: "", planned_quantity: "", start_date: "", deadline: "", notes: "" });
  const [extraBatchBusy, setExtraBatchBusy] = useState(false);
  const [extraBatchErr, setExtraBatchErr] = useState("");
  const [editingBatchId, setEditingBatchId] = useState(0);
  const [batchPlanEdit, setBatchPlanEdit] = useState<BatchPlanEdit>({ name: "", planned_quantity: "", start_date: "", deadline: "", notes: "" });
  const [batchPlanEditBusy, setBatchPlanEditBusy] = useState(false);
  const [batchPlanEditErr, setBatchPlanEditErr] = useState("");
  const [fabricSearch, setFabricSearch] = useState("");
  const [fabricPickerOpen, setFabricPickerOpen] = useState(false);
  const [fabricPickedManually, setFabricPickedManually] = useState(false);
  const [wastePickedManually, setWastePickedManually] = useState(false);
  const passportAutofillDirtyFields = useRef<Set<PassportAutofillField>>(new Set());
  const [shortageBusy, setShortageBusy] = useState(false);
  const [shortageErr, setShortageErr] = useState("");
  const [uslugaBatchBusy, setUslugaBatchBusy] = useState(0);
  const [uslugaRejectingId, setUslugaRejectingId] = useState(0);
  const [uslugaRejectReason, setUslugaRejectReason] = useState("");
  const [editingReportPiecesId, setEditingReportPiecesId] = useState(0);
  const [reportPiecesEdit, setReportPiecesEdit] = useState<NumberInputValue>("");
  const [reportPiecesEditBusy, setReportPiecesEditBusy] = useState(false);
  const [editingUslugaSizeCountsId, setEditingUslugaSizeCountsId] = useState(0);
  const [uslugaSizeCountEdits, setUslugaSizeCountEdits] = useState<UslugaSizeCountEdit[]>([]);
  const [uslugaSizeCountEditBusy, setUslugaSizeCountEditBusy] = useState(false);

  const uslugaFabricRows = useMemo(
    () => isUsluga ? materialBomRows : [],
    [isUsluga, materialBomRows],
  );
  const selectedUslugaFabric = useMemo(
    () => uslugaFabricRows.find((row: any) => Number(row?.id || 0) === Number(form.model_bom_id || 0)) || null,
    [form.model_bom_id, uslugaFabricRows],
  );
  const isSecondaryUslugaFabric = selectedUslugaFabric?.material_role === "secondary";
  const uslugaCuttingBatches = Array.isArray(uslugaCuttingData?.items) ? uslugaCuttingData.items : [];

  const fabricBatches = useMemo(() => {
    const materialIdSet = new Set(materialItemIds);
    return [...(batches || [])]
      .filter((batch) => {
        const itemId = Number(batch?.item_id || 0);
        if (materialIdSet.size > 0 && !materialIdSet.has(itemId)) return false;
        const category = String(batch?.item_category || "").toLowerCase();
        if (materialIdSet.size === 0 && !MATERIAL_BATCH_CATEGORIES.has(category)) return false;
        const quantity = Number(batch?.quantity || 0);
        return quantity > 0 || batchAvailableQty(batch) > 0 || Boolean(reservationForOrder(batch, po?.id));
      })
      .sort((a, b) => {
        const aReserved = reservationForOrder(a, po?.id) ? 1 : 0;
        const bReserved = reservationForOrder(b, po?.id) ? 1 : 0;
        if (aReserved !== bReserved) return bReserved - aReserved;
        const availableDiff = batchAvailableQty(b) - batchAvailableQty(a);
        if (Math.abs(availableDiff) > 0.0001) return availableDiff;
        return Number(b.id || 0) - Number(a.id || 0);
      });
  }, [batches, materialItemIds, po?.id]);
  const allSearchableFabricBatches = useMemo(() => {
    const materialIdSet = new Set(materialItemIds);
    return uniqueBatchOptions(fabricBatches, allMaterialBatches)
      .filter((batch) => {
        const category = String(batch?.item_category || "").toLowerCase();
        if (!MATERIAL_BATCH_CATEGORIES.has(category)) return false;
        const quantity = Number(batch?.quantity || 0);
        return quantity > 0 || batchAvailableQty(batch) > 0 || Boolean(reservationForOrder(batch, po?.id));
      })
      .sort((a, b) => {
        const aModelMaterial = materialIdSet.has(Number(a.item_id || 0)) ? 1 : 0;
        const bModelMaterial = materialIdSet.has(Number(b.item_id || 0)) ? 1 : 0;
        if (aModelMaterial !== bModelMaterial) return bModelMaterial - aModelMaterial;
        const aReserved = reservationForOrder(a, po?.id) ? 1 : 0;
        const bReserved = reservationForOrder(b, po?.id) ? 1 : 0;
        if (aReserved !== bReserved) return bReserved - aReserved;
        const availableDiff = batchAvailableQty(b) - batchAvailableQty(a);
        if (Math.abs(availableDiff) > 0.0001) return availableDiff;
        return Number(b.id || 0) - Number(a.id || 0);
      });
  }, [allMaterialBatches, fabricBatches, materialItemIds, po?.id]);
  const fabricSearchQuery = fabricSearch.trim();
  const fabricPickerOptions = useMemo(() => {
    const source = fabricSearchQuery ? allSearchableFabricBatches : fabricBatches;
    return source.filter((batch) => batchMatchesSearch(batch, fabricSearchQuery)).slice(0, 30);
  }, [allSearchableFabricBatches, fabricBatches, fabricSearchQuery]);
  const selectedFabricBatch = useMemo(
    () => allSearchableFabricBatches.find((batch) => Number(batch.id || 0) === Number(form.fabric_batch_id || 0)) || null,
    [allSearchableFabricBatches, form.fabric_batch_id],
  );
  const selectedFabricReservation = useMemo(
    () => reservationForOrder(selectedFabricBatch, po?.id),
    [po?.id, selectedFabricBatch],
  );
  const plannedMaterials = useMemo(
    () => (Array.isArray(po?.materials) ? po.materials : [])
      .map((row: any) => ({
        stock_batch_id: Number(row?.stock_batch_id || 0),
        planned_quantity: Number(row?.estimated_quantity || 0),
        unit: String(row?.unit || "kg"),
      }))
      .filter((row: { stock_batch_id: number; planned_quantity: number; unit: string }) => (
        row.stock_batch_id > 0 && row.planned_quantity > 0
      )),
    [po?.materials],
  );
  const plannedMaterialBatchLookup = useMemo(
    () => new Map(allSearchableFabricBatches.map((batch) => [Number(batch.id), batch])),
    [allSearchableFabricBatches],
  );
  const hasPlannedMaterials = plannedMaterials.length > 0;
  const selectedCuttingPassport = useMemo(() => {
    const rows = Array.isArray(cuttingPassports) ? cuttingPassports : [];
    return rows.find((passport) => passportMatchesFabricBatch(passport, selectedFabricBatch)) || rows[0] || null;
  }, [cuttingPassports, selectedFabricBatch]);
  const pendingReplacementItems = useMemo(
    () => (Array.isArray(replacementStatus?.items) ? replacementStatus.items : [])
      .filter((row: any) => Number(row?.waiting_cutting_qty || 0) > 0),
    [replacementStatus?.items],
  );
  const selectedReplacementItem = useMemo(
    () => pendingReplacementItems.find(
      (row: any) => Number(row?.production_batch_id || 0) === Number(replacementCompletion.production_batch_id || 0),
    ) || pendingReplacementItems[0] || null,
    [pendingReplacementItems, replacementCompletion.production_batch_id],
  );
  const autoWasteQuantity = useMemo(
    () => wasteKgFromPassport(selectedCuttingPassport, numberOrZero(form.input_quantity)),
    [form.input_quantity, selectedCuttingPassport],
  );
  const passportAutofill = useMemo(
    () => cuttingPassportAutofillValues(selectedCuttingPassport),
    [selectedCuttingPassport],
  );
  const passportBeikaKg = useMemo(
    () => beikaKgFromPassport(selectedCuttingPassport),
    [selectedCuttingPassport],
  );
  const requiredMaterialNames = useMemo(() => {
    return materialBomRows
      .map((row: any) => compactParts([row?.item?.sku, row?.item?.name]) || `Item #${row?.item_id}`)
      .filter(Boolean)
      .join(", ");
  }, [materialBomRows]);

  const plannedItemTotal = useMemo(
    () => (po?.items || []).reduce((sum: number, it: any) => sum + Math.max(0, Number(it?.planned_quantity || 0)), 0),
    [po?.items],
  );
  const isAlreadyBatched = Array.isArray(po?.batches) && po.batches.length > 0;
  const canSplitHere = Boolean(
    wo
    && po
    && !isAlreadyBatched
    && (wo.production_batch_id === null || wo.production_batch_id === undefined)
  );
  const splitTotal = splitRows.reduce((sum, row) => sum + numberOrZero(row.planned_quantity), 0);
  const splitPlannedQty = Number(wo?.planned_output_qty || po?.planned_quantity || 0);
  const productInfoPo = useMemo(() => {
    if (!po || !canSplitHere || splitTotal <= splitPlannedQty) return po;
    return {
      ...po,
      actual_quantity: Math.max(Number(po?.actual_quantity || 0), splitTotal),
    };
  }, [canSplitHere, po, splitPlannedQty, splitTotal]);
  const batchItems = useMemo(
    () => Array.isArray(batchProgress?.items) ? batchProgress.items : [],
    [batchProgress?.items],
  );
  const recordedPassedQty = Math.max(
    Number(wo?.passed_qty || 0),
    batchItems.reduce((sum: number, row: any) => sum + Math.max(0, Number(row?.passed_pieces || 0)), 0),
  );
  const recordedFailedQty = Math.max(
    Number(wo?.failed_qty || 0),
    batchItems.reduce((sum: number, row: any) => sum + Math.max(0, Number(row?.defective_pieces || 0)), 0),
  );
  const cuttingPlanQty = Math.max(0, Number(wo?.planned_output_qty || 0));
  const cuttingShortageQty = Math.max(0, cuttingPlanQty - recordedPassedQty - recordedFailedQty);
  const canCompleteWithShortage = Boolean(
    wo
    && can(me, "*", "planning.production", "cutting.records")
    && !["completed", "rejected", "cancelled"].includes(String(wo.status || ""))
    && recordedPassedQty > 0
    && cuttingShortageQty > 0
  );
  const selectedBatchProgress = useMemo(() => {
    const selectedId = Number(form.production_batch_id || wo?.production_batch_id || 0);
    if (!selectedId) return null;
    return batchItems.find((row: any) => Number(row?.id || 0) === selectedId) || null;
  }, [batchItems, form.production_batch_id, wo?.production_batch_id]);
  const batchTargetTotal = selectedBatchProgress
    ? Math.max(0, Number(selectedBatchProgress.remaining_quantity ?? selectedBatchProgress.planned_quantity ?? 0))
    : plannedItemTotal;
  const cutPieces = numberOrZero(form.cut_pieces);
  const bundleTargetTotal = cutPieces > 0 ? cutPieces : batchTargetTotal;
  const bundleTargetQtyByKey = useMemo(
    () => distributeBundleTargets(po?.items || [], bundleTargetTotal),
    [po?.items, bundleTargetTotal],
  );
  const createdBundlesBatch = useMemo(() => {
    const productionBatches = Array.isArray(po?.batches) ? po.batches : [];
    const selectedId = Number(form.production_batch_id || wo?.production_batch_id || 0);
    if (selectedId) {
      const selected = productionBatches.find((b: any) => Number(b?.id || 0) === selectedId);
      if (selected) return selected;
    }
    return productionBatches.length === 1 ? productionBatches[0] : null;
  }, [form.production_batch_id, po?.batches, wo?.production_batch_id]);
  const createdBundlesBatchLabel = createdBundlesBatch
    ? formatBatchLabel(createdBundlesBatch, po?.id)
    : form.production_batch_id
      ? `${t("field.batch")} #${form.production_batch_id}`
      : t("field.batch");
  const savedBundles = Array.isArray(bundlePage?.rows)
    ? bundlePage.rows
    : Array.isArray(bundlePage)
      ? bundlePage
      : [];
  const visibleBundles = mergeBundleRows(savedBundles, createdBundles);
  const visibleBundleQuantity = visibleBundles.reduce((sum, bundle) => sum + Number(bundle?.quantity || 0), 0);
  const adjustableBundleCount = visibleBundles.filter(canAdjustCuttingInventoryBundle).length;
  const bundlePlanTotal = bundles.reduce((sum, row) => (
    sum + Math.max(0, numberOrZero(row.quantity)) * Math.max(0, numberOrZero(row.count))
  ), 0);
  const visibleBundleIds = visibleBundles
    .map((b) => Number(b?.id || 0))
    .filter((bundleId) => bundleId > 0)
    .join(",");
  const selectedBundleBatchId = Number(form.production_batch_id || wo?.production_batch_id || 0);
  const printableCuttingSheets = (() => {
    const productionBatches = Array.isArray(po?.batches) ? po.batches : [];
    const byRecordId = new Map<number, CuttingSheetOption>();
    for (const bundle of visibleBundles) {
      const recordId = Number(bundle?.cutting_record_id || 0);
      const bundleId = Number(bundle?.id || 0);
      if (!recordId || !bundleId) continue;
      const batchId = Number(bundle?.production_batch_id || 0);
      const batch = productionBatches.find((row: any) => Number(row?.id || 0) === batchId);
      const batchLabel = batch
        ? formatBatchLabel(batch, po?.id)
        : batchId
          ? `${t("field.batch")} #${batchId}`
          : orderReference(po);
      const existing = byRecordId.get(recordId);
      if (existing) {
        existing.bundleIds.push(bundleId);
      } else {
        byRecordId.set(recordId, {
          recordId,
          batchId,
          label: `${batchLabel} — CUT-${recordId}`,
          bundleIds: [bundleId],
        });
      }
    }
    return Array.from(byRecordId.values()).sort((a, b) => {
      const aBatchIndex = productionBatches.findIndex((row: any) => Number(row?.id || 0) === a.batchId);
      const bBatchIndex = productionBatches.findIndex((row: any) => Number(row?.id || 0) === b.batchId);
      if (aBatchIndex !== bBatchIndex) return aBatchIndex - bBatchIndex;
      return a.recordId - b.recordId;
    });
  })();
  const selectedPrintCuttingSheet = printableCuttingSheets.find(
    (option) => option.recordId === selectedPrintCuttingRecordId,
  ) || printableCuttingSheets.find(
    (option) => selectedBundleBatchId > 0 && option.batchId === selectedBundleBatchId,
  ) || printableCuttingSheets.find(
    (option) => option.recordId === lastCuttingRecordId,
  ) || printableCuttingSheets[0] || null;
  const printableCuttingRecordId = selectedPrintCuttingSheet?.recordId || 0;
  const printableBundleIds = selectedPrintCuttingSheet?.bundleIds.join(",") || "";

  useEffect(() => {
    if (!Array.isArray(po?.items) || po.items.length === 0 || departments.length === 0) return;
    const hasPrintingStage = Array.isArray(po?.work_orders) && po.work_orders.some((w: any) => w.operation === "printing");
    const nextStage: "sewing" | "printing" = hasPrintingStage ? "printing" : "sewing";
    const defaultBundleQty = 50;
    const targetMap = distributeBundleTargets(po.items, bundleTargetTotal);
    setBundles((prev) => {
      const byKey = new Map(prev.map((row) => [itemKey(row.color, row.size), row]));
      const recalculated = po.items
        .filter((it: any) => Number(it?.planned_quantity || 0) > 0)
        .map((it: any) => {
          const color = String(it?.color || "").trim() || "-";
          const size = String(it?.size || "").trim() || "-";
          const key = itemKey(color, size);
          const existing = byKey.get(key);
          const targetQty = targetMap.get(key) || 0;
          if (targetQty <= 0) return null;
          const preferredQty = Math.max(1, Number(existing?.quantity || defaultBundleQty));
          const qtyPerBundle = Math.max(1, Math.min(preferredQty, targetQty));
          return {
            color,
            size,
            quantity: qtyPerBundle,
            count: Math.max(1, Math.ceil(targetQty / qtyPerBundle)),
            next: existing?.next || nextStage,
            sewing_factory: existing?.sewing_factory || plannedSewingFactory,
          };
        })
        .filter((row): row is BundlePlan => row !== null);
      return recalculated.length > 0 ? recalculated : prev;
    });
    if (!bundlesAutofilled) {
      setBundlesAutofilled(true);
    }
  }, [po?.items, po?.work_orders, bundleTargetTotal, bundlesAutofilled, departments.length, plannedSewingFactory]);

  useEffect(() => {
    if (!canSplitHere) return;
    const plannedQty = Number(wo?.planned_output_qty || po?.planned_quantity || 0);
    setSplitRows((prev) => (prev.length > 0 ? prev : autoSplitRows(plannedQty, numberOrFallback(splitMax, 1))));
  }, [canSplitHere, po?.planned_quantity, splitMax, wo?.planned_output_qty]);

  useEffect(() => {
    passportAutofillDirtyFields.current.clear();
    setWastePickedManually(false);
  }, [po?.id, form.production_batch_id, form.fabric_batch_id]);

  useEffect(() => {
    if (wastePickedManually || autoWasteQuantity === null) return;
    setForm((prev) => {
      const current = numberOrZero(prev.waste_quantity);
      if (Math.abs(current - autoWasteQuantity) < 0.0001) return prev;
      return {
        ...prev,
        waste_quantity: autoWasteQuantity,
        waste_unit: prev.waste_unit || selectedFabricBatch?.unit || "kg",
      };
    });
  }, [autoWasteQuantity, selectedFabricBatch?.unit, wastePickedManually]);

  useEffect(() => {
    if (!isAlreadyBatched || !Array.isArray(po?.batches) || po.batches.length === 0) return;
    setForm((prev) => {
      if (prev.production_batch_id) return prev;
      return { ...prev, production_batch_id: Number(po.batches[0].id || 0) };
    });
  }, [isAlreadyBatched, po?.batches]);

  useEffect(() => {
    if (!isUsluga || form.model_bom_id || uslugaFabricRows.length === 0) return;
    const defaultFabric = uslugaFabricRows.find((row: any) => row?.material_role === "main") || uslugaFabricRows[0];
    setForm((prev) => ({ ...prev, model_bom_id: Number(defaultFabric?.id || 0) }));
  }, [form.model_bom_id, isUsluga, uslugaFabricRows]);

  useEffect(() => {
    if (!plannedMaterials.length) {
      setCuttingMaterials([]);
      return;
    }
    setCuttingMaterials((current) => {
      const byBatch = new Map(current.map((row) => [row.stock_batch_id, row]));
      return plannedMaterials.map((planned) => ({
        ...planned,
        quantity: byBatch.get(planned.stock_batch_id)?.quantity ?? "",
      }));
    });
    const primary = plannedMaterials[0];
    setForm((current) => ({
      ...current,
      fabric_batch_id: primary.stock_batch_id,
      input_unit: primary.unit,
      waste_unit: current.waste_unit || primary.unit,
    }));
  }, [plannedMaterials]);

  useEffect(() => {
    if (plannedMaterials.length > 0) return;
    if (form.fabric_batch_id || fabricPickedManually || fabricBatches.length === 0) return;
    const batch = fabricBatches.find(
      (row) => Number(row.id || 0) === Number(po?.fabric_batch_id || 0),
    ) || fabricBatches[0];
    setForm((prev) => {
      if (prev.fabric_batch_id) return prev;
      return {
        ...prev,
        fabric_batch_id: Number(batch.id || 0),
        input_unit: batch.unit || prev.input_unit,
        waste_unit: batch.unit || prev.waste_unit,
      };
    });
  }, [fabricBatches, fabricPickedManually, form.fabric_batch_id, plannedMaterials.length, po?.fabric_batch_id]);

  useEffect(() => {
    if (pendingReplacementItems.length === 0) return;
    setReplacementCompletion((prev) => {
      const selected = pendingReplacementItems.find(
        (row: any) => Number(row?.production_batch_id || 0) === Number(prev.production_batch_id || 0),
      ) || pendingReplacementItems[0];
      const waiting = Math.max(0, Number(selected?.waiting_cutting_qty || 0));
      const currentQty = numberOrZero(prev.completed_pieces);
      return {
        ...prev,
        production_batch_id: Number(selected?.production_batch_id || 0),
        completed_pieces: currentQty > 0 && currentQty <= waiting ? prev.completed_pieces : waiting,
      };
    });
  }, [pendingReplacementItems]);

  useEffect(() => {
    if (!form.fabric_batch_id) return;
    if (selectedFabricBatch) return;
    setForm((prev) => ({ ...prev, fabric_batch_id: 0 }));
  }, [form.fabric_batch_id, selectedFabricBatch]);

  useEffect(() => {
    if (!selectedCuttingPassport) return;
    const dirtyFields = passportAutofillDirtyFields.current;
    const entries = Object.entries(passportAutofill) as Array<[
      PassportAutofillField,
      CuttingForm[PassportAutofillField] | undefined,
    ]>;
    setForm((current) => {
      let next = current;
      for (const [field, value] of entries) {
        if (value === undefined || dirtyFields.has(field) || current[field] === value) continue;
        next = { ...next, [field]: value };
      }
      return next;
    });
  }, [form.fabric_batch_id, form.production_batch_id, passportAutofill, selectedCuttingPassport]);

  useEffect(() => {
    if (!selectedCuttingPassport) return;
    setForm((current) => ({
      ...current,
      beika_kg: passportBeikaKg ?? "",
    }));
  }, [form.fabric_batch_id, form.production_batch_id, passportBeikaKg, selectedCuttingPassport]);

  function setPassportAutofillField(
    field: PassportAutofillField,
    value: CuttingForm[PassportAutofillField],
  ) {
    passportAutofillDirtyFields.current.add(field);
    setForm((current) => ({ ...current, [field]: value }));
  }

  function setB(i: number, p: Partial<BundlePlan>) {
    setBundles((prev) => prev.map((b, j) => (applyBundleColumnToAll || i === j ? { ...b, ...p } : b)));
  }
  function setBQty(i: number, nextQtyRaw: string | number) {
    const parsedQty = parseWholeInput(nextQtyRaw);
    setBundles((prev) => prev.map((b, j) => {
      if (!applyBundleColumnToAll && i !== j) return b;
      if (parsedQty === "") return { ...b, quantity: "" };
      const nextQty = Math.max(1, parsedQty);
      const key = itemKey(b.color, b.size);
      const targetQty = bundleTargetQtyByKey.get(key) ?? (Number(b.quantity || 0) * Number(b.count || 1));
      const nextCount = Math.max(1, Math.ceil(Number(targetQty || 0) / nextQty));
      return { ...b, quantity: nextQty, count: nextCount };
    }));
  }
  function addB() {
    const first = bundles[0];
    setBundles([
      ...bundles,
      {
        color: first?.color || "white",
        size: first?.size || "M",
        quantity: first?.quantity || 50,
        count: 1,
        next: first?.next || "sewing",
        sewing_factory: first?.sewing_factory || plannedSewingFactory,
      },
    ]);
  }
  function remB(i: number) {
    setBundles(bundles.filter((_, j) => j !== i));
  }

  function factoryLabel(value: string | null | undefined) {
    const normalized = String(value || "").trim().toLowerCase();
    if (normalized === "bst" || normalized === "besttex") return t("factory.besttex");
    if (["eco", "eco cotton", "eco_cotton", "ecocotton"].includes(normalized)) return t("factory.ecoCotton");
    return t("factory.milana");
  }

  function selectFabricBatch(batch: StockBatchOption | null, manual = true) {
    setForm((prev) => ({
      ...prev,
      fabric_batch_id: Number(batch?.id || 0),
      input_unit: batch?.unit || prev.input_unit,
      waste_unit: batch?.unit || prev.waste_unit,
    }));
    setFabricPickedManually(manual);
    setFabricSearch("");
    setFabricPickerOpen(false);
  }

  function updateSplitRow(index: number, patch: Partial<SplitRow>) {
    setSplitRows((prev) => prev.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  function addSplitRow() {
    setSplitRows((prev) => [...prev, { name: `Batch ${prev.length + 1}`, planned_quantity: "", start_date: "", deadline: "", notes: "" }]);
  }

  function removeSplitRow(index: number) {
    setSplitRows((prev) => (prev.length <= 1 ? prev : prev.filter((_, i) => i !== index)));
  }

  async function splitIntoBatches() {
    if (!canSplitHere) return;
    setSplitErr("");
    const rows = splitRows.map((row) => ({
      ...row,
      name: String(row.name || "").trim(),
      planned_quantity: numberOrZero(row.planned_quantity),
    }));
    if (rows.some((row) => !Number.isFinite(row.planned_quantity) || row.planned_quantity <= 0)) {
      setSplitErr(t("batch.quantityGreaterThanZero"));
      return;
    }
    setSplitBusy(true);
    try {
      const payloadRows = rows.map((row) => ({
        name: row.name || null,
        planned_quantity: row.planned_quantity,
        start_date: row.start_date ? new Date(row.start_date).toISOString() : null,
        deadline: row.deadline ? new Date(row.deadline).toISOString() : null,
        notes: row.notes ? row.notes : null,
      }));
      await api.post(`/api/work-orders/${id}/split-batches`, { batches: payloadRows });
      await Promise.all([mutatePo(), mutateWo(), mutateBatchProgress()]);
      setDoneMsg(t("batch.planSaved"));
    } catch (e: any) {
      setSplitErr(e.message || "Failed to split into batches");
    } finally {
      setSplitBusy(false);
    }
  }

  function openExtraBatchForm() {
    const nextIndex = (Array.isArray(po?.batches) ? po.batches.length : 0) + 1;
    setExtraBatch({
      name: `Extra batch ${nextIndex}`,
      planned_quantity: Math.max(0, numberOrZero(form.cut_pieces)),
      start_date: "",
      deadline: "",
      notes: "",
    });
    setExtraBatchErr("");
    setExtraBatchOpen(true);
  }

  function updateExtraBatch(patch: Partial<SplitRow>) {
    setExtraBatch((prev) => ({ ...prev, ...patch }));
  }

  async function saveExtraBatch() {
    const qty = numberOrZero(extraBatch.planned_quantity);
    setExtraBatchErr("");
    if (!Number.isFinite(qty) || qty <= 0) {
      setExtraBatchErr(t("batch.quantityGreaterThanZero"));
      return;
    }
    setExtraBatchBusy(true);
    try {
      const created = await api.post(`/api/work-orders/${id}/extra-batch`, {
        name: String(extraBatch.name || "").trim() || null,
        planned_quantity: qty,
        start_date: extraBatch.start_date ? new Date(extraBatch.start_date).toISOString() : null,
        deadline: extraBatch.deadline ? new Date(extraBatch.deadline).toISOString() : null,
        notes: extraBatch.notes ? extraBatch.notes : null,
      });
      const batchId = Number(created?.id || 0);
      const batchQty = Number(created?.planned_quantity || qty);
      passportAutofillDirtyFields.current.add("cut_pieces");
      setForm((prev) => ({
        ...prev,
        production_batch_id: batchId || prev.production_batch_id,
        cut_pieces: batchQty || prev.cut_pieces,
      }));
      setExtraBatchOpen(false);
      setDoneMsg(t("batch.extraBatchCreated"));
      await Promise.all([mutatePo(), mutateWo(), mutateBatchProgress()]);
    } catch (e: any) {
      setExtraBatchErr(e.message || "Failed to add extra batch");
    } finally {
      setExtraBatchBusy(false);
    }
  }

  function startBatchPlanEdit(row: any) {
    setEditingBatchId(Number(row?.id || 0));
    setBatchPlanEdit({
      name: String(row?.name || ""),
      planned_quantity: Math.max(0, Number(row?.planned_quantity || 0)),
      start_date: dateInputValue(row?.start_date),
      deadline: dateInputValue(row?.deadline),
      notes: String(row?.notes || ""),
    });
    setBatchPlanEditErr("");
  }

  function cancelBatchPlanEdit() {
    setEditingBatchId(0);
    setBatchPlanEdit({ name: "", planned_quantity: "", start_date: "", deadline: "", notes: "" });
    setBatchPlanEditErr("");
  }

  async function saveBatchPlanEdit(row: any) {
    const batchId = Number(row?.id || 0);
    const quantityEditable = Boolean(row?.quantity_editable ?? row?.editable);
    const name = String(batchPlanEdit.name || "").trim();
    const quantity = numberOrZero(batchPlanEdit.planned_quantity);
    setBatchPlanEditErr("");
    if (!name) {
      setBatchPlanEditErr(t("batch.nameRequired"));
      return;
    }
    if (quantityEditable && (!Number.isFinite(quantity) || quantity <= 0)) {
      setBatchPlanEditErr(t("batch.quantityGreaterThanZero"));
      return;
    }
    setBatchPlanEditBusy(true);
    try {
      await api.patch(`/api/work-orders/${id}/batches/${batchId}`, {
        name,
        ...(quantityEditable ? { planned_quantity: quantity } : {}),
        ...(!isUsluga ? {
          start_date: batchPlanEdit.start_date ? new Date(batchPlanEdit.start_date).toISOString() : null,
          deadline: batchPlanEdit.deadline ? new Date(batchPlanEdit.deadline).toISOString() : null,
          notes: batchPlanEdit.notes.trim() || null,
        } : {}),
      });
      await Promise.all([mutatePo(), mutateWo(), mutateBatchProgress(), mutateBundles()]);
      cancelBatchPlanEdit();
      setDoneMsg(t("batch.planUpdated"));
    } catch (e: any) {
      setBatchPlanEditErr(e.message || "Failed to update batch plan");
    } finally {
      setBatchPlanEditBusy(false);
    }
  }

  async function saveBreakdown(items: Array<{ id?: number | null; color: string; size: string; planned_quantity: number }>) {
    if (!po?.id) return;
    await api.put(`/api/production-orders/${po.id}/breakdown`, { items });
    await Promise.all([mutatePo(), mutateWo(), mutateBatchProgress()]);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    setDoneMsg("");
    if (isUsluga && !form.model_bom_id) {
      setErr(t("usluga.selectCuttingFabric"));
      return;
    }
    if (isAlreadyBatched && !form.production_batch_id) {
      setErr(t("batch.selectBeforeSaving", { operation: operationLabel("cutting", t).toLowerCase() }));
      return;
    }
    if (hasPlannedMaterials && cuttingMaterials.some((row) => numberOrZero(row.quantity) <= 0)) {
      setErr(t("page.cutting.enterEveryMaterialAmount"));
      return;
    }
    setSubmitting(true);
    try {
      const outputPieces = isSecondaryUslugaFabric ? 0 : (bundlePlanTotal > 0 ? bundlePlanTotal : numberOrZero(form.cut_pieces));
      const normalizedBundles = (isSecondaryUslugaFabric ? [] : bundles).map((bundle) => ({
        ...bundle,
        quantity: Math.max(1, numberOrFallback(bundle.quantity, 1)),
        count: Math.max(1, numberOrFallback(bundle.count, 1)),
      }));
      const normalizedMaterials = hasPlannedMaterials
        ? cuttingMaterials.map((row) => ({
            stock_batch_id: row.stock_batch_id,
            quantity: numberOrZero(row.quantity),
            unit: row.unit,
          }))
        : [];
      const primaryMaterial = normalizedMaterials[0];
      const r = await api.post("/api/cutting/records", {
        work_order_id: id,
        ...form,
        input_quantity: primaryMaterial?.quantity ?? numberOrZero(form.input_quantity),
        input_unit: primaryMaterial?.unit ?? form.input_unit,
        layer_material_kg: numberOrZero(form.layer_material_kg),
        beika_kg: numberOrZero(form.beika_kg),
        material_rolls_used: numberOrZero(form.material_rolls_used),
        waste_quantity: numberOrZero(form.waste_quantity),
        cut_pieces: outputPieces,
        report_piece_count: isSecondaryUslugaFabric ? numberOrZero(form.report_piece_count) : 0,
        passed_pieces: outputPieces,
        defective_pieces: 0,
        production_batch_id: form.production_batch_id || null,
        fabric_batch_id: isUsluga ? null : (primaryMaterial?.stock_batch_id ?? (form.fabric_batch_id || null)),
        model_bom_id: isUsluga ? (form.model_bom_id || null) : null,
        materials: normalizedMaterials,
        bundles: normalizedBundles,
      }, 120_000);
      const created = Array.isArray(r?.bundles) ? r.bundles : [];
      setLastCuttingRecordId(Number(r?.id || 0));
      setCreatedBundles((prev) => mergeBundleRows(prev, created));
      setCreatedBundlesExpanded(true);
      setCuttingMaterials((current) => current.map((row) => ({ ...row, quantity: "" })));
      setDoneMsg(isUsluga ? t("usluga.batchSavedPending") : t("msg.cuttingDone", { count: created.length }));
      setForm((prev) => ({
        ...prev,
        input_quantity: "",
        cut_pieces: "",
        report_piece_count: "",
        waste_quantity: "",
        layer_material_kg: "",
        beika_kg: "",
        material_rolls_used: "",
        notes: "",
      }));
      await Promise.all([mutatePo(), mutateWo(), mutateBatchProgress(), mutateBundles(), mutateReplacementStatus(), mutateUslugaCutting()]);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSubmitting(false);
    }
  }

  async function approveUslugaBatch(recordId: number) {
    setUslugaBatchBusy(recordId);
    setErr("");
    setDoneMsg("");
    try {
      await api.post(`/api/cutting/records/${recordId}/approve-usluga-batch`, {});
      setDoneMsg(t("usluga.approved"));
      await Promise.all([mutatePo(), mutateWo(), mutateBatchProgress(), mutateBundles(), mutateUslugaCutting()]);
    } catch (e: any) {
      setErr(e?.message || t("usluga.actionFailed"));
    } finally {
      setUslugaBatchBusy(0);
    }
  }

  async function saveReportPieces(recordId: number) {
    setReportPiecesEditBusy(true);
    setErr("");
    try {
      await api.patch(`/api/cutting/records/${recordId}/usluga-report-pieces`, {
        report_piece_count: numberOrZero(reportPiecesEdit),
      });
      setEditingReportPiecesId(0);
      setReportPiecesEdit("");
      await mutateUslugaCutting();
    } catch (e: any) {
      setErr(e.message || t("usluga.actionFailed"));
    } finally {
      setReportPiecesEditBusy(false);
    }
  }

  async function saveUslugaSizeCounts(recordId: number) {
    setUslugaSizeCountEditBusy(true);
    setErr("");
    setDoneMsg("");
    try {
      await api.patch(`/api/cutting/records/${recordId}/usluga-size-counts`, {
        sizes: uslugaSizeCountEdits.map((row) => ({
          color: row.color,
          size: row.size,
          quantity: numberOrZero(row.quantity),
        })),
      });
      setEditingUslugaSizeCountsId(0);
      setUslugaSizeCountEdits([]);
      setDoneMsg(t("usluga.sizeCountsSaved"));
      await Promise.all([mutateUslugaCutting(), mutateBundles()]);
    } catch (e: any) {
      setErr(e?.message || t("usluga.actionFailed"));
    } finally {
      setUslugaSizeCountEditBusy(false);
    }
  }

  async function rejectUslugaBatch(recordId: number) {
    const reason = uslugaRejectReason.trim();
    if (!reason) {
      setErr(t("usluga.rejectReason"));
      return;
    }
    setUslugaBatchBusy(recordId);
    setErr("");
    setDoneMsg("");
    try {
      await api.post(`/api/cutting/records/${recordId}/reject-usluga-batch`, { reason });
      setUslugaRejectingId(0);
      setUslugaRejectReason("");
      setDoneMsg(t("usluga.rejected"));
      await Promise.all([mutatePo(), mutateWo(), mutateBatchProgress(), mutateBundles(), mutateUslugaCutting()]);
    } catch (e: any) {
      setErr(e?.message || t("usluga.actionFailed"));
    } finally {
      setUslugaBatchBusy(0);
    }
  }

  async function completeReplacementCutting() {
    const completedPieces = numberOrZero(replacementCompletion.completed_pieces);
    const materialUsed = numberOrZero(replacementCompletion.input_quantity);
    const waitingPieces = Math.max(0, Number(selectedReplacementItem?.waiting_cutting_qty || 0));
    setReplacementCompletionErr("");
    setReplacementCompletionDone("");
    if (!selectedReplacementItem || completedPieces <= 0 || completedPieces > waitingPieces) {
      setReplacementCompletionErr(t("replacement.invalidCompletedQty", { count: waitingPieces.toLocaleString() }));
      return;
    }
    if (!form.fabric_batch_id) {
      setReplacementCompletionErr(t("replacement.selectFabricBatch"));
      return;
    }
    if (materialUsed <= 0) {
      setReplacementCompletionErr(t("replacement.materialUsedRequired"));
      return;
    }

    setReplacementCompletionBusy(true);
    try {
      const result = await api.post("/api/cutting/records", {
        work_order_id: id,
        production_batch_id: selectedReplacementItem.production_batch_id || null,
        fabric_batch_id: form.fabric_batch_id,
        input_quantity: materialUsed,
        input_unit: selectedFabricBatch?.unit || "kg",
        cut_pieces: completedPieces,
        passed_pieces: completedPieces,
        defective_pieces: 0,
        waste_quantity: 0,
        waste_unit: selectedFabricBatch?.unit || "kg",
        layer_material_kg: 0,
        beika_kg: 0,
        material_rolls_used: 0,
        layup_operator_name: form.layup_operator_name.trim() || null,
        notes: "Replacement cutting completed",
        bundles: [],
      }, 120_000);
      const recorded = Math.max(0, Number(result?.replacement_cut_qty || 0));
      setReplacementCompletionDone(t("replacement.cuttingCompleted", { count: recorded.toLocaleString() }));
      setReplacementCompletion((prev) => ({ ...prev, input_quantity: "" }));
      await Promise.all([mutatePo(), mutateWo(), mutateBatchProgress(), mutateBundles(), mutateReplacementStatus()]);
    } catch (e: any) {
      setReplacementCompletionErr(e?.message || t("replacement.cuttingCompleteFailed"));
    } finally {
      setReplacementCompletionBusy(false);
    }
  }

  function beginBundleAdjustment(bundle: any) {
    const recordId = Number(bundle?.cutting_record_id || 0);
    const bundleId = Number(bundle?.id || 0);
    if (!recordId || !bundleId) return;
    setAdjustingBundle({
      bundleId,
      recordId,
      quantity: Math.max(1, numberOrFallback(parseWholeInput(bundle?.quantity || 1, 1), 1)),
      color: String(bundle?.color || ""),
      size: String(bundle?.size || ""),
    });
    setAdjustingBundleErr("");
    setDoneMsg("");
  }

  function showBundleAdjustments() {
    setCreatedBundlesExpanded(true);
    window.requestAnimationFrame(() => {
      document.getElementById("created-bundles-panel")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  async function saveBundleAdjustment() {
    if (!adjustingBundle) return;
    const quantity = Math.max(1, numberOrFallback(adjustingBundle.quantity, 1));
    setAdjustingBundleBusy(true);
    setAdjustingBundleErr("");
    setDoneMsg("");
    try {
      const result = await api.patch(`/api/cutting/records/${adjustingBundle.recordId}/bundle-quantities`, {
        bundles: [{
          id: adjustingBundle.bundleId,
          quantity,
          ...(!isUsluga ? {
            color: adjustingBundle.color.trim(),
            size: adjustingBundle.size.trim(),
          } : {}),
        }],
      });
      const updated: BundleQuantityResponseRow[] = Array.isArray(result?.bundles) ? result.bundles : [];
      const byId = new Map<number, BundleQuantityResponseRow>(updated.map((row) => [Number(row.id || 0), row]));
      setCreatedBundles((prev) => prev.map((row) => {
        const next = byId.get(Number(row?.id || 0));
        return next ? { ...row, quantity: next.quantity, color: next.color ?? row.color, size: next.size ?? row.size } : row;
      }));
      await Promise.all([mutatePo(), mutateWo(), mutateBatchProgress(), mutateBundles()]);
      setAdjustingBundle(null);
      setDoneMsg(t("page.cutting.bundleQuantityUpdated"));
    } catch (e: any) {
      setAdjustingBundleErr(e.message || "Failed to update bundle quantity");
    } finally {
      setAdjustingBundleBusy(false);
    }
  }

  async function beginCuttingDetailsEdit(recordId: number) {
    if (!recordId) return;
    setEditingCuttingDetailsBusy(true);
    setEditingCuttingDetailsErr("");
    setDoneMsg("");
    try {
      const record = await api.get(`/api/cutting/records/${recordId}`);
      setEditingCuttingDetails({
        recordId,
        layer_material_kg: Number(record?.layer_material_kg || 0),
        beika_kg: Number(record?.beika_kg || 0),
        material_rolls_used: Number(record?.material_rolls_used || 0),
        layup_operator_name: String(record?.layup_operator_name || ""),
        notes: String(record?.notes || ""),
      });
    } catch (e: any) {
      setEditingCuttingDetailsErr(e?.message || t("page.cutting.detailsUpdateFailed"));
    } finally {
      setEditingCuttingDetailsBusy(false);
    }
  }

  async function saveCuttingDetailsEdit() {
    if (!editingCuttingDetails) return;
    setEditingCuttingDetailsBusy(true);
    setEditingCuttingDetailsErr("");
    try {
      await api.patch(`/api/cutting/records/${editingCuttingDetails.recordId}`, {
        layer_material_kg: numberOrZero(editingCuttingDetails.layer_material_kg),
        beika_kg: numberOrZero(editingCuttingDetails.beika_kg),
        material_rolls_used: numberOrZero(editingCuttingDetails.material_rolls_used),
        layup_operator_name: editingCuttingDetails.layup_operator_name.trim() || null,
        notes: editingCuttingDetails.notes.trim() || null,
      });
      setEditingCuttingDetails(null);
      setDoneMsg(t("page.cutting.detailsUpdated"));
    } catch (e: any) {
      setEditingCuttingDetailsErr(e?.message || t("page.cutting.detailsUpdateFailed"));
    } finally {
      setEditingCuttingDetailsBusy(false);
    }
  }

  async function deleteCreatedBundle(bundle: any) {
    const bundleId = Number(bundle?.id || 0);
    if (!bundleId) return;
    const confirmed = await dialogs.ask({
      title: t("btn.delete"),
      message: t("page.cutting.deleteBundleConfirm", { bundleNo: bundle.bundle_no || `#${bundleId}` }),
      confirmText: t("btn.delete"),
      tone: "danger",
    });
    if (!confirmed) return;

    setDeletingBundleId(bundleId);
    setAdjustingBundleErr("");
    setDoneMsg("");
    try {
      await api.del(`/api/bundles/${bundleId}`);
      setCreatedBundles((prev) => prev.filter((row) => Number(row?.id || 0) !== bundleId));
      if (adjustingBundle?.bundleId === bundleId) setAdjustingBundle(null);
      await Promise.all([mutatePo(), mutateWo(), mutateBatchProgress(), mutateBundles()]);
      setDoneMsg(t("page.cutting.bundleDeleted", { bundleNo: bundle.bundle_no || `#${bundleId}` }));
    } catch (e: any) {
      setAdjustingBundleErr(e.message || t("page.cutting.bundleDeleteFailed"));
    } finally {
      setDeletingBundleId(0);
    }
  }

  async function completeWithShortage() {
    if (!canCompleteWithShortage) return;
    const confirmed = await dialogs.ask({
      title: t("page.cutting.completeShortage"),
      message: t("page.cutting.completeShortageConfirm", {
        actual: recordedPassedQty.toLocaleString(),
        shortage: cuttingShortageQty.toLocaleString(),
      }),
      confirmText: t("page.cutting.completeShortage"),
    });
    if (!confirmed) return;

    setShortageBusy(true);
    setShortageErr("");
    setDoneMsg("");
    try {
      await api.post(`/api/work-orders/${id}/complete-cutting-shortage`, {});
      await Promise.all([mutateWo(), mutatePo(), mutateBatchProgress()]);
      setDoneMsg(t("page.cutting.shortageCompleted", {
        actual: recordedPassedQty.toLocaleString(),
        shortage: cuttingShortageQty.toLocaleString(),
      }));
    } catch (e: any) {
      setShortageErr(e.message || t("page.cutting.shortageFailed"));
    } finally {
      setShortageBusy(false);
    }
  }

  const orderNo = orderReference({
    order_no: so?.order_no || productInfoPo?.order_no || wo?.order_no,
    sales_order_no: productInfoPo?.sales_order_no || wo?.sales_order_no,
    production_no: productInfoPo?.production_no || wo?.production_no,
    production_order_id: wo?.production_order_id,
  }, `#${id}`);

  return (
    <div>
      <PageHeader
        title={t("page.cutting.title", { id, orderNo })}
        subtitle={wo ? t("page.cutting.subtitle", { op: operationLabel(wo.operation, t), status: statusLabel(wo.status, t) }) : ""}
      />
      <WorkOrderProductInfo
        t={t}
        so={so}
        po={productInfoPo}
        wo={wo}
        model={model}
        customerName={so?.customer_id ? (customerMap.get(so.customer_id) || `#${so.customer_id}`) : null}
        statusText={wo ? statusLabel(wo.status, t) : "-"}
        canEditBreakdown={canEditBreakdown}
        onSaveBreakdown={saveBreakdown}
      />

      {Number(replacementStatus?.waiting_cutting_qty || 0) > 0 && (
        <>
          <div className="border-y border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950">
            <div className="font-semibold">
              {t("replacement.cuttingRequired", {
                count: Number(replacementStatus.waiting_cutting_qty).toLocaleString(),
              })}
            </div>
            <div className="mt-1 text-amber-900">{t("replacement.cuttingHint")}</div>
            {Array.isArray(replacementStatus.items) && replacementStatus.items.length > 1 && (
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-amber-900">
                {replacementStatus.items
                  .filter((row: any) => Number(row.waiting_cutting_qty || 0) > 0)
                  .map((row: any) => (
                    <span key={row.production_batch_id || "order"}>
                      {row.batch_no || t("field.batch")}: {Number(row.waiting_cutting_qty).toLocaleString()}
                    </span>
                  ))}
              </div>
            )}
          </div>
          <section className="card mb-4 rounded-t-none border-t-0 p-4">
            <div className="mb-3">
              <h2 className="text-base font-semibold">{t("replacement.completeCuttingTitle")}</h2>
              <p className="mt-1 text-sm text-slate-600">{t("replacement.completeCuttingHint")}</p>
            </div>
            <div className="grid grid-cols-1 items-end gap-3 md:grid-cols-4">
              {pendingReplacementItems.length > 1 && (
                <div>
                  <label className="label">{t("batch.orderBatch")}</label>
                  <select
                    className="input"
                    value={replacementCompletion.production_batch_id}
                    onChange={(e) => {
                      const batchId = Number(e.target.value || 0);
                      const row = pendingReplacementItems.find((item: any) => Number(item?.production_batch_id || 0) === batchId);
                      setReplacementCompletion((prev) => ({
                        ...prev,
                        production_batch_id: batchId,
                        completed_pieces: Number(row?.waiting_cutting_qty || 0),
                      }));
                    }}
                  >
                    {pendingReplacementItems.map((row: any) => (
                      <option key={row.production_batch_id || "order"} value={Number(row.production_batch_id || 0)}>
                        {row.batch_no || t("field.batch")} ({Number(row.waiting_cutting_qty || 0).toLocaleString()})
                      </option>
                    ))}
                  </select>
                </div>
              )}
              <div>
                <label className="label">{t("field.fabricBatch")}</label>
                <select
                  className="input"
                  value={form.fabric_batch_id}
                  onChange={(e) => {
                    const batch = allSearchableFabricBatches.find((row) => Number(row.id) === Number(e.target.value || 0)) || null;
                    selectFabricBatch(batch);
                  }}
                >
                  <option value={0}>{t("replacement.selectFabricBatchOption")}</option>
                  {allSearchableFabricBatches.slice(0, 100).map((batch) => (
                    <option key={batch.id} value={batch.id}>
                      {fabricBatchCompactLabel(batch)} - {fmtQty(batchAvailableQty(batch))} {batch.unit}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="label">{t("replacement.completedPieces")}</label>
                <input
                  className="input"
                  type="number"
                  min={1}
                  max={Math.max(1, Number(selectedReplacementItem?.waiting_cutting_qty || 1))}
                  value={replacementCompletion.completed_pieces}
                  onChange={(e) => setReplacementCompletion((prev) => ({ ...prev, completed_pieces: parseWholeInput(e.target.value) }))}
                />
              </div>
              <div>
                <label className="label">{t("replacement.materialUsed", { unit: selectedFabricBatch?.unit || "kg" })}</label>
                <input
                  className="input"
                  type="number"
                  min="0"
                  step="0.01"
                  value={replacementCompletion.input_quantity}
                  onChange={(e) => setReplacementCompletion((prev) => ({ ...prev, input_quantity: parseDecimalInput(e.target.value) }))}
                />
              </div>
            </div>
            {replacementCompletionErr && <div className="mt-3 text-sm text-red-600">{replacementCompletionErr}</div>}
            <div className="mt-3">
              <button type="button" className="btn btn-primary" onClick={completeReplacementCutting} disabled={replacementCompletionBusy}>
                {replacementCompletionBusy ? t("common.saving") : t("replacement.markCuttingDone")}
              </button>
            </div>
          </section>
        </>
      )}
      {replacementCompletionDone && (
        <div className="mb-4 border-y border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
          {replacementCompletionDone}
        </div>
      )}

      {!isAlreadyBatched && canCompleteWithShortage && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 border-y border-amber-200 bg-amber-50 px-4 py-3">
          <div className="min-w-0 text-sm text-amber-950">
            {t("page.cutting.shortageReady", {
              actual: recordedPassedQty.toLocaleString(),
              planned: cuttingPlanQty.toLocaleString(),
              shortage: cuttingShortageQty.toLocaleString(),
            })}
          </div>
          <button type="button" className="btn btn-primary shrink-0" onClick={completeWithShortage} disabled={shortageBusy}>
            {shortageBusy ? t("common.saving") : t("page.cutting.completeShortage")}
          </button>
        </div>
      )}
      {!isAlreadyBatched && shortageErr && <div className="mb-4 text-sm text-red-600">{shortageErr}</div>}

      {isAlreadyBatched && (
        <div className="card mb-4 p-4">
          <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="text-base font-semibold">{t("batch.managedInsideWorkOrder")}</div>
              <div className="mt-1 text-sm text-slate-600">
                {t("batch.recordAction", { operation: operationLabel("cutting", t).toLowerCase() })}
              </div>
              {isUsluga && (
                <div className="mt-1 text-sm text-slate-600">{t("batch.editBeforeBundles")}</div>
              )}
            </div>
            <button type="button" className="btn" onClick={openExtraBatchForm} disabled={extraBatchBusy}>
              {t("batch.addExtraBatch")}
            </button>
          </div>
          <div className="overflow-x-auto">
            <table className="table text-sm">
              <thead>
                <tr>
                  <th>{t("field.batch")}</th>
                  <th>{t("statusValue.planned")}</th>
                  <th>{t("field.remaining")}</th>
                  <th>{t("page.processes.progress")}</th>
                  {!isUsluga && <th>{t("batch.startDate")}</th>}
                  {!isUsluga && <th>{t("field.deadline")}</th>}
                  {!isUsluga && <th>{t("field.notes")}</th>}
                  <th>{t("field.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {batchItems.map((row: any) => {
                  const isEditing = editingBatchId === Number(row.id);
                  const quantityEditable = Boolean(row.quantity_editable ?? row.editable);
                  return (
                    <tr key={row.id}>
                      <td>
                        {isEditing ? (
                          <div className="min-w-52">
                            <div className="mb-1 text-xs text-slate-500">{formatBatchSerial(row, po?.id)}</div>
                            <input
                              className="input"
                              aria-label={t("common.name")}
                              maxLength={128}
                              value={batchPlanEdit.name}
                              onChange={(event) => setBatchPlanEdit((current) => ({ ...current, name: event.target.value }))}
                            />
                          </div>
                        ) : (
                          <>
                            <div className="font-medium">{formatBatchLabel(row, po?.id)}</div>
                            <div className="text-xs text-slate-500">{formatBatchSerial(row, po?.id)}</div>
                          </>
                        )}
                      </td>
                      <td>
                        {isEditing ? (
                          <div className="w-40">
                            <input
                              className="input w-28"
                              aria-label={t("batch.quantity")}
                              type="number"
                              min={1}
                              disabled={!quantityEditable}
                              value={batchPlanEdit.planned_quantity}
                              onChange={(event) => setBatchPlanEdit((current) => ({
                                ...current,
                                planned_quantity: parseWholeInput(event.target.value),
                              }))}
                            />
                            {!quantityEditable && (
                              <div className="mt-1 text-xs text-slate-500">{t("batch.lockedAfterBundles")}</div>
                            )}
                          </div>
                        ) : row.planned_quantity}
                      </td>
                      <td>{row.remaining_quantity}</td>
                      <td>{row.progress_pct}%</td>
                      {!isUsluga && (
                        <td>
                          {isEditing ? (
                            <input
                              className="input min-w-36"
                              type="date"
                              value={batchPlanEdit.start_date}
                              onChange={(event) => setBatchPlanEdit((current) => ({ ...current, start_date: event.target.value }))}
                            />
                          ) : dateInputValue(row.start_date) || "-"}
                        </td>
                      )}
                      {!isUsluga && (
                        <td>
                          {isEditing ? (
                            <input
                              className="input min-w-36"
                              type="date"
                              value={batchPlanEdit.deadline}
                              onChange={(event) => setBatchPlanEdit((current) => ({ ...current, deadline: event.target.value }))}
                            />
                          ) : dateInputValue(row.deadline) || "-"}
                        </td>
                      )}
                      {!isUsluga && (
                        <td>
                          {isEditing ? (
                            <input
                              className="input min-w-44"
                              value={batchPlanEdit.notes}
                              onChange={(event) => setBatchPlanEdit((current) => ({ ...current, notes: event.target.value }))}
                            />
                          ) : row.notes || "-"}
                        </td>
                      )}
                      <td>
                          {isEditing ? (
                            <div className="flex gap-2">
                              <button
                                type="button"
                                className="btn btn-primary"
                                disabled={batchPlanEditBusy}
                                onClick={() => saveBatchPlanEdit(row)}
                              >
                                {batchPlanEditBusy ? t("common.saving") : t("btn.save")}
                              </button>
                              <button type="button" className="btn" disabled={batchPlanEditBusy} onClick={cancelBatchPlanEdit}>
                                {t("btn.cancel")}
                              </button>
                            </div>
                          ) : (
                            <div className="flex items-center gap-2">
                              <button
                                type="button"
                                className="btn"
                                disabled={batchPlanEditBusy || row.name_editable === false}
                                onClick={() => startBatchPlanEdit(row)}
                              >
                                {t("btn.edit")}
                              </button>
                              {!quantityEditable && (
                                <span className="text-xs text-slate-500">{t("batch.lockedAfterBundles")}</span>
                              )}
                            </div>
                          )}
                      </td>
                    </tr>
                  );
                })}
                {batchItems.length === 0 && (
                  <tr>
                    <td colSpan={isUsluga ? 5 : 8} className="text-slate-500">{t("batch.noProgressYet")}</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          {!isUsluga && <div className="mt-2 text-sm text-[#56503f]">{t("page.cutting.postStartEditHint")}</div>}
          {batchPlanEditErr && <div className="mt-2 text-sm text-red-600">{batchPlanEditErr}</div>}
          {canCompleteWithShortage && (
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-t border-amber-200 pt-3">
              <div className="min-w-0 text-sm text-[#56503f]">
                {t("page.cutting.shortageReady", {
                  actual: recordedPassedQty.toLocaleString(),
                  planned: cuttingPlanQty.toLocaleString(),
                  shortage: cuttingShortageQty.toLocaleString(),
                })}
              </div>
              <button type="button" className="btn btn-primary shrink-0" onClick={completeWithShortage} disabled={shortageBusy}>
                {shortageBusy ? t("common.saving") : t("page.cutting.completeShortage")}
              </button>
            </div>
          )}
          {shortageErr && <div className="mt-2 text-sm text-red-600">{shortageErr}</div>}
          {extraBatchOpen && (
            <div className="mt-4 border-t border-[#ecebe3] pt-4">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-[1fr_140px_160px_160px_1fr_auto] xl:items-end">
                <div>
                  <label className="label">{t("field.batch")}</label>
                  <input className="input" value={extraBatch.name} onChange={(e) => updateExtraBatch({ name: e.target.value })} />
                </div>
                <div>
                  <label className="label">{t("batch.quantity")}</label>
                  <input
                    className="input"
                    type="number"
                    min={1}
                    value={extraBatch.planned_quantity}
                    onChange={(e) => updateExtraBatch({ planned_quantity: parseWholeInput(e.target.value) })}
                  />
                </div>
                <div>
                  <label className="label">{t("batch.startDate")}</label>
                  <input className="input" type="date" value={extraBatch.start_date} onChange={(e) => updateExtraBatch({ start_date: e.target.value })} />
                </div>
                <div>
                  <label className="label">{t("field.deadline")}</label>
                  <input className="input" type="date" value={extraBatch.deadline} onChange={(e) => updateExtraBatch({ deadline: e.target.value })} />
                </div>
                <div>
                  <label className="label">{t("field.notes")}</label>
                  <input className="input" value={extraBatch.notes} onChange={(e) => updateExtraBatch({ notes: e.target.value })} />
                </div>
                <div className="flex gap-2">
                  <button type="button" className="btn btn-primary" onClick={saveExtraBatch} disabled={extraBatchBusy}>
                    {extraBatchBusy ? t("common.saving") : t("btn.save")}
                  </button>
                  <button type="button" className="btn" onClick={() => setExtraBatchOpen(false)} disabled={extraBatchBusy}>
                    {t("btn.cancel")}
                  </button>
                </div>
              </div>
              {extraBatchErr && <div className="mt-2 text-sm text-red-600">{extraBatchErr}</div>}
            </div>
          )}
        </div>
      )}

      {canSplitHere && (
        <div className="card mb-4 p-4">
          <div className="mb-2 text-base font-semibold">{t("batch.defineInsideWorkOrder")}</div>
          <div className="mb-3 text-sm text-slate-600">
            {t("batch.defineHint")}
          </div>
          <div className="grid grid-cols-1 md:grid-cols-[220px_auto] gap-3 items-end mb-3">
            <div>
              <label className="label">{t("batch.maxPiecesPerBatch")}</label>
              <input
                className="input"
                type="number"
                min={1}
                value={splitMax}
                onChange={(e) => setSplitMax(parseWholeInput(e.target.value))}
              />
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                className="btn"
                onClick={() => setSplitRows(autoSplitRows(Number(wo?.planned_output_qty || po?.planned_quantity || 0), numberOrFallback(splitMax, 1)))}
                disabled={splitBusy}
              >
                {t("batch.autoSplit")}
              </button>
              <button type="button" className="btn" onClick={addSplitRow} disabled={splitBusy}>{t("batch.addBatch")}</button>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="table text-sm">
              <thead>
                <tr>
                  <th>{t("field.batch")}</th>
                  <th>{t("batch.quantity")}</th>
                  <th>{t("batch.startDate")}</th>
                  <th>{t("field.deadline")}</th>
                  <th>{t("field.notes")}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {splitRows.map((row, index) => (
                  <tr key={index}>
                    <td>
                      <input className="input min-w-32" value={row.name} onChange={(e) => updateSplitRow(index, { name: e.target.value })} />
                    </td>
                    <td>
                      <input
                        className="input w-28"
                        type="number"
                        min={1}
                        value={row.planned_quantity}
                        onChange={(e) => updateSplitRow(index, { planned_quantity: parseWholeInput(e.target.value) })}
                      />
                    </td>
                    <td>
                      <input className="input" type="date" value={row.start_date} onChange={(e) => updateSplitRow(index, { start_date: e.target.value })} />
                    </td>
                    <td>
                      <input className="input" type="date" value={row.deadline} onChange={(e) => updateSplitRow(index, { deadline: e.target.value })} />
                    </td>
                    <td>
                      <input className="input min-w-44" value={row.notes} onChange={(e) => updateSplitRow(index, { notes: e.target.value })} />
                    </td>
                    <td>
                      <button type="button" className="btn btn-danger" onClick={() => removeSplitRow(index)} disabled={splitRows.length <= 1 || splitBusy}>
                        {t("btn.remove")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-2 text-sm">
            {t("batch.totalInBatches")} <span className="font-semibold">{splitTotal}</span> / {Number(wo?.planned_output_qty || po?.planned_quantity || 0)}
          </div>
          {splitErr && <div className="mt-2 text-sm text-red-600">{splitErr}</div>}
          <div className="mt-3">
            <button type="button" className="btn btn-primary" onClick={splitIntoBatches} disabled={splitBusy}>
              {splitBusy ? t("common.saving") : t("batch.saveBatchPlan")}
            </button>
          </div>
        </div>
      )}

      {visibleBundles.length > 0 && (
        <div className="card p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="font-medium">{t("page.cutting.bundlesCreated")}</h3>
              <div className="mt-1 text-sm text-[#56503f]">
                {visibleBundles.length} {t("nav.bundles").toLowerCase()} · {visibleBundleQuantity.toLocaleString()} {t("field.quantity").toLowerCase()}
              </div>
            </div>
            <button
              type="button"
              className="btn btn-primary"
              disabled={adjustableBundleCount === 0}
              onClick={showBundleAdjustments}
            >
              {t("page.cutting.adjustBundleQuantities")}
            </button>
          </div>
          {adjustableBundleCount === 0 && (
            <div className="mt-2 text-sm text-[#6f684f]">{t("page.cutting.adjustUnavailable")}</div>
          )}
        </div>
      )}

      {isUsluga && (
        <section className="card mb-4 p-4">
          <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold">{t("usluga.cuttingBatches")}</h2>
              <p className="mt-1 text-sm text-[#6f684f]">{t("usluga.cuttingMaterialHint")}</p>
            </div>
            <button
              type="button"
              className="btn"
              onClick={() => {
                setForm((prev) => ({ ...prev, input_quantity: "", cut_pieces: "", report_piece_count: "", waste_quantity: "", layer_material_kg: "", beika_kg: "", material_rolls_used: "", notes: "" }));
                document.getElementById("usluga-cutting-entry")?.scrollIntoView({ behavior: "smooth", block: "start" });
              }}
            >
              {t("usluga.addAnotherBatch")}
            </button>
          </div>
          <div className="overflow-x-auto">
            <table className="table text-sm">
              <thead>
                <tr>
                  <th>{t("usluga.cuttingBatchNo")}</th>
                  <th>{t("usluga.selectCuttingFabric")}</th>
                  <th>{t("field.batch")}</th>
                  <th>{t("field.inputQty")}</th>
                  <th>{t("usluga.pieces")}</th>
                  <th>{t("nav.bundles")}</th>
                  <th>{t("usluga.approvalStatus")}</th>
                  <th>{t("field.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {uslugaCuttingBatches.map((row: any) => {
                  const pending = row.approval_status === "pending";
                  const canApprove = can(me, "*", "usluga.cutting.approve", "usluga.manage");
                  const sizeCountRows = Array.isArray(row.size_counts) ? row.size_counts : [];
                  const sizeCountEditTotal = uslugaSizeCountEdits.reduce(
                    (sum, sizeRow) => sum + numberOrZero(sizeRow.quantity),
                    0,
                  );
                  const requiredSizeCountTotal = sizeCountRows.reduce(
                    (sum: number, sizeRow: any) => sum + Number(sizeRow.quantity || 0),
                    0,
                  );
                  return (
                    <Fragment key={row.id}>
                    <tr>
                      <td className="font-medium">{row.cutting_batch_no || `CUT-${row.id}`}</td>
                      <td>
                        <div>{row.material_name || "-"}</div>
                        <div className="text-xs text-[#6f684f]">
                          {row.material_role === "main" ? t("usluga.mainFabric") : t("usluga.secondaryFabric")}
                        </div>
                      </td>
                      <td>{row.production_batch_no || "-"}</td>
                      <td className="min-w-56">
                        <div className="font-medium">
                          {fmtQty(row.input_quantity)} {row.input_unit || "kg"}
                        </div>
                        <div className="mt-1 space-y-0.5 text-xs text-[#6f684f]">
                          <div>
                            {t("field.layerMaterialKg")}: {fmtQty(row.layer_material_kg)} kg
                          </div>
                          <div>
                            {t("field.beikaKg")}: {fmtQty(row.beika_kg)} kg
                          </div>
                          <div>
                            {t("field.materialRollsUsed")}: {fmtQty(row.material_rolls_used)}
                          </div>
                          <div>
                            {t("field.wasteQty")}: {fmtQty(row.waste_quantity)} {row.waste_unit || "kg"}
                          </div>
                          {row.layup_operator_name && (
                            <div>{t("field.layupOperator")}: {row.layup_operator_name}</div>
                          )}
                          {row.notes && <div>{t("field.notes")}: {row.notes}</div>}
                        </div>
                      </td>
                      <td className="min-w-36">
                        {row.material_role === "secondary" && editingReportPiecesId === Number(row.id) ? (
                          <div className="space-y-2">
                            <input
                              className="input h-9 w-28"
                              type="number"
                              min={0}
                              step={1}
                              aria-label={t("usluga.reportPieces")}
                              value={reportPiecesEdit}
                              onChange={(event) => setReportPiecesEdit(parseWholeInput(event.target.value))}
                            />
                            <div className="flex items-center gap-2">
                              <button
                                type="button"
                                className="text-brand-600 hover:underline disabled:opacity-50"
                                disabled={reportPiecesEditBusy}
                                onClick={() => saveReportPieces(Number(row.id))}
                              >
                                {t("common.save")}
                              </button>
                              <button
                                type="button"
                                className="text-[#6f684f] hover:underline disabled:opacity-50"
                                disabled={reportPiecesEditBusy}
                                onClick={() => {
                                  setEditingReportPiecesId(0);
                                  setReportPiecesEdit("");
                                }}
                              >
                                {t("common.cancel")}
                              </button>
                            </div>
                          </div>
                        ) : (
                          <>
                            <div>
                              {Number((row.material_role === "secondary" ? row.report_piece_count : row.cut_pieces) || 0).toLocaleString()}
                            </div>
                            {row.material_role === "secondary" && (
                              <>
                                <div className="text-xs text-[#6f684f]">{t("usluga.reportOnly")}</div>
                                {can(me, "*", "cutting.records") && (
                                  <button
                                    type="button"
                                    className="mt-1 text-brand-600 hover:underline"
                                    onClick={() => {
                                      setEditingReportPiecesId(Number(row.id));
                                      setReportPiecesEdit(Number(row.report_piece_count || 0));
                                    }}
                                  >
                                    {t("common.edit")}
                                  </button>
                                )}
                              </>
                            )}
                          </>
                        )}
                      </td>
                      <td>{Number(row.bundle_count || 0).toLocaleString()}</td>
                      <td>
                        <span className="badge">
                          {row.approval_status === "approved"
                            ? t("usluga.approved")
                            : row.approval_status === "rejected"
                              ? t("usluga.rejected")
                              : t("usluga.pendingApproval")}
                        </span>
                        {row.rejection_reason && <div className="mt-1 max-w-48 text-xs text-red-700">{row.rejection_reason}</div>}
                      </td>
                      <td>
                        <div className="flex min-w-52 flex-wrap items-center gap-2">
                          {row.material_role === "main" && Number(row.bundle_count || 0) > 0 && (
                            <>
                              <button
                                type="button"
                                className="text-brand-600 hover:underline"
                                onClick={() => {
                                  const bundleIds = Array.isArray(row.bundle_ids) ? row.bundle_ids.join(",") : "";
                                  const query = bundleIds ? `?bundle_ids=${encodeURIComponent(bundleIds)}` : "";
                                  api.openLabel(`/api/cutting/records/${row.id}/production-sheet${query}`);
                                }}
                              >
                                {t("page.cutting.printProductionSheet")}
                              </button>
                              {can(me, "*", "cutting.records") && sizeCountRows.length > 0 && (
                                <button
                                  type="button"
                                  className="text-brand-600 hover:underline"
                                  onClick={() => {
                                    setEditingUslugaSizeCountsId(Number(row.id));
                                    setUslugaSizeCountEdits(sizeCountRows.map((sizeRow: any) => ({
                                      color: String(sizeRow.color || ""),
                                      size: String(sizeRow.size || ""),
                                      quantity: Number(sizeRow.quantity || 0),
                                      bundle_count: Number(sizeRow.bundle_count || 0),
                                    })));
                                  }}
                                >
                                  {t("common.edit")}
                                </button>
                              )}
                            </>
                          )}
                          {pending && canApprove && (
                            <>
                              <button
                                type="button"
                                className="text-brand-600 hover:underline disabled:opacity-50"
                                disabled={uslugaBatchBusy === row.id}
                                onClick={() => approveUslugaBatch(Number(row.id))}
                              >
                                {t("usluga.approveBatch")}
                              </button>
                              <button
                                type="button"
                                className="text-red-600 hover:underline disabled:opacity-50"
                                disabled={uslugaBatchBusy === row.id}
                                onClick={() => {
                                  setUslugaRejectingId(Number(row.id));
                                  setUslugaRejectReason("");
                                }}
                              >
                                {t("usluga.rejectBatch")}
                              </button>
                            </>
                          )}
                        </div>
                        {uslugaRejectingId === Number(row.id) && pending && (
                          <div className="mt-2 flex min-w-72 items-center gap-2">
                            <input
                              className="input"
                              maxLength={500}
                              placeholder={t("usluga.rejectReason")}
                              value={uslugaRejectReason}
                              onChange={(event) => setUslugaRejectReason(event.target.value)}
                            />
                            <button type="button" className="btn btn-danger" disabled={uslugaBatchBusy === row.id} onClick={() => rejectUslugaBatch(Number(row.id))}>
                              {t("usluga.rejectBatch")}
                            </button>
                            <button type="button" className="btn" onClick={() => setUslugaRejectingId(0)}>{t("btn.cancel")}</button>
                          </div>
                        )}
                      </td>
                    </tr>
                    {editingUslugaSizeCountsId === Number(row.id) && row.material_role === "main" && (
                      <tr>
                        <td colSpan={8} className="bg-[#faf9f5]">
                          <div className="flex flex-wrap items-end gap-3 py-2">
                            {uslugaSizeCountEdits.map((sizeRow, index) => (
                              <label key={`${sizeRow.color}-${sizeRow.size}`} className="block min-w-40">
                                <span className="label">{sizeRow.color} / {sizeRow.size}</span>
                                <input
                                  className="input h-9 w-40"
                                  type="number"
                                  min={sizeRow.bundle_count}
                                  step={1}
                                  value={sizeRow.quantity}
                                  onChange={(event) => setUslugaSizeCountEdits((current) => current.map((entry, entryIndex) => (
                                    entryIndex === index
                                      ? { ...entry, quantity: parseWholeInput(event.target.value) }
                                      : entry
                                  )))}
                                />
                              </label>
                            ))}
                            <div className="pb-1 text-sm text-[#6f684f]">
                              {t("usluga.sizeCountTotal", {
                                current: sizeCountEditTotal.toLocaleString(),
                                required: requiredSizeCountTotal.toLocaleString(),
                              })}
                            </div>
                            <button
                              type="button"
                              className="btn btn-primary"
                              disabled={uslugaSizeCountEditBusy || sizeCountEditTotal !== requiredSizeCountTotal}
                              onClick={() => saveUslugaSizeCounts(Number(row.id))}
                            >
                              {t("common.save")}
                            </button>
                            <button
                              type="button"
                              className="btn"
                              disabled={uslugaSizeCountEditBusy}
                              onClick={() => {
                                setEditingUslugaSizeCountsId(0);
                                setUslugaSizeCountEdits([]);
                              }}
                            >
                              {t("common.cancel")}
                            </button>
                          </div>
                          <p className="pb-2 text-xs text-[#6f684f]">{t("usluga.sizeCountEditHint")}</p>
                        </td>
                      </tr>
                    )}
                    </Fragment>
                  );
                })}
                {uslugaCuttingBatches.length === 0 && (
                  <tr><td colSpan={8} className="text-[#6f684f]">{t("usluga.noCuttingBatches")}</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <form id={isUsluga ? "usluga-cutting-entry" : undefined} onSubmit={submit} className="card space-y-5 p-6">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
          {isAlreadyBatched && (
            <div>
              <label className="label">{t("batch.orderBatch")}</label>
              <select
                className="input"
                value={form.production_batch_id}
                onChange={(e) => setForm({ ...form, production_batch_id: Number(e.target.value) })}
              >
                <option value={0}>{t("batch.selectBatch")}</option>
                {(po?.batches || []).map((b: any) => (
                  <option key={b.id} value={b.id}>
                    {formatBatchLabel(b, po?.id)} ({b.planned_quantity})
                  </option>
                ))}
              </select>
            </div>
          )}
          {hasPlannedMaterials ? (
            <div className="md:col-span-4">
              <div className="mb-3">
                <h2 className="text-sm font-semibold text-[#393528]">{t("page.cutting.materialUsage")}</h2>
                <p className="mt-0.5 text-xs text-[#8a8472]">{t("page.cutting.materialUsageHelp")}</p>
              </div>
              <div className="divide-y divide-[#ecebe3] rounded-md border border-[#e3e0d5]">
                {cuttingMaterials.map((material, index) => {
                  const batch = plannedMaterialBatchLookup.get(material.stock_batch_id);
                  const reservation = reservationForOrder(batch, po?.id);
                  return (
                    <div
                      key={material.stock_batch_id}
                      className="grid grid-cols-1 gap-3 p-3 md:grid-cols-[minmax(0,1fr)_150px_150px] md:items-end"
                    >
                      <div>
                        <div className="text-sm font-medium text-[#14110b]">
                          {batch
                            ? compactParts([batch.item_sku, batch.item_name]) || t("page.cutting.itemId", { id: batch.item_id })
                            : `${t("field.fabricBatch")} #${material.stock_batch_id}`}
                        </div>
                        <div className="mt-1 text-xs text-[#6f684f]">
                          {batch?.batch_no ? `${t("field.batch")} ${batch.batch_no}` : `${t("field.batch")} #${material.stock_batch_id}`}
                          {" · "}
                          {t("page.cutting.plannedAmount")}: {fmtQty(material.planned_quantity)} {material.unit}
                        </div>
                        {batch && (
                          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-[#8a8472]">
                            <span>{t("field.available")}: {fmtQty(batchAvailableQty(batch))} {batch.unit}</span>
                            <span>{t("field.reserved")}: {fmtQty(batch.reserved_quantity)} {batch.unit}</span>
                            {reservation && (
                              <span>{t("page.cutting.forThisOrder")}: {fmtQty(reservation.remaining_quantity)} {reservation.unit || batch.unit}</span>
                            )}
                          </div>
                        )}
                      </div>
                      <div>
                        <label className="label" htmlFor={`cutting-material-${material.stock_batch_id}`}>
                          {t("page.cutting.actualAmountUsed")}
                        </label>
                        <input
                          id={`cutting-material-${material.stock_batch_id}`}
                          className="input"
                          type="number"
                          min={0}
                          step="0.01"
                          value={material.quantity}
                          onChange={(e) => {
                            const quantity = parseDecimalInput(e.target.value);
                            setCuttingMaterials((current) => current.map((row, rowIndex) => (
                              rowIndex === index ? { ...row, quantity } : row
                            )));
                            if (index === 0) {
                              setPassportAutofillField("input_quantity", quantity);
                            }
                          }}
                          required
                        />
                      </div>
                      <div>
                        <label className="label">{t("field.inputUnit")}</label>
                        <input className="input" value={material.unit} readOnly />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ) : !isUsluga ? <div className="md:col-span-2">
            <label className="label">{t("field.fabricBatch")}</label>
            <div
              className="relative"
              onBlur={(e) => {
                if (!e.currentTarget.contains(e.relatedTarget as Node | null)) {
                  setFabricPickerOpen(false);
                  setFabricSearch("");
                }
              }}
            >
              <input
                className="input pr-10"
                role="combobox"
                aria-expanded={fabricPickerOpen}
                aria-controls={fabricListboxId}
                value={fabricPickerOpen ? fabricSearch : selectedFabricBatch ? fabricBatchCompactLabel(selectedFabricBatch) : ""}
                placeholder={t("page.cutting.searchMaterialBatch")}
                onFocus={() => {
                  setFabricPickerOpen(true);
                  setFabricSearch("");
                }}
                onChange={(e) => {
                  setFabricSearch(e.target.value);
                  setFabricPickerOpen(true);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Escape") {
                    setFabricPickerOpen(false);
                    setFabricSearch("");
                  }
                  if (e.key === "Enter" && fabricPickerOpen && fabricPickerOptions[0]) {
                    e.preventDefault();
                    selectFabricBatch(fabricPickerOptions[0]);
                  }
                }}
              />
              <button
                type="button"
                className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-[#6f684f]"
                onClick={() => {
                  setFabricPickerOpen((open) => !open);
                  setFabricSearch("");
                }}
              >
                {fabricPickerOpen ? t("common.close") : t("common.search")}
              </button>
              {fabricPickerOpen && (
                <div id={fabricListboxId} role="listbox" className="absolute z-30 mt-1 max-h-72 w-full overflow-y-auto rounded-md border border-[#d8d2c3] bg-white shadow-sm">
                  {fabricPickerOptions.map((batch) => {
                    const isSelected = Number(batch.id || 0) === Number(form.fabric_batch_id || 0);
                    const unit = String(batch.unit || "").trim();
                    return (
                      <button
                        key={batch.id}
                        type="button"
                        className={`w-full border-b border-[#ecebe3] px-3 py-2 text-left last:border-b-0 hover:bg-[#f6f3ea] ${isSelected ? "bg-[#f6f3ea]" : ""}`}
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => selectFabricBatch(batch)}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="break-words text-sm font-medium text-[#14110b]">
                              {compactParts([batch.item_sku, batch.item_name]) || t("page.cutting.itemId", { id: batch.item_id })}
                            </div>
                            <div className="mt-0.5 break-words text-xs text-[#6f684f]">
                              {compactParts([
                                batch.batch_no ? `${t("field.batch")} ${batch.batch_no}` : `${t("field.batch")} #${batch.id}`,
                                batch.color ? `${t("common.color")} ${batch.color}` : null,
                                batch.color_code ? `${t("common.code")} ${batch.color_code}` : null,
                                batch.warehouse_name,
                              ]).replace(/, /g, " - ")}
                            </div>
                          </div>
                          <div className="shrink-0 text-right text-xs text-[#56503f]">
                            <div className="font-medium text-[#14110b]">{fmtQty(batchAvailableQty(batch))} {unit}</div>
                            {Number(batch.cost_per_unit || 0) > 0 && (
                              <div>{fmtQty(batch.cost_per_unit)} / {unit || "unit"}</div>
                            )}
                          </div>
                        </div>
                      </button>
                    );
                  })}
                  {fabricPickerOptions.length === 0 && (
                    <div className="px-3 py-2 text-sm text-[#6f684f]">{t("page.cutting.noMaterialBatch")}</div>
                  )}
                </div>
              )}
            </div>
            {selectedFabricBatch && (
              <div className="mt-2 rounded-md border border-[#ecebe3] bg-[#fbfaf6] px-3 py-2 text-xs text-[#56503f]">
                <div className="font-medium text-[#14110b]">
                  {compactParts([selectedFabricBatch.item_sku, selectedFabricBatch.item_name]) || t("page.cutting.itemId", { id: selectedFabricBatch.item_id })}
                </div>
                <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
                  <span>{t("field.available")}: {fmtQty(batchAvailableQty(selectedFabricBatch))} {selectedFabricBatch.unit}</span>
                  <span>{t("page.cutting.onHand")}: {fmtQty(selectedFabricBatch.quantity)} {selectedFabricBatch.unit}</span>
                  <span>{t("field.reserved")}: {fmtQty(selectedFabricBatch.reserved_quantity)} {selectedFabricBatch.unit}</span>
                  {selectedFabricReservation && (
                    <span>{t("page.cutting.forThisOrder")}: {fmtQty(selectedFabricReservation.remaining_quantity)} {selectedFabricReservation.unit || selectedFabricBatch.unit}</span>
                  )}
                  {Number(selectedFabricBatch.cost_per_unit || 0) > 0 && (
                    <span>{t("common.price")}: {fmtQty(selectedFabricBatch.cost_per_unit)} / {selectedFabricBatch.unit || t("common.unit")}</span>
                  )}
                  {selectedFabricBatch.warehouse_name && <span>{selectedFabricBatch.warehouse_name}</span>}
                  {selectedFabricBatch.qc_status && <span>{t("field.qc")}: {selectedFabricBatch.qc_status}</span>}
                </div>
              </div>
            )}
            {!selectedFabricBatch && po && materialBomRows.length > 0 && fabricBatches.length === 0 && (
              <div className="mt-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                {t("page.cutting.noMatchingBatches", { material: requiredMaterialNames || t("page.cutting.thisModelBom") })}
              </div>
            )}
          </div> : (
            <div className="md:col-span-2">
              <label className="label">{t("usluga.selectCuttingFabric")}</label>
              <select
                className="input"
                value={form.model_bom_id}
                onChange={(event) => setForm({ ...form, model_bom_id: Number(event.target.value || 0), cut_pieces: "", report_piece_count: "" })}
              >
                <option value={0}>{t("usluga.selectCuttingFabric")}</option>
                {uslugaFabricRows.map((row: any) => (
                  <option key={row.id} value={row.id}>
                    {row.material_name} — {row.material_role === "main" ? t("usluga.mainFabric") : t("usluga.secondaryFabric")}
                  </option>
                ))}
              </select>
              <div className="mt-2 border border-[#dedbd0] bg-[#fbfaf6] px-3 py-2 text-sm text-[#56503f]">
                {isSecondaryUslugaFabric ? t("usluga.secondaryReportOnly") : t("usluga.cuttingMaterialHint")}
              </div>
            </div>
          )}
          {!hasPlannedMaterials && <div>
            <label className="label">{t("field.inputQty")}</label>
            <input className="input" type="number" step="0.01" value={form.input_quantity} onChange={(e) => setPassportAutofillField("input_quantity", parseDecimalInput(e.target.value))} />
          </div>}
          {!hasPlannedMaterials && <div>
            <label className="label">{t("field.inputUnit")}</label>
            <input className="input" value={form.input_unit} onChange={(e) => setForm({ ...form, input_unit: e.target.value })} />
          </div>}
          <div>
            <label className="label">{t("field.layerMaterialKg")}</label>
            <input className="input" type="number" step="0.01" value={form.layer_material_kg} onChange={(e) => setPassportAutofillField("layer_material_kg", parseDecimalInput(e.target.value))} />
          </div>
          <div>
            <label className="label">{t("field.beikaKg")}</label>
            <input className="input" type="number" step="0.01" value={form.beika_kg} onChange={(e) => setForm({ ...form, beika_kg: parseDecimalInput(e.target.value) })} />
          </div>
          <div>
            <label className="label">{t("field.materialRollsUsed")}</label>
            <input className="input" type="number" step="0.01" value={form.material_rolls_used} onChange={(e) => setPassportAutofillField("material_rolls_used", parseDecimalInput(e.target.value))} />
          </div>
          <div>
            <label className="label">{t("field.layupOperator")}</label>
            <input
              className="input"
              value={form.layup_operator_name}
              maxLength={128}
              autoComplete="off"
              onChange={(e) => setPassportAutofillField("layup_operator_name", e.target.value)}
            />
          </div>
          {!isSecondaryUslugaFabric && <div>
            <label className="label">{t("field.cutPieces")}</label>
            <input className="input" type="number" value={form.cut_pieces} onChange={(e) => setPassportAutofillField("cut_pieces", parseWholeInput(e.target.value))} />
          </div>}
          {isSecondaryUslugaFabric && <div>
            <label className="label">{t("usluga.reportPieces")}</label>
            <input
              className="input"
              type="number"
              min={0}
              step={1}
              value={form.report_piece_count}
              onChange={(event) => setForm({ ...form, report_piece_count: parseWholeInput(event.target.value) })}
            />
          </div>}
          <div>
            <label className="label">{t("field.wasteQty")}</label>
            <input
              className="input"
              type="number"
              step="0.01"
              value={form.waste_quantity}
              onChange={(e) => {
                setWastePickedManually(true);
                setForm({ ...form, waste_quantity: parseDecimalInput(e.target.value) });
              }}
            />
          </div>
          <div>
            <label className="label">{t("field.wasteUnit")}</label>
            <input className="input" value={form.waste_unit} onChange={(e) => setForm({ ...form, waste_unit: e.target.value })} />
          </div>
        </div>

        {!isSecondaryUslugaFabric && <div>
          <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
            <h3 className="font-medium">{t("page.cutting.bundlePlan")}</h3>
            <div className="flex flex-wrap items-center gap-3">
              <label className="flex items-center gap-2 text-sm font-medium text-[#56503f]">
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-[#19140d]"
                  checked={applyBundleColumnToAll}
                  onChange={(e) => setApplyBundleColumnToAll(e.target.checked)}
                />
                <span>{t("page.cutting.applyEditedColumnToAll")}</span>
              </label>
              <button type="button" className="btn" onClick={addB}>{t("btn.addBundleLine")}</button>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="table">
            <thead>
              <tr>
                <th>{t("field.color")}</th>
                <th>{t("field.size")}</th>
                <th>{t("field.bundleQty")}</th>
                <th>{t("field.count")}</th>
                <th>{t("field.sewingFactory")}</th>
                <th>{t("field.next")}</th>
                <th>{t("field.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {bundles.map((b, i) => (
                <tr key={i}>
                  <td><input className="input" value={b.color} onChange={(e) => setB(i, { color: e.target.value })} /></td>
                  <td><input className="input" value={b.size} onChange={(e) => setB(i, { size: e.target.value })} /></td>
                  <td><input className="input" type="number" value={b.quantity} onChange={(e) => setBQty(i, e.target.value)} /></td>
                  <td><input className="input" type="number" value={b.count} onChange={(e) => setB(i, { count: parseWholeInput(e.target.value) })} /></td>
                  <td>
                    <select className="input" disabled={isUsluga} value={isUsluga ? "eco_cotton" : (b.sewing_factory || "milana")} onChange={(e) => setB(i, { sewing_factory: e.target.value as SewingFactory })}>
                      <option value="milana">{t("factory.milana")}</option>
                      <option value="besttex">{t("factory.besttex")}</option>
                      <option value="eco_cotton">{t("factory.ecoCotton")}</option>
                    </select>
                  </td>
                  <td>
                    <select className="input" disabled={isUsluga} value={isUsluga ? "sewing" : b.next} onChange={(e) => setB(i, { next: e.target.value as any })}>
                      <option value="sewing">{t("page.cutting.toSewingFactory")}</option>
                      <option value="printing">{t("page.cutting.toPrinting")}</option>
                    </select>
                  </td>
                  <td><button type="button" className="btn btn-danger" onClick={() => remB(i)}>{t("btn.remove")}</button></td>
                </tr>
              ))}
            </tbody>
            </table>
          </div>
        </div>}

        <div>
          <label className="label">{t("common.notes")}</label>
          <textarea className="input" rows={2} value={form.notes} onChange={(e) => setPassportAutofillField("notes", e.target.value)} />
        </div>

        {doneMsg && <div className="rounded border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-700">{doneMsg}</div>}
        {err && <div className="text-sm text-red-600">{err}</div>}
        <button className="btn btn-primary" disabled={submitting}>
          {submitting
            ? t("common.saving")
            : isSecondaryUslugaFabric
              ? t("btn.save")
              : t("btn.saveCreateBundles")}
        </button>
      </form>

      {visibleBundles.length > 0 && (
        <div id="created-bundles-panel" className="card mt-6 p-4">
          <h3 className="mb-2 font-medium">{t("page.cutting.bundlesCreated")}</h3>
          <div className="overflow-hidden rounded-lg border border-[#e3dfd3] bg-[#fdfcf8]">
            <button
              type="button"
              className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left transition hover:bg-[#f7f4ec]"
              aria-expanded={createdBundlesExpanded}
              onClick={() => setCreatedBundlesExpanded((open) => !open)}
            >
              <div className="flex min-w-0 items-center gap-3">
                {createdBundlesExpanded ? <ChevronDown className="h-4 w-4 shrink-0" /> : <ChevronRight className="h-4 w-4 shrink-0" />}
                <div className="min-w-0">
                  <div className="label !mb-0">{t("field.orderNo")}</div>
                  <div className="truncate font-medium">
                    {orderReference(po, createdBundlesBatchLabel)}
                  </div>
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-3">
                <span className="badge">{visibleBundles.length} {t("nav.bundles").toLowerCase()}</span>
                <span className="text-xs font-medium text-[#56503f]">
                  {createdBundlesExpanded ? t("btn.hideLabels") : t("btn.showLabels")}
                </span>
              </div>
            </button>
            {createdBundlesExpanded && (
              <div className="overflow-x-auto border-t border-[#ecebe3]">
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#ecebe3] bg-white px-4 py-3">
                  <div className="text-sm font-medium text-[#56503f]">
                    {visibleBundles.length} {t("nav.bundles").toLowerCase()}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {printableCuttingSheets.length > 1 && (
                      <select
                        className="input !w-auto min-w-56 py-1.5"
                        aria-label={t("page.cutting.selectPrintBatch")}
                        value={printableCuttingRecordId}
                        onChange={(event) => setSelectedPrintCuttingRecordId(Number(event.target.value || 0))}
                      >
                        {printableCuttingSheets.map((option) => (
                          <option key={option.recordId} value={option.recordId}>
                            {option.label} ({option.bundleIds.length} {t("nav.bundles").toLowerCase()})
                          </option>
                        ))}
                      </select>
                    )}
                    <button
                      type="button"
                      className="btn"
                      disabled={!printableCuttingRecordId}
                      onClick={() => {
                        const query = printableBundleIds ? `?bundle_ids=${encodeURIComponent(printableBundleIds)}` : "";
                        api.openLabel(`/api/cutting/records/${printableCuttingRecordId}/production-sheet${query}`);
                      }}
                    >
                      {t("page.cutting.printProductionSheet")}
                    </button>
                    <button
                      type="button"
                      className="btn"
                      disabled={!visibleBundleIds}
                      onClick={() => api.openLabel(`/api/bundles/label-sheet/by-ids?ids=${encodeURIComponent(visibleBundleIds)}`)}
                    >
                      {t("page.packaging.printAllLabels")}
                    </button>
                  </div>
                </div>
                <table className="table">
                  <thead>
                    <tr>
                      <th>{t("field.bundleNo")}</th>
                      <th>{t("field.color")}</th>
                      <th>{t("field.size")}</th>
                      <th>{t("field.quantity")}</th>
                      <th>{t("field.sewingFactory")}</th>
                      <th>{t("field.barcode")}</th>
                      <th>{t("field.actions")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleBundles.map((b) => {
                      const bundleId = Number(b?.id || 0);
                      const canAdjust = canAdjustCuttingInventoryBundle(b);
                      const canDelete = b?.status === "created" && Number(b?.created_by || 0) === Number(me?.id || 0);
                      const isAdjusting = adjustingBundle?.bundleId === bundleId;
                      return (
                        <tr key={b.id}>
                          <td>{b.bundle_no}</td>
                          <td>
                            {isAdjusting && !isUsluga ? (
                              <input
                                className="input min-w-32"
                                value={adjustingBundle.color}
                                onChange={(e) => setAdjustingBundle((prev) => prev ? { ...prev, color: e.target.value } : prev)}
                              />
                            ) : b.color || "-"}
                          </td>
                          <td>
                            {isAdjusting && !isUsluga ? (
                              <input
                                className="input min-w-24"
                                value={adjustingBundle.size}
                                onChange={(e) => setAdjustingBundle((prev) => prev ? { ...prev, size: e.target.value } : prev)}
                              />
                            ) : b.size || "-"}
                          </td>
                          <td>
                            {isAdjusting ? (
                              <input
                                className="input max-w-28"
                                type="number"
                                min={1}
                                value={adjustingBundle.quantity}
                                onChange={(e) => setAdjustingBundle((prev) => prev ? { ...prev, quantity: parseWholeInput(e.target.value) } : prev)}
                              />
                            ) : (
                              Number(b.quantity || 0).toLocaleString()
                            )}
                          </td>
                          <td>{factoryLabel(b.sewing_factory_code)}</td>
                          <td><code>{b.barcode}</code></td>
                          <td>
                            <div className="flex flex-wrap items-center gap-2">
                              <button type="button" className="text-brand-600 hover:underline" onClick={() => api.openLabel(`/api/bundles/${b.id}/label`)}>
                                {t("common.print")}
                              </button>
                              {isAdjusting ? (
                                <>
                                  <button type="button" className="text-brand-600 hover:underline" disabled={adjustingBundleBusy} onClick={saveBundleAdjustment}>
                                    {t("btn.save")}
                                  </button>
                                  <button type="button" className="text-[#6f684f] hover:underline" disabled={adjustingBundleBusy} onClick={() => setAdjustingBundle(null)}>
                                    {t("btn.cancel")}
                                  </button>
                                </>
                              ) : canAdjust ? (
                                <>
                                  <button type="button" className="text-brand-600 hover:underline" onClick={() => beginBundleAdjustment(b)}>
                                    {t("btn.adjust")}
                                  </button>
                                  {!isUsluga ? (
                                    <button
                                      type="button"
                                      className="text-brand-600 hover:underline"
                                      disabled={editingCuttingDetailsBusy}
                                      onClick={() => beginCuttingDetailsEdit(Number(b.cutting_record_id || 0))}
                                    >
                                      {t("page.cutting.editCuttingDetails")}
                                    </button>
                                  ) : null}
                                </>
                              ) : null}
                              {canDelete && !isAdjusting ? (
                                <button
                                  type="button"
                                  className="text-red-600 hover:underline disabled:opacity-50"
                                  disabled={deletingBundleId === bundleId}
                                  onClick={() => deleteCreatedBundle(b)}
                                >
                                  {deletingBundleId === bundleId ? t("common.saving") : t("btn.delete")}
                                </button>
                              ) : null}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                {adjustingBundleErr && <div className="border-t border-[#ecebe3] px-4 py-3 text-sm text-red-600">{adjustingBundleErr}</div>}
                {editingCuttingDetails && (
                  <div className="border-t border-[#ecebe3] bg-white px-4 py-4">
                    <div className="mb-3 font-medium">{t("page.cutting.editCuttingDetails")}</div>
                    <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                      <div>
                        <label className="label">{t("field.layerMaterialKg")}</label>
                        <input
                          className="input"
                          type="number"
                          min={0}
                          step="0.01"
                          value={editingCuttingDetails.layer_material_kg}
                          onChange={(e) => setEditingCuttingDetails((prev) => prev ? { ...prev, layer_material_kg: parseDecimalInput(e.target.value) } : prev)}
                        />
                      </div>
                      <div>
                        <label className="label">{t("field.beikaKg")}</label>
                        <input
                          className="input"
                          type="number"
                          min={0}
                          step="0.01"
                          value={editingCuttingDetails.beika_kg}
                          onChange={(e) => setEditingCuttingDetails((prev) => prev ? { ...prev, beika_kg: parseDecimalInput(e.target.value) } : prev)}
                        />
                      </div>
                      <div>
                        <label className="label">{t("field.materialRollsUsed")}</label>
                        <input
                          className="input"
                          type="number"
                          min={0}
                          step="0.01"
                          value={editingCuttingDetails.material_rolls_used}
                          onChange={(e) => setEditingCuttingDetails((prev) => prev ? { ...prev, material_rolls_used: parseDecimalInput(e.target.value) } : prev)}
                        />
                      </div>
                      <div>
                        <label className="label">{t("field.layupOperator")}</label>
                        <input
                          className="input"
                          value={editingCuttingDetails.layup_operator_name}
                          onChange={(e) => setEditingCuttingDetails((prev) => prev ? { ...prev, layup_operator_name: e.target.value } : prev)}
                        />
                      </div>
                      <div className="md:col-span-2">
                        <label className="label">{t("field.notes")}</label>
                        <input
                          className="input"
                          value={editingCuttingDetails.notes}
                          onChange={(e) => setEditingCuttingDetails((prev) => prev ? { ...prev, notes: e.target.value } : prev)}
                        />
                      </div>
                    </div>
                    <div className="mt-3 flex gap-2">
                      <button type="button" className="btn btn-primary" onClick={saveCuttingDetailsEdit} disabled={editingCuttingDetailsBusy}>
                        {editingCuttingDetailsBusy ? t("common.saving") : t("btn.save")}
                      </button>
                      <button type="button" className="btn" onClick={() => setEditingCuttingDetails(null)} disabled={editingCuttingDetailsBusy}>
                        {t("btn.cancel")}
                      </button>
                    </div>
                  </div>
                )}
                {editingCuttingDetailsErr && <div className="border-t border-[#ecebe3] px-4 py-3 text-sm text-red-600">{editingCuttingDetailsErr}</div>}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
