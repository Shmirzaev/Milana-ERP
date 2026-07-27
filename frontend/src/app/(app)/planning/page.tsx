"use client";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { PackageCheck, Pencil, Plus, RotateCcw, Trash2 } from "lucide-react";
import { api, fetcher } from "@/lib/api";
import { useMe, can } from "@/lib/auth";
import PageHeader from "@/components/PageHeader";
import BrandedOrderHistory, { type BrandedPlanningOrder } from "@/components/BrandedOrderHistory";
import Modal from "@/components/Modal";
import SearchableSelect from "@/components/SearchableSelect";
import { statusLabel } from "@/components/StagePipeline";
import { useT } from "@/lib/i18n";
import { numberOrFallback, numberOrZero, parseNumberInput, type NumberInputValue } from "@/lib/numberInput";

type FabricBatch = {
  id: number;
  item_id: number;
  item_sku?: string | null;
  item_name?: string | null;
  item_category?: string | null;
  batch_no: string;
  color?: string | null;
  unit: string;
  available_quantity: number;
  warehouse_name?: string | null;
  qc_status?: string | null;
};

type Brand = {
  id: number;
  name: string;
  is_active: boolean;
};

type NewBrandTarget = "material" | "batch" | "branded";

type BrandedLine = {
  color: string;
  size: string;
  quantity: NumberInputValue;
  printing_required: boolean;
};

type BrandedModelDetail = {
  id: number;
  sizes?: Array<{ id: number; size: string }>;
  bom?: Array<{
    item_id: number;
    item?: { id: number; sku?: string; name?: string; category?: string } | null;
  }>;
};

type PrintingAttachment = { file_url: string; file_name?: string | null; content_type?: string | null };
type CuttingDepartmentCode = "CUT" | "ECT";

type BatchPlanRow = {
  name: string;
  planned_quantity: NumberInputValue;
  start_date: string;
  deadline: string;
  notes: string;
};

type MaterialEstimateDraft = {
  brandId: number;
  fabricBatchId: number;
  fabricItemIds: number[];
  materialAmount: NumberInputValue;
  materialUnit: string;
  cuttingDepartmentCode: CuttingDepartmentCode;
};

type MaterialEstimatePayload = {
  brand_id: number;
  fabric_batch_id: number;
  estimated_material_code: string;
  estimated_material_amount: number;
  estimated_material_unit: string;
  cutting_department_code: CuttingDepartmentCode;
};

type MaterialEstimateState = MaterialEstimateDraft & {
  orderId: number;
  orderNo: string;
};

type BatchPlanState = {
  orderId: number;
  orderNo: string;
  totalQty: number;
  maxPerBatch: NumberInputValue;
  rows: BatchPlanRow[];
} & MaterialEstimateDraft;

type BrandedFormState = {
  model_id: number;
  brand_id: number;
  fabric_batch_id: number;
  estimated_material_amount: NumberInputValue;
  deadline: string;
  cutting_department_code: CuttingDepartmentCode;
  lines: BrandedLine[];
};

type ReservationBatchSuggestion = {
  stock_batch_id: number;
  batch_no: string;
  warehouse_id: number;
  received_date: string;
  current_quantity: number;
  reserved_quantity: number;
  available_quantity: number;
  suggested_quantity: number;
  unit: string;
};

type MaterialReservationPlanRow = {
  item_id: number;
  item_sku: string;
  item_name: string;
  category: string;
  reservation_type: string;
  unit: string;
  required_quantity: number;
  already_reserved_quantity: number;
  remaining_to_reserve: number;
  current_stock: number;
  reserved_stock: number;
  available_stock: number;
  shortage: number;
  suggested_batches: ReservationBatchSuggestion[];
  status: string;
};

type MaterialReservation = {
  id: number;
  reservation_no: string;
  production_order_id: number;
  item_id: number;
  item_sku?: string | null;
  item_name?: string | null;
  stock_batch_id?: number | null;
  batch_no?: string | null;
  reserved_quantity: number;
  consumed_quantity: number;
  released_quantity: number;
  unit: string;
  status: string;
};

type MaterialReservationStatus = {
  plan: {
    production_order_id: number;
    order_no?: string | null;
    production_no: string;
    status: string;
    is_complete: boolean;
    warning?: string | null;
    summary: {
      required_quantity: number;
      already_reserved_quantity: number;
      remaining_to_reserve: number;
      shortage: number;
      line_count: number;
      ready_line_count: number;
      shortage_line_count: number;
    };
    rows: MaterialReservationPlanRow[];
  };
  reservations: MaterialReservation[];
};

const SIZE_OPTIONS = ["44", "46", "48", "50", "52", "54", "56", "58", "60", "62", "64"];
const DEFAULT_MATERIAL_UNIT = "kg";
const MATERIAL_ESTIMATE_LABEL_CLASS = "label md:min-h-[32px]";

function expandSizeValue(value: string | null | undefined): string[] {
  const token = String(value || "").trim();
  const match = token.match(/^(\d+)\s*[-\u2013\u2014]\s*(\d+)$/);
  if (!match) return token ? [token] : [];
  const first = Number(match[1]);
  const last = Number(match[2]);
  if (first > last || (last - first) % 2 !== 0 || (last - first) / 2 > 50) return [token];
  return Array.from({ length: ((last - first) / 2) + 1 }, (_, index) => String(first + (index * 2)));
}

function uniqueSortedSizes(values: Array<string | null | undefined>): string[] {
  return Array.from(new Set(values.flatMap(expandSizeValue)))
    .sort((a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" }));
}

function distributeExistingQuantityAcrossSizes(sizes: string[], lines: BrandedLine[]): BrandedLine[] {
  if (!sizes.length) return lines;
  const total = Math.max(
    sizes.length,
    lines.reduce((sum, line) => sum + Math.max(0, numberOrZero(line.quantity)), 0),
  );
  const baseQuantity = Math.floor(total / sizes.length);
  let remainder = total % sizes.length;
  const color = String(lines[0]?.color || "white").trim() || "white";
  const printingRequired = Boolean(lines[0]?.printing_required);
  return sizes.map((size) => {
    const quantity = baseQuantity + (remainder > 0 ? 1 : 0);
    if (remainder > 0) remainder -= 1;
    return { color, size, quantity, printing_required: printingRequired };
  });
}

function fmtQty(value: number | string | null | undefined) {
  const parsed = numberOrZero(value);
  return parsed.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

function modelFabricItemIds(model?: BrandedModelDetail | null): number[] {
  return Array.from(new Set((model?.bom || [])
    .filter((row) => ["fabric", "semi_finished"].includes(String(row.item?.category || "").toLowerCase()))
    .map((row) => Number(row.item_id || row.item?.id || 0))
    .filter((itemId) => itemId > 0)));
}

function fabricBatchLabel(batch: FabricBatch): string {
  const fabric = [batch.item_sku, batch.item_name].filter(Boolean).join(" - ");
  const details = [
    batch.batch_no,
    batch.color,
    `${fmtQty(batch.available_quantity)} ${batch.unit || DEFAULT_MATERIAL_UNIT} available`,
    batch.warehouse_name,
  ].filter(Boolean).join(" | ");
  return `${fabric || `Fabric #${batch.item_id}`} | ${details}`;
}

function fabricBatchOptions(batches: FabricBatch[], fabricItemIds: number[]) {
  const matchingItemIds = new Set(fabricItemIds.map(Number));
  return batches
    .map((batch, index) => ({
      batch,
      index,
      matchesModel: matchingItemIds.has(Number(batch.item_id)),
    }))
    .sort((left, right) => (
      Number(right.matchesModel) - Number(left.matchesModel)
      || left.index - right.index
    ))
    .map(({ batch }) => ({ value: Number(batch.id), label: fabricBatchLabel(batch) }));
}

function reservationStatusLabel(status: string, t: (key: string) => string) {
  if (status === "ready") return t("reservation.status.ready");
  if (status === "shortage") return t("reservation.status.shortage");
  return t("reservation.status.partial");
}

function reservationStatusClass(status: string) {
  if (status === "ready") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (status === "shortage") return "border-red-200 bg-red-50 text-red-700";
  return "border-amber-200 bg-amber-50 text-amber-700";
}

function emptyMaterialEstimate(brandId = 0, fabricItemIds: number[] = [], fabricBatch?: FabricBatch): MaterialEstimateDraft {
  return {
    brandId,
    fabricBatchId: Number(fabricBatch?.id || 0),
    fabricItemIds,
    materialAmount: "",
    materialUnit: fabricBatch?.unit || DEFAULT_MATERIAL_UNIT,
    cuttingDepartmentCode: "CUT",
  };
}

function validateMaterialEstimate(draft: MaterialEstimateDraft, fabricBatches: FabricBatch[]): { payload?: MaterialEstimatePayload; error?: string } {
  const batch = fabricBatches.find((row) => Number(row.id) === Number(draft.fabricBatchId));
  const amount = Number(draft.materialAmount);
  if (!draft.brandId) return { error: "Select a brand for the production order." };
  if (!batch) return { error: "Select an available fabric batch for the cutting team." };
  if (!Number.isFinite(amount) || amount <= 0) return { error: "Enter estimated material amount greater than zero." };
  return {
    payload: {
      brand_id: draft.brandId,
      fabric_batch_id: batch.id,
      estimated_material_code: batch.item_sku || batch.batch_no,
      estimated_material_amount: amount,
      estimated_material_unit: batch.unit || DEFAULT_MATERIAL_UNIT,
      cutting_department_code: draft.cuttingDepartmentCode,
    },
  };
}

function autoSplitBatchRows(totalQty: number, maxPerBatch: number): BatchPlanRow[] {
  const safeTotal = Math.max(0, Number(totalQty || 0));
  const safeMax = Math.max(1, Number(maxPerBatch || 1));
  if (safeTotal <= 0) {
    return [{ name: "Batch 1", planned_quantity: "", start_date: "", deadline: "", notes: "" }];
  }
  const out: BatchPlanRow[] = [];
  let left = safeTotal;
  let idx = 1;
  while (left > 0) {
    const qty = Math.min(safeMax, left);
    out.push({
      name: `Batch ${idx}`,
      planned_quantity: qty,
      start_date: "",
      deadline: "",
      notes: "",
    });
    left -= qty;
    idx += 1;
  }
  return out;
}

export default function PlanningDashboard() {
  const { t } = useT();
  const pathname = usePathname();
  const brandedOnly = pathname.endsWith("/planning/branded-stock");
  const searchParams = useSearchParams();
  const { me } = useMe();
  const { data: dash } = useSWR<any>("/api/dashboard/planning", fetcher);
  const { data: orders } = useSWR<any[]>("/api/sales-orders?order_type=client_order&page_size=200", fetcher);
  const { data: productionOrders, mutate: mutateProductionOrders } = useSWR<any[]>("/api/production-orders?page_size=100", fetcher);
  const { data: models } = useSWR<any[]>("/api/models?status=approved", fetcher);
  const { data: brands, mutate: mutateBrands } = useSWR<Brand[]>("/api/brands", fetcher);
  const { data: fabricBatches } = useSWR<FabricBatch[]>("/api/inventory/batches?group=materials&hide_empty=true&page_size=1000", fetcher);
  const { data: brandedOrders, mutate: mutateBrandedOrders } = useSWR<BrandedPlanningOrder[]>("/api/planning/branded-orders", fetcher);
  const canViewForecasting = can(me, "forecasting.view");
  const { data: forecastSuggestions } = useSWR<any[]>(
    canViewForecasting ? "/api/forecasting/branded-stock-suggestions" : null,
    fetcher,
  );
  const [brandedForm, setBrandedForm] = useState<BrandedFormState>({
    model_id: 0,
    brand_id: 0,
    fabric_batch_id: 0,
    estimated_material_amount: "",
    deadline: "",
    cutting_department_code: "CUT",
    lines: [{ color: "white", size: "46", quantity: 600, printing_required: false }],
  });
  const [brandedSizeFrom, setBrandedSizeFrom] = useState("46");
  const [brandedSizeTo, setBrandedSizeTo] = useState("56");
  const [brandedDistributeQty, setBrandedDistributeQty] = useState<NumberInputValue>(6000);
  const [brandedLinesEditing, setBrandedLinesEditing] = useState(false);
  const [brandedLinesModelId, setBrandedLinesModelId] = useState(0);
  const [brandedSaving, setBrandedSaving] = useState(false);
  const [brandedErr, setBrandedErr] = useState("");
  const [brandedSuccess, setBrandedSuccess] = useState<{ id: number; orderNo: string } | null>(null);
  const [selectedBrandedOrderId, setSelectedBrandedOrderId] = useState(0);
  const [newBrandedOrderSaving, setNewBrandedOrderSaving] = useState(false);
  const [newBrandedOrderErr, setNewBrandedOrderErr] = useState("");
  const [brandedPrintingInstructions, setBrandedPrintingInstructions] = useState("");
  const [brandedPrintingAttachments, setBrandedPrintingAttachments] = useState<PrintingAttachment[]>([]);
  const [brandedUploadingPrintFile, setBrandedUploadingPrintFile] = useState(false);
  const { data: selectedBrandedModelDetail } = useSWR<BrandedModelDetail>(
    brandedForm.model_id ? `/api/models/${brandedForm.model_id}` : null,
    fetcher,
  );
  const [busyOrderId, setBusyOrderId] = useState<number | null>(null);
  const [materialEstimate, setMaterialEstimate] = useState<MaterialEstimateState | null>(null);
  const [materialEstimateErr, setMaterialEstimateErr] = useState("");
  const [batchPlan, setBatchPlan] = useState<BatchPlanState | null>(null);
  const [batchPlanErr, setBatchPlanErr] = useState("");
  const [newBrandTarget, setNewBrandTarget] = useState<NewBrandTarget | null>(null);
  const [newBrandForm, setNewBrandForm] = useState({ name: "", description: "" });
  const [newBrandSaving, setNewBrandSaving] = useState(false);
  const [newBrandError, setNewBrandError] = useState("");
  const [selectedReservationPoId, setSelectedReservationPoId] = useState<number | null>(null);
  const [reservationBusy, setReservationBusy] = useState("");
  const [reservationMsg, setReservationMsg] = useState("");
  const canCreateReservations = can(me, "*", "planning.reserve_materials", "inventory.reservations.create");
  const canReleaseReservations = can(me, "*", "inventory.reservations.release");
  const activeReservationPoId = selectedReservationPoId || Number(productionOrders?.[0]?.id || 0) || null;
  const { data: reservationStatus, mutate: mutateReservationStatus } = useSWR<MaterialReservationStatus>(
    activeReservationPoId ? `/api/production-orders/${activeReservationPoId}/material-reservation-status` : null,
    fetcher,
  );

  const planningOrders = (orders || []).filter((o) => ["confirmed", "pending_sales_approval", "planning_approved"].includes(o.status));
  const brandedTotalQty = brandedForm.lines.reduce((sum, line) => sum + Number(line.quantity || 0), 0);
  const brandedPrintingLineCount = brandedForm.lines.filter((line) => Boolean(line.printing_required)).length;
  const brandedHasPrintingSelected = brandedPrintingLineCount > 0;
  const activeBrands = (brands || []).filter((brand) => brand.is_active);
  const availableFabricBatches = useMemo(() => (fabricBatches || [])
    .filter((batch) => Number(batch.available_quantity || 0) > 0)
    .filter((batch) => !["failed", "rejected"].includes(String(batch.qc_status || "").toLowerCase())), [fabricBatches]);
  const selectedBrandedModel = models?.find((m) => Number(m.id) === Number(brandedForm.model_id)) || null;
  const selectedBrandedBrand = activeBrands.find((brand) => Number(brand.id) === Number(brandedForm.brand_id)) || null;
  const selectedBrandedFabricBatch = availableFabricBatches.find((batch) => Number(batch.id) === Number(brandedForm.fabric_batch_id)) || null;
  const brandedModelOptions = useMemo(() => (models || []).map((model) => ({
    value: Number(model.id),
    label: [model.code, model.name].filter(Boolean).join(" - "),
  })), [models]);
  const selectedBrandedModelSizes = useMemo(
    () => uniqueSortedSizes((selectedBrandedModelDetail?.sizes || []).map((row) => row.size)),
    [selectedBrandedModelDetail],
  );
  const selectedBrandedFabricItemIds = useMemo(
    () => modelFabricItemIds(selectedBrandedModelDetail),
    [selectedBrandedModelDetail],
  );
  const brandedFabricBatchOptions = useMemo(
    () => fabricBatchOptions(availableFabricBatches, selectedBrandedFabricItemIds),
    [availableFabricBatches, selectedBrandedFabricItemIds],
  );
  const brandedSizeOptions = useMemo(
    () => uniqueSortedSizes([
      ...SIZE_OPTIONS,
      ...selectedBrandedModelSizes,
      ...brandedForm.lines.map((line) => line.size),
    ]),
    [brandedForm.lines, selectedBrandedModelSizes],
  );
  const selectedBrandedOrder = brandedOrders?.find((order) => Number(order.id) === Number(selectedBrandedOrderId)) || null;
  const forecastPrefillKey = searchParams.toString();

  useEffect(() => {
    const params = new URLSearchParams(forecastPrefillKey);
    const modelId = Number(params.get("model_id") || 0);
    if (!modelId) return;
    const color = String(params.get("color") || "white").trim() || "white";
    const size = String(params.get("size") || "46").trim() || "46";
    const quantity = Math.max(1, Number(params.get("qty") || 1));
    setBrandedForm((prev) => ({
      ...prev,
      model_id: modelId,
      lines: [{ color, size, quantity, printing_required: false }],
    }));
    setBrandedLinesModelId(modelId);
    setBrandedLinesEditing(true);
  }, [forecastPrefillKey]);

  useEffect(() => {
    const modelId = Number(brandedForm.model_id || 0);
    if (!modelId || Number(selectedBrandedModelDetail?.id || 0) !== modelId || brandedLinesModelId === modelId) return;

    const sizes = uniqueSortedSizes((selectedBrandedModelDetail?.sizes || []).map((row) => row.size));
    setBrandedLinesModelId(modelId);
    if (!sizes.length) {
      setBrandedLinesEditing(true);
      return;
    }

    setBrandedForm((prev) => ({
      ...prev,
      lines: distributeExistingQuantityAcrossSizes(sizes, prev.lines),
    }));
    setBrandedSizeFrom(sizes[0]);
    setBrandedSizeTo(sizes[sizes.length - 1]);
    setBrandedLinesEditing(false);
  }, [brandedForm.model_id, brandedLinesModelId, selectedBrandedModelDetail]);

  useEffect(() => {
    if (!brandedForm.model_id || brandedForm.brand_id) return;
    const model = models?.find((row) => Number(row.id) === Number(brandedForm.model_id));
    if (!model?.brand_id) return;
    setBrandedForm((prev) => ({ ...prev, brand_id: Number(model.brand_id) }));
  }, [brandedForm.brand_id, brandedForm.model_id, models]);

  useEffect(() => {
    if (!brandedForm.model_id || !availableFabricBatches.length) return;
    const currentIsValid = availableFabricBatches.some(
      (batch) => Number(batch.id) === Number(brandedForm.fabric_batch_id),
    );
    if (currentIsValid) return;
    const firstMatch = availableFabricBatches.find((batch) => selectedBrandedFabricItemIds.includes(Number(batch.item_id)));
    setBrandedForm((prev) => ({ ...prev, fabric_batch_id: Number(firstMatch?.id || 0) }));
  }, [availableFabricBatches, brandedForm.fabric_batch_id, brandedForm.model_id, selectedBrandedFabricItemIds]);

  function selectBrandedModel(modelId: number) {
    const model = models?.find((row) => Number(row.id) === Number(modelId));
    setBrandedLinesModelId(0);
    setBrandedLinesEditing(false);
    setBrandedForm((prev) => ({
      ...prev,
      model_id: Number(modelId),
      brand_id: Number(model?.brand_id || 0),
      fabric_batch_id: 0,
    }));
  }

  function openNewBrand(target: NewBrandTarget) {
    setNewBrandTarget(target);
    setNewBrandForm({ name: "", description: "" });
    setNewBrandError("");
  }

  function closeNewBrand() {
    if (newBrandSaving) return;
    setNewBrandTarget(null);
    setNewBrandError("");
  }

  async function createNewBrand(e: React.FormEvent) {
    e.preventDefault();
    const name = newBrandForm.name.trim();
    if (!name || !newBrandTarget) return;
    const target = newBrandTarget;
    setNewBrandSaving(true);
    setNewBrandError("");
    try {
      const created = await api.post<Brand>("/api/brands", {
        name,
        description: newBrandForm.description.trim() || null,
        is_active: true,
      });
      await mutateBrands(
        (current) => [...(current || []).filter((brand) => brand.id !== created.id), created]
          .sort((a, b) => a.name.localeCompare(b.name)),
        { revalidate: false },
      );
      if (target === "material") {
        setMaterialEstimate((prev) => prev ? { ...prev, brandId: created.id } : prev);
      } else if (target === "batch") {
        setBatchPlan((prev) => prev ? { ...prev, brandId: created.id } : prev);
      } else {
        setBrandedForm((prev) => ({ ...prev, brand_id: created.id }));
      }
      setNewBrandTarget(null);
      setNewBrandForm({ name: "", description: "" });
    } catch (error: any) {
      setNewBrandError(error?.message || "Could not create brand.");
    } finally {
      setNewBrandSaving(false);
    }
  }

  function restoreBrandedModelSizes() {
    if (!selectedBrandedModelSizes.length) return;
    setBrandedForm((prev) => ({
      ...prev,
      lines: distributeExistingQuantityAcrossSizes(selectedBrandedModelSizes, prev.lines),
    }));
    setBrandedSizeFrom(selectedBrandedModelSizes[0]);
    setBrandedSizeTo(selectedBrandedModelSizes[selectedBrandedModelSizes.length - 1]);
    setBrandedLinesEditing(false);
  }

  function updateBrandedLine(i: number, patch: Partial<BrandedLine>) {
    setBrandedForm((prev) => ({
      ...prev,
      lines: prev.lines.map((line, idx) => (idx === i ? { ...line, ...patch } : line)),
    }));
  }

  function addBrandedLine() {
    setBrandedForm((prev) => ({
      ...prev,
      lines: [...prev.lines, { color: prev.lines[0]?.color || "white", size: "46", quantity: 1, printing_required: false }],
    }));
  }

  function removeBrandedLine(i: number) {
    setBrandedForm((prev) => {
      if (prev.lines.length <= 1) return prev;
      return { ...prev, lines: prev.lines.filter((_, idx) => idx !== i) };
    });
  }

  function distributeBrandedBySizeRange() {
    setBrandedErr("");
    const startIdx = brandedSizeOptions.indexOf(brandedSizeFrom);
    const endIdx = brandedSizeOptions.indexOf(brandedSizeTo);
    const distributeQty = numberOrZero(brandedDistributeQty);
    if (startIdx < 0 || endIdx < 0 || startIdx > endIdx) {
      setBrandedErr(t("newso.invalidSizeRange"));
      return;
    }
    if (distributeQty <= 0) {
      setBrandedErr(t("newso.invalidTotalQty"));
      return;
    }

    const selectedSizes = brandedSizeOptions.slice(startIdx, endIdx + 1);
    const count = selectedSizes.length;
    const qtyPerSize = Math.floor(distributeQty / count);
    let remainder = distributeQty % count;
    const baseColor = brandedForm.lines[0]?.color || "white";
    const basePrintingRequired = Boolean(brandedForm.lines[0]?.printing_required);

    const nextLines: BrandedLine[] = selectedSizes.map((size) => {
      const addOne = remainder > 0 ? 1 : 0;
      if (remainder > 0) remainder -= 1;
      return { color: baseColor, size, quantity: qtyPerSize + addOne, printing_required: basePrintingRequired };
    });

    setBrandedForm((prev) => ({ ...prev, lines: nextLines }));
  }

  function isImageAttachment(a: PrintingAttachment): boolean {
    const byMime = (a.content_type || "").toLowerCase().startsWith("image/");
    const byName = /\.(png|jpe?g|webp|gif)$/i.test(a.file_name || a.file_url || "");
    return byMime || byName;
  }

  async function onPickBrandedPrintingFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    setBrandedErr("");
    setBrandedUploadingPrintFile(true);
    try {
      const uploaded: PrintingAttachment[] = [];
      for (const file of Array.from(files)) {
        const form = new FormData();
        form.append("file", file);
        const saved = await api.postForm<PrintingAttachment>("/api/production-orders/printing-attachments/upload", form);
        uploaded.push(saved);
      }
      setBrandedPrintingAttachments((prev) => [...prev, ...uploaded]);
    } catch (e: any) {
      setBrandedErr(e?.message || "Failed to upload file");
    } finally {
      setBrandedUploadingPrintFile(false);
    }
  }

  async function createPOForSO(soId: number, batches?: BatchPlanRow[], material?: MaterialEstimatePayload) {
    setBusyOrderId(soId);
    try {
      const so = await api.get(`/api/sales-orders/${soId}`);
      const items = (so.items || []).map((i: any) => ({
        model_id: i.model_id,
        color: i.color,
        size: i.size,
        planned_quantity: i.quantity,
        printing_required: Boolean(i.printing_required),
      }));
      const normalizedBatches = (batches || [])
        .map((b) => ({
          name: String(b.name || "").trim() || null,
          planned_quantity: Number(b.planned_quantity || 0),
          start_date: b.start_date ? new Date(b.start_date).toISOString() : null,
          deadline: b.deadline ? new Date(b.deadline).toISOString() : null,
          notes: String(b.notes || "").trim() || null,
        }))
        .filter((b) => b.planned_quantity > 0);
      const po = await api.post("/api/planning/create-production-order", {
        production_type: "client_order",
        sales_order_id: soId,
        model_id: so.items?.[0]?.model_id,
        planned_quantity: items.reduce((s: number, i: any) => s + i.planned_quantity, 0),
        // Carry the customer deadline through to the production order so the
        // process tracker shows a meaningful "due by" value.
        deadline: so.deadline ?? null,
        items,
        batches: normalizedBatches,
        ...(material || {}),
      }, 60_000);
      // Cascade the deadline into each work-order (cutting/printing/sewing/packaging)
      // unless explicit per-batch planning is used.
      if (so.deadline && normalizedBatches.length === 0) {
        try { await api.post(`/api/production-orders/${po.id}/cascade-deadlines`); } catch {}
      }
      window.location.href = `/production-orders/${po.id}`;
    } finally {
      setBusyOrderId(null);
    }
  }

  async function materialEstimateForSalesOrder(so: any): Promise<MaterialEstimateDraft> {
    const modelIds = Array.from(new Set((so.items || [])
      .map((row: any) => Number(row.model_id || 0))
      .filter((modelId: number) => modelId > 0)));
    const modelDetails = await Promise.all(modelIds.map((modelId) => api.get<BrandedModelDetail>(`/api/models/${modelId}`)));
    const fabricItemIds = Array.from(new Set(modelDetails.flatMap((model) => modelFabricItemIds(model))));
    const selectedBatch = availableFabricBatches.find((batch) => fabricItemIds.includes(Number(batch.item_id)));
    const firstItem = so.items?.[0];
    const model = models?.find((row) => Number(row.id) === Number(firstItem?.model_id));
    return emptyMaterialEstimate(
      Number(firstItem?.brand_id || model?.brand_id || 0),
      fabricItemIds,
      selectedBatch,
    );
  }

  async function openMaterialEstimateForSO(order: any) {
    setBusyOrderId(Number(order.id));
    setMaterialEstimateErr("");
    try {
      const so = await api.get(`/api/sales-orders/${order.id}`);
      setMaterialEstimate({
        orderId: Number(order.id),
        orderNo: order.order_no || `#${order.id}`,
        ...await materialEstimateForSalesOrder(so),
      });
    } finally {
      setBusyOrderId(null);
    }
  }

  async function createPOFromMaterialEstimate() {
    if (!materialEstimate) return;
    const check = validateMaterialEstimate(materialEstimate, availableFabricBatches);
    if (check.error || !check.payload) {
      setMaterialEstimateErr(check.error || "Enter material estimate before creating the production order.");
      return;
    }
    setMaterialEstimateErr("");
    try {
      await createPOForSO(materialEstimate.orderId, undefined, check.payload);
    } catch (e: any) {
      setMaterialEstimateErr(e?.message || "Failed to create production order.");
    }
  }

  async function openBatchPlannerForSO(soId: number) {
    setBusyOrderId(soId);
    setBatchPlanErr("");
    try {
      const so = await api.get(`/api/sales-orders/${soId}`);
      const totalQty = (so.items || []).reduce((sum: number, row: any) => sum + Number(row.quantity || 0), 0);
      const maxPerBatch = 600;
      setBatchPlan({
        orderId: soId,
        orderNo: so.order_no || `#${soId}`,
        totalQty,
        maxPerBatch,
        rows: autoSplitBatchRows(totalQty, maxPerBatch),
        ...await materialEstimateForSalesOrder(so),
      });
    } finally {
      setBusyOrderId(null);
    }
  }

  function updateBatchPlanRow(index: number, patch: Partial<BatchPlanRow>) {
    setBatchPlan((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        rows: prev.rows.map((row, i) => (i === index ? { ...row, ...patch } : row)),
      };
    });
  }

  function addBatchPlanRow() {
    setBatchPlan((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        rows: [
          ...prev.rows,
          { name: `Batch ${prev.rows.length + 1}`, planned_quantity: "", start_date: "", deadline: "", notes: "" },
        ],
      };
    });
  }

  function removeBatchPlanRow(index: number) {
    setBatchPlan((prev) => {
      if (!prev || prev.rows.length <= 1) return prev;
      return {
        ...prev,
        rows: prev.rows.filter((_, i) => i !== index),
      };
    });
  }

  async function createPOFromBatchPlan() {
    if (!batchPlan) return;
    const rows = batchPlan.rows.map((row) => ({
      ...row,
      planned_quantity: Number(row.planned_quantity || 0),
      name: String(row.name || "").trim(),
    }));
    if (rows.some((row) => !Number.isFinite(row.planned_quantity) || row.planned_quantity <= 0)) {
      setBatchPlanErr(t("batch.quantityGreaterThanZero"));
      return;
    }
    const estimate = validateMaterialEstimate(batchPlan, availableFabricBatches);
    if (estimate.error || !estimate.payload) {
      setBatchPlanErr(estimate.error || "Enter material estimate before creating the production order.");
      return;
    }
    setBatchPlanErr("");
    try {
      await createPOForSO(batchPlan.orderId, rows, estimate.payload);
    } catch (e: any) {
      setBatchPlanErr(e?.message || "Failed to create production order.");
    }
  }

  async function autoReserveMaterials(productionOrderId: number) {
    setReservationBusy(`auto-${productionOrderId}`);
    setReservationMsg("");
    try {
      const result = await api.post(`/api/production-orders/${productionOrderId}/reserve-materials`, {
        mode: "full_remaining",
        reserve_accessories: true,
        reserve_materials: true,
        reserve_packaging: true,
      });
      setReservationMsg(t("reservation.createdCount", { count: Number(result?.created_count || 0) }));
      await mutateReservationStatus();
      await mutateProductionOrders();
    } catch (e: any) {
      setReservationMsg(e?.message || t("reservation.actionFailed"));
    } finally {
      setReservationBusy("");
    }
  }

  async function reserveSuggestedBatch(row: MaterialReservationPlanRow, batch: ReservationBatchSuggestion) {
    if (!activeReservationPoId) return;
    setReservationBusy(`batch-${batch.stock_batch_id}`);
    setReservationMsg("");
    try {
      await api.post("/api/inventory/reservations", {
        production_order_id: activeReservationPoId,
        item_id: row.item_id,
        stock_batch_id: batch.stock_batch_id,
        warehouse_id: batch.warehouse_id,
        reserved_quantity: batch.suggested_quantity,
        unit: row.unit,
        reservation_type: row.reservation_type,
        notes: "Reserved from planning batch suggestion",
      });
      setReservationMsg(t("reservation.created"));
      await mutateReservationStatus();
    } catch (e: any) {
      setReservationMsg(e?.message || t("reservation.actionFailed"));
    } finally {
      setReservationBusy("");
    }
  }

  async function releaseReservation(reservationId: number) {
    setReservationBusy(`release-${reservationId}`);
    setReservationMsg("");
    try {
      await api.post(`/api/inventory/reservations/${reservationId}/release`, {});
      setReservationMsg(t("reservation.released"));
      await mutateReservationStatus();
    } catch (e: any) {
      setReservationMsg(e?.message || t("reservation.actionFailed"));
    } finally {
      setReservationBusy("");
    }
  }

  async function createBrandedPlanningOrder() {
    setNewBrandedOrderErr("");
    setNewBrandedOrderSaving(true);
    try {
      const order = await api.post<BrandedPlanningOrder>("/api/planning/branded-orders", {});
      await mutateBrandedOrders();
      selectBrandedOrderForProduction(order.id);
    } catch (e: any) {
      setNewBrandedOrderErr(e?.message || t("page.warehouseMap.actionFailed"));
    } finally {
      setNewBrandedOrderSaving(false);
    }
  }

  function selectBrandedOrderForProduction(orderId: number) {
    setSelectedBrandedOrderId(orderId);
    setBrandedErr("");
    setBrandedSuccess(null);
    window.requestAnimationFrame(() => {
      document.getElementById("branded-production-form")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  async function createBranded(e: React.FormEvent) {
    e.preventDefault();
    setBrandedErr("");
    if (!brandedForm.model_id) {
      setBrandedErr(t("newso.selectModel"));
      return;
    }
    if (!brandedForm.brand_id) {
      setBrandedErr(t("newso.brandSelect"));
      return;
    }
    if (!selectedBrandedFabricBatch || !selectedBrandedFabricItemIds.includes(Number(selectedBrandedFabricBatch.item_id))) {
      setBrandedErr("Select an available fabric batch that matches this model's fabric type.");
      return;
    }
    const estimatedMaterialAmount = Number(brandedForm.estimated_material_amount);
    if (!Number.isFinite(estimatedMaterialAmount) || estimatedMaterialAmount <= 0) {
      setBrandedErr("Enter estimated material amount greater than zero.");
      return;
    }
    if (!selectedBrandedOrderId) {
      setBrandedErr(t("page.planning.selectBrandedOrderError"));
      return;
    }

    const items = brandedForm.lines
      .map((line) => ({
        model_id: brandedForm.model_id,
        color: String(line.color || "").trim() || "white",
        size: String(line.size || "").trim() || "46",
        planned_quantity: numberOrZero(line.quantity),
        printing_required: Boolean(line.printing_required),
      }))
      .filter((line) => line.planned_quantity > 0);

    if (!items.length) {
      setBrandedErr(t("newso.invalidTotalQty"));
      return;
    }

    const plannedQty = items.reduce((sum, line) => sum + line.planned_quantity, 0);
    setBrandedSaving(true);
    try {
      const po = await api.post("/api/planning/create-branded-production", {
        production_type: "branded_stock",
        planning_order_id: selectedBrandedOrderId,
        model_id: brandedForm.model_id,
        brand_id: brandedForm.brand_id,
        fabric_batch_id: selectedBrandedFabricBatch.id,
        estimated_material_code: selectedBrandedFabricBatch.item_sku || selectedBrandedFabricBatch.batch_no,
        estimated_material_amount: estimatedMaterialAmount,
        estimated_material_unit: selectedBrandedFabricBatch.unit || DEFAULT_MATERIAL_UNIT,
        planned_quantity: plannedQty,
        deadline: brandedForm.deadline || null,
        cutting_department_code: brandedForm.cutting_department_code,
        printing_instructions: brandedHasPrintingSelected ? (brandedPrintingInstructions.trim() || null) : null,
        printing_attachments: brandedHasPrintingSelected ? brandedPrintingAttachments : [],
        items,
      }, 60_000);
      if (brandedForm.deadline) {
        try { await api.post(`/api/production-orders/${po.id}/cascade-deadlines`); } catch {}
      }
      setBrandedSuccess({ id: po.id, orderNo: po.order_no || po.production_no || `#${po.id}` });
      setBrandedForm((prev) => ({
        ...prev,
        model_id: 0,
        brand_id: 0,
        fabric_batch_id: 0,
        estimated_material_amount: "",
        deadline: "",
        lines: [{ color: "white", size: "46", quantity: 600, printing_required: false }],
      }));
      setBrandedLinesModelId(0);
      setBrandedLinesEditing(false);
      setBrandedPrintingInstructions("");
      setBrandedPrintingAttachments([]);
      await Promise.all([mutateBrandedOrders(), mutateProductionOrders()]);
    } catch (e: any) {
      setBrandedErr(e?.message || t("page.warehouseMap.actionFailed"));
    } finally {
      setBrandedSaving(false);
    }
  }

  return (
    <div>
      <PageHeader
        title={brandedOnly ? t("page.planning.brandedOrdersTitle") : t("page.planning.title")}
        subtitle={brandedOnly ? t("page.planning.brandedOrdersSubtitle") : t("page.planning.subtitle")}
      />
      {!brandedOnly ? (
        <>
      <div className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 lg:gap-4">
        <div className="card p-4"><div className="text-xs text-slate-500">{t("page.planning.ordersWaiting")}</div><div className="text-2xl font-semibold">{dash?.orders_waiting_planning ?? 0}</div></div>
        <div className="card p-4"><div className="text-xs text-slate-500">{t("page.planning.activeProduction")}</div><div className="text-2xl font-semibold">{dash?.active_production_orders ?? 0}</div></div>
        <div className="card p-4"><div className="text-xs text-slate-500">{t("page.planning.brandedPlans")}</div><div className="text-2xl font-semibold">{dash?.branded_plans ?? 0}</div></div>
      </div>

      {canViewForecasting && (forecastSuggestions || []).length > 0 && (
        <section className="card mb-6 p-4">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <h2 className="app-card-title">{t("page.planning.forecastSuggestions")}</h2>
              <p className="mt-1 text-sm text-[#8a8472]">{t("page.planning.forecastSuggestionsSub")}</p>
            </div>
            <Link className="btn" href="/forecasting">{t("nav.forecasting")}</Link>
          </div>
          <div className="grid gap-2 lg:grid-cols-3">
            {(forecastSuggestions || []).slice(0, 3).map((row: any) => (
              <Link
                key={`${row.model_id}-${row.color}-${row.size}`}
                className="rounded-md border border-[#ecebe3] p-3 text-sm transition hover:border-[#d6d0bf] hover:bg-[#fdf8f2]"
                href={`/planning/branded-stock?model_id=${row.model_id}&color=${encodeURIComponent(row.color || "")}&size=${encodeURIComponent(row.size || "")}&qty=${row.suggested_quantity}`}
              >
                <span className="block font-semibold text-[#14110b]">{row.model_code || row.model_id} - {row.color || "-"} / {row.size || "-"}</span>
                <span className="mt-1 block text-xs text-[#6f684f]">
                  {t("page.forecasting.suggested")}: {fmtQty(row.suggested_quantity)} {row.unit || "pcs"}
                </span>
              </Link>
            ))}
          </div>
        </section>
      )}

      <section className="card mb-6 overflow-hidden">
        <div className="flex flex-col gap-3 border-b border-[#ecebe3] p-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h2 className="app-card-title">{t("reservation.title")}</h2>
            <p className="mt-1 text-sm text-[#6f684f]">{t("reservation.planningSubtitle")}</p>
          </div>
          {activeReservationPoId && canCreateReservations && (
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => autoReserveMaterials(activeReservationPoId)}
              disabled={reservationBusy === `auto-${activeReservationPoId}`}
            >
              <PackageCheck className="h-4 w-4" />
              {reservationBusy === `auto-${activeReservationPoId}` ? t("common.saving") : t("reservation.autoReserve")}
            </button>
          )}
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-[280px_minmax(0,1fr)]">
          <div className="border-b border-[#ecebe3] lg:border-b-0 lg:border-r">
            <div className="max-h-[520px] overflow-y-auto p-3">
              {(productionOrders || []).slice(0, 30).map((po) => {
                const active = Number(po.id) === Number(activeReservationPoId);
                return (
                  <button
                    key={po.id}
                    type="button"
                    className={`mb-1 flex w-full items-center justify-between gap-3 rounded-md px-3 py-2 text-left text-sm ${
                      active ? "bg-[#14110b] text-[#fdfcf8]" : "text-[#2c2920] hover:bg-[#f1efe8]"
                    }`}
                    onClick={() => setSelectedReservationPoId(Number(po.id))}
                  >
                    <span className="min-w-0">
                      <span className="block truncate font-medium">{po.order_no || po.production_no}</span>
                      <span className={`block truncate text-xs ${active ? "text-[#ded9ca]" : "text-[#8a8472]"}`}>
                        {statusLabel(po.status, t)}
                      </span>
                    </span>
                    <span className={`shrink-0 rounded-md border px-2 py-0.5 text-xs ${active ? "border-[#fdfcf8]/30" : "border-[#ded9ca]"}`}>
                      #{po.id}
                    </span>
                  </button>
                );
              })}
              {(productionOrders || []).length === 0 && (
                <div className="px-2 py-4 text-sm text-[#8a8472]">{t("reservation.noProductionOrders")}</div>
              )}
            </div>
          </div>
          <div className="min-w-0 p-4">
            {reservationStatus ? (
              <div className="space-y-4">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-semibold text-[#14110b]">
                        {reservationStatus.plan.order_no || reservationStatus.plan.production_no}
                      </span>
                      <span className={`rounded-md border px-2 py-0.5 text-xs font-medium ${reservationStatusClass(reservationStatus.plan.status)}`}>
                        {reservationStatusLabel(reservationStatus.plan.status, t)}
                      </span>
                    </div>
                    <div className="mt-1 text-sm text-[#6f684f]">
                      {t("reservation.summaryLine", {
                        reserved: fmtQty(reservationStatus.plan.summary.already_reserved_quantity),
                        required: fmtQty(reservationStatus.plan.summary.required_quantity),
                        shortage: fmtQty(reservationStatus.plan.summary.shortage),
                      })}
                    </div>
                  </div>
                  {reservationStatus.plan.warning && (
                    <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                      {t("reservation.warning")}
                    </div>
                  )}
                </div>

                <div className="overflow-x-auto">
                  <table className="table text-sm">
                    <thead>
                      <tr>
                        <th>{t("field.item")}</th>
                        <th>{t("field.required")}</th>
                        <th>{t("field.reserved")}</th>
                        <th>{t("field.available")}</th>
                        <th>{t("field.shortage")}</th>
                        <th>{t("reservation.suggestedBatches")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {reservationStatus.plan.rows.map((row) => (
                        <tr key={`${row.item_id}-${row.unit}`}>
                          <td>
                            <div className="mono font-semibold text-[#14110b]">{row.item_sku}</div>
                            <div className="max-w-[220px] truncate text-xs text-[#8a8472]">{row.item_name}</div>
                          </td>
                          <td className="mono">{fmtQty(row.required_quantity)} {row.unit}</td>
                          <td className="mono">{fmtQty(row.already_reserved_quantity)} {row.unit}</td>
                          <td className="mono">{fmtQty(row.available_stock)} {row.unit}</td>
                          <td className={`mono ${Number(row.shortage || 0) > 0 ? "text-red-700" : ""}`}>{fmtQty(row.shortage)} {row.unit}</td>
                          <td className="min-w-[260px]">
                            <div className="space-y-1">
                              {row.suggested_batches.slice(0, 3).map((batch) => (
                                <div key={batch.stock_batch_id} className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-[#ecebe3] px-2 py-1">
                                  <span className="text-xs">
                                    <span className="mono font-semibold">{batch.batch_no}</span>
                                    <span className="text-[#8a8472]"> - {fmtQty(batch.suggested_quantity)} {batch.unit}</span>
                                  </span>
                                  {canCreateReservations && (
                                    <button
                                      type="button"
                                      className="btn h-7 px-2 text-xs"
                                      onClick={() => reserveSuggestedBatch(row, batch)}
                                      disabled={reservationBusy === `batch-${batch.stock_batch_id}`}
                                    >
                                      {t("reservation.reserveBatch")}
                                    </button>
                                  )}
                                </div>
                              ))}
                              {row.suggested_batches.length === 0 && (
                                <span className="text-xs text-[#8a8472]">{t("reservation.noSuggestedBatches")}</span>
                              )}
                            </div>
                          </td>
                        </tr>
                      ))}
                      {reservationStatus.plan.rows.length === 0 && (
                        <tr>
                          <td colSpan={6} className="text-sm text-[#8a8472]">{t("reservation.noBomRows")}</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>

                <div className="overflow-x-auto border-t border-[#ecebe3] pt-4">
                  <div className="mb-2 text-sm font-semibold text-[#14110b]">{t("reservation.activeReservations")}</div>
                  <table className="table text-sm">
                    <thead>
                      <tr>
                        <th>{t("field.batch")}</th>
                        <th>{t("field.item")}</th>
                        <th>{t("field.reserved")}</th>
                        <th>{t("common.status")}</th>
                        <th>{t("field.actions")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {reservationStatus.reservations.map((reservation) => (
                        <tr key={reservation.id}>
                          <td className="mono">{reservation.batch_no || "-"}</td>
                          <td>{reservation.item_sku || reservation.item_id}</td>
                          <td className="mono">{fmtQty(reservation.reserved_quantity)} {reservation.unit}</td>
                          <td><span className="badge">{statusLabel(reservation.status, t)}</span></td>
                          <td>
                            {canReleaseReservations && ["reserved", "partially_consumed"].includes(reservation.status) ? (
                              <button
                                type="button"
                                className="btn h-8 px-2 text-xs"
                                onClick={() => releaseReservation(reservation.id)}
                                disabled={reservationBusy === `release-${reservation.id}`}
                              >
                                <RotateCcw className="h-3.5 w-3.5" />
                                {t("btn.releaseReservation")}
                              </button>
                            ) : "-"}
                          </td>
                        </tr>
                      ))}
                      {reservationStatus.reservations.length === 0 && (
                        <tr>
                          <td colSpan={5} className="text-sm text-[#8a8472]">{t("reservation.noReservations")}</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
                {reservationMsg && <div className="text-sm text-[#56503f]">{reservationMsg}</div>}
              </div>
            ) : (
              <div className="text-sm text-[#8a8472]">{activeReservationPoId ? t("common.loading") : t("reservation.selectProductionOrder")}</div>
            )}
          </div>
        </div>
      </section>

      <div className="card p-4 mb-6">
        <h2 className="font-medium mb-3">{t("page.planning.confirmedAwaiting")}</h2>
        <table className="table">
          <thead><tr><th>{t("field.orderNo")}</th><th>{t("field.customer")}</th><th>{t("field.total")}</th><th>{t("common.status")}</th><th></th></tr></thead>
          <tbody>
            {planningOrders.map((o) => (
              <tr key={o.id}>
                <td>{o.order_no}</td>
                <td>{o.customer?.name || o.customer_name || o.customer_id || "-"}</td>
                <td>${Number(o.total_amount).toFixed(2)}</td>
                <td>{statusLabel(o.status, t)}</td>
                <td>
                  <div className="flex flex-wrap gap-2">
                    <button className="btn btn-primary" disabled={busyOrderId === o.id} onClick={() => openMaterialEstimateForSO(o)}>
                      {busyOrderId === o.id ? t("common.creating") : t("btn.createProductionOrder")}
                    </button>
                    <button className="btn" disabled={busyOrderId === o.id} onClick={() => openBatchPlannerForSO(o.id)}>
                      {t("batch.planBatches")}
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {batchPlan && (
        <div className="fixed inset-0 z-40 bg-black/40">
          <div className="absolute inset-0 overflow-y-auto p-4 md:p-6">
            <div className="card !overflow-visible w-full max-w-5xl mx-auto p-5 space-y-4">
              <div className="text-lg font-semibold">{t("batch.planningFor", { orderNo: batchPlan.orderNo })}</div>
              <div className="text-sm text-slate-600">
                {t("batch.splitOrderHint")}
              </div>
              <div className="rounded-md border border-[#ecebe3] bg-[#fbfaf6] p-4">
                <div className="mb-3">
                  <div className="text-sm font-semibold text-[#14110b]">{t("page.planning.materialEstimateTitle")}</div>
                  <div className="mt-1 text-sm text-slate-600">{t("page.planning.materialEstimateHelp")}</div>
                </div>
                <div className="grid grid-cols-1 gap-3 md:grid-cols-[minmax(0,1fr)_180px_120px]">
                  <div>
                    <label className={MATERIAL_ESTIMATE_LABEL_CLASS}>{t("field.fabricBatch")}</label>
                    <SearchableSelect
                      value={batchPlan.fabricBatchId || null}
                      options={fabricBatchOptions(availableFabricBatches, batchPlan.fabricItemIds)}
                      onChange={(batchId) => setBatchPlan((prev) => {
                        if (!prev) return prev;
                        const batch = availableFabricBatches.find((row) => Number(row.id) === Number(batchId));
                        return { ...prev, fabricBatchId: Number(batchId), materialUnit: batch?.unit || prev.materialUnit };
                      })}
                      placeholder={t("field.fabricBatch")}
                      noResultsText={t("page.search.noMatches")}
                      required
                    />
                  </div>
                  <div>
                    <label className={MATERIAL_ESTIMATE_LABEL_CLASS}>{t("page.planning.materialEstimateAmount")}</label>
                    <input
                      className="input"
                      type="number"
                      min={0}
                      step="0.01"
                      value={batchPlan.materialAmount}
                      onChange={(e) => setBatchPlan((prev) => prev ? { ...prev, materialAmount: parseNumberInput(e.target.value) } : prev)}
                    />
                  </div>
                  <div>
                    <label className={MATERIAL_ESTIMATE_LABEL_CLASS}>{t("page.planning.materialEstimateUnit")}</label>
                    <input className="input" value={batchPlan.materialUnit} readOnly />
                  </div>
                </div>
                <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div>
                    <label className="label">{t("field.brand")}</label>
                    <select
                      className="input"
                      value={batchPlan.brandId}
                      onChange={(e) => setBatchPlan((prev) => prev ? { ...prev, brandId: Number(e.target.value) } : prev)}
                      required
                    >
                      <option value={0}>{t("newso.brandSelect")}</option>
                      {activeBrands.map((brand) => <option key={brand.id} value={brand.id}>{brand.name}</option>)}
                    </select>
                    <button
                      type="button"
                      className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-brand-600 hover:underline"
                      onClick={() => openNewBrand("batch")}
                    >
                      <Plus className="h-4 w-4" />
                      {t("common.add")} {t("field.brand")}
                    </button>
                  </div>
                  <div>
                    <label className="label">{t("field.cuttingDepartment")}</label>
                    <select
                      className="input"
                      value={batchPlan.cuttingDepartmentCode}
                      onChange={(e) => setBatchPlan((prev) => prev ? {
                        ...prev,
                        cuttingDepartmentCode: e.target.value as CuttingDepartmentCode,
                      } : prev)}
                    >
                      <option value="CUT">{t("nav.cuttingFloor")}</option>
                      <option value="ECT">{t("nav.ecoCottonCutting")}</option>
                    </select>
                  </div>
                </div>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-[220px_auto] gap-3 items-end">
                <div>
                  <label className="label">{t("batch.maxPiecesPerBatch")}</label>
                  <input
                    className="input"
                    type="number"
                    min={1}
                    value={batchPlan.maxPerBatch}
                    onChange={(e) => setBatchPlan((prev) => prev ? { ...prev, maxPerBatch: parseNumberInput(e.target.value) } : prev)}
                  />
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    className="btn"
                    onClick={() => setBatchPlan((prev) => prev ? { ...prev, rows: autoSplitBatchRows(prev.totalQty, numberOrFallback(prev.maxPerBatch, 1)) } : prev)}
                  >
                    {t("batch.autoSplit")}
                  </button>
                  <button type="button" className="btn" onClick={addBatchPlanRow}>{t("batch.addBatch")}</button>
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
                    {batchPlan.rows.map((row, index) => (
                      <tr key={index}>
                        <td>
                          <input
                            className="input min-w-32"
                            value={row.name}
                            onChange={(e) => updateBatchPlanRow(index, { name: e.target.value })}
                          />
                        </td>
                        <td>
                          <input
                            className="input w-28"
                            type="number"
                            min={1}
                            value={row.planned_quantity}
                            onChange={(e) => updateBatchPlanRow(index, { planned_quantity: parseNumberInput(e.target.value) })}
                          />
                        </td>
                        <td>
                          <input
                            className="input"
                            type="date"
                            value={row.start_date}
                            onChange={(e) => updateBatchPlanRow(index, { start_date: e.target.value })}
                          />
                        </td>
                        <td>
                          <input
                            className="input"
                            type="date"
                            value={row.deadline}
                            onChange={(e) => updateBatchPlanRow(index, { deadline: e.target.value })}
                          />
                        </td>
                        <td>
                          <input
                            className="input min-w-44"
                            value={row.notes}
                            onChange={(e) => updateBatchPlanRow(index, { notes: e.target.value })}
                          />
                        </td>
                        <td>
                          <button type="button" className="btn btn-danger" onClick={() => removeBatchPlanRow(index)} disabled={batchPlan.rows.length <= 1}>
                            {t("btn.remove")}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="text-sm">
                {t("batch.totalInBatches")} <span className="font-semibold">{batchPlan.rows.reduce((sum, row) => sum + Number(row.planned_quantity || 0), 0)}</span> / {batchPlan.totalQty}
              </div>
              {batchPlanErr && <div className="text-sm text-red-600">{batchPlanErr}</div>}
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  className="btn"
                  onClick={() => {
                    setBatchPlan(null);
                    setBatchPlanErr("");
                  }}
                  disabled={busyOrderId === batchPlan.orderId}
                >
                  {t("btn.cancel")}
                </button>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={createPOFromBatchPlan}
                  disabled={busyOrderId === batchPlan.orderId}
                >
                  {busyOrderId === batchPlan.orderId ? t("common.creating") : t("batch.createProductionWithBatches")}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {materialEstimate && (
        <div className="fixed inset-0 z-40 bg-black/40">
          <div className="absolute inset-0 overflow-y-auto p-4 md:p-6">
            <div className="card !overflow-visible w-full max-w-2xl mx-auto p-5 space-y-4">
              <div>
                <div className="text-lg font-semibold">
                  {t("page.planning.materialEstimateTitle")} - {materialEstimate.orderNo}
                </div>
                <div className="mt-1 text-sm text-slate-600">{t("page.planning.materialEstimateHelp")}</div>
              </div>
              <div className="grid grid-cols-1 gap-3 md:grid-cols-[minmax(0,1fr)_180px_120px]">
                <div>
                  <label className={MATERIAL_ESTIMATE_LABEL_CLASS}>{t("field.fabricBatch")}</label>
                  <SearchableSelect
                    value={materialEstimate.fabricBatchId || null}
                    options={fabricBatchOptions(availableFabricBatches, materialEstimate.fabricItemIds)}
                    onChange={(batchId) => setMaterialEstimate((prev) => {
                      if (!prev) return prev;
                      const batch = availableFabricBatches.find((row) => Number(row.id) === Number(batchId));
                      return { ...prev, fabricBatchId: Number(batchId), materialUnit: batch?.unit || prev.materialUnit };
                    })}
                    placeholder={t("field.fabricBatch")}
                    noResultsText={t("page.search.noMatches")}
                    required
                  />
                </div>
                <div>
                  <label className={MATERIAL_ESTIMATE_LABEL_CLASS}>{t("page.planning.materialEstimateAmount")}</label>
                  <input
                    className="input"
                    type="number"
                    min={0}
                    step="0.01"
                    value={materialEstimate.materialAmount}
                    onChange={(e) => setMaterialEstimate((prev) => prev ? { ...prev, materialAmount: parseNumberInput(e.target.value) } : prev)}
                  />
                </div>
                <div>
                  <label className={MATERIAL_ESTIMATE_LABEL_CLASS}>{t("page.planning.materialEstimateUnit")}</label>
                  <input className="input" value={materialEstimate.materialUnit} readOnly />
                </div>
              </div>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <label className="label">{t("field.brand")}</label>
                  <select
                    className="input"
                    value={materialEstimate.brandId}
                    onChange={(e) => setMaterialEstimate((prev) => prev ? { ...prev, brandId: Number(e.target.value) } : prev)}
                    required
                  >
                    <option value={0}>{t("newso.brandSelect")}</option>
                    {activeBrands.map((brand) => <option key={brand.id} value={brand.id}>{brand.name}</option>)}
                  </select>
                  <button
                    type="button"
                    className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-brand-600 hover:underline"
                    onClick={() => openNewBrand("material")}
                  >
                    <Plus className="h-4 w-4" />
                    {t("common.add")} {t("field.brand")}
                  </button>
                </div>
                <div>
                  <label className="label">{t("field.cuttingDepartment")}</label>
                  <select
                    className="input"
                    value={materialEstimate.cuttingDepartmentCode}
                    onChange={(e) => setMaterialEstimate((prev) => prev ? {
                      ...prev,
                      cuttingDepartmentCode: e.target.value as CuttingDepartmentCode,
                    } : prev)}
                  >
                    <option value="CUT">{t("nav.cuttingFloor")}</option>
                    <option value="ECT">{t("nav.ecoCottonCutting")}</option>
                  </select>
                </div>
              </div>
              {materialEstimateErr && <div className="text-sm text-red-600">{materialEstimateErr}</div>}
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  className="btn"
                  onClick={() => {
                    setMaterialEstimate(null);
                    setMaterialEstimateErr("");
                  }}
                  disabled={busyOrderId === materialEstimate.orderId}
                >
                  {t("btn.cancel")}
                </button>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={createPOFromMaterialEstimate}
                  disabled={busyOrderId === materialEstimate.orderId}
                >
                  {busyOrderId === materialEstimate.orderId ? t("common.creating") : t("btn.createProductionOrder")}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

        </>
      ) : null}

      {brandedOnly ? (
        <>

      <BrandedOrderHistory
        orders={brandedOrders || []}
        models={models || []}
        activeOrderId={selectedBrandedOrderId}
        creating={newBrandedOrderSaving}
        error={newBrandedOrderErr}
        onNewOrder={createBrandedPlanningOrder}
        onAddProduction={selectBrandedOrderForProduction}
      />

      {selectedBrandedOrder ? (
      <form id="branded-production-form" onSubmit={createBranded} className="grid scroll-mt-24 grid-cols-1 items-start gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="space-y-4">
        <section className="card">
          <div className="flex items-center justify-between border-b border-[#ecebe3] px-5 py-4">
            <div>
              <h2 className="app-card-title">{t("page.planning.addBrandedProduction")}</h2>
              <p className="mt-1 text-sm text-[#8a8472]">{t("page.planning.activeOrder")}: {selectedBrandedOrder.order_no}</p>
            </div>
            <span className="mono text-sm font-semibold text-[#56503f]">{selectedBrandedOrder?.order_no || "—"}</span>
          </div>
          <div className="border-b border-[#ecebe3] px-5 py-4">
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
              <div>
                <label className="label" htmlFor="branded-approved-model">{t("field.model")}</label>
                <SearchableSelect
                  inputId="branded-approved-model"
                  value={brandedForm.model_id || null}
                  options={brandedModelOptions}
                  onChange={(modelId) => selectBrandedModel(Number(modelId))}
                  placeholder={t("ph.approvedModel")}
                  noResultsText={t("page.search.noMatches")}
                  required
                />
              </div>
              <div>
                <label className="label">{t("field.brand")}</label>
                <select
                  className="input"
                  value={brandedForm.brand_id}
                  onChange={(e) => setBrandedForm((prev) => ({ ...prev, brand_id: Number(e.target.value) }))}
                  required
                >
                  <option value={0}>{t("newso.brandSelect")}</option>
                  {activeBrands.map((brand) => <option key={brand.id} value={brand.id}>{brand.name}</option>)}
                </select>
                <button
                  type="button"
                  className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-brand-600 hover:underline"
                  onClick={() => openNewBrand("branded")}
                >
                  <Plus className="h-4 w-4" />
                  {t("common.add")} {t("field.brand")}
                </button>
              </div>
              <div>
                <label className="label">{t("field.deadline")}</label>
                <input
                  className="input"
                  type="date"
                  value={brandedForm.deadline}
                  onChange={(e) => setBrandedForm((prev) => ({ ...prev, deadline: e.target.value }))}
                />
              </div>
              <div>
                <label className="label">{t("field.cuttingDepartment")}</label>
                <select
                  className="input"
                  value={brandedForm.cutting_department_code}
                  onChange={(e) => setBrandedForm((prev) => ({
                    ...prev,
                    cutting_department_code: e.target.value as CuttingDepartmentCode,
                  }))}
                >
                  <option value="CUT">{t("nav.cuttingFloor")}</option>
                  <option value="ECT">{t("nav.ecoCottonCutting")}</option>
                </select>
              </div>
            </div>
            <div className="mt-4 grid grid-cols-1 gap-4 border-t border-[#ecebe3] pt-4 md:grid-cols-[minmax(0,1fr)_180px_120px]">
              <div>
                <label className="label" htmlFor="branded-fabric-batch">{t("field.fabricBatch")}</label>
                <SearchableSelect
                  inputId="branded-fabric-batch"
                  value={brandedForm.fabric_batch_id || null}
                  options={brandedFabricBatchOptions}
                  onChange={(batchId) => setBrandedForm((prev) => ({ ...prev, fabric_batch_id: Number(batchId) }))}
                  placeholder={brandedForm.model_id ? t("field.fabricBatch") : t("newso.selectModel")}
                  noResultsText={t("page.search.noMatches")}
                  disabled={!brandedForm.model_id}
                  required
                />
              </div>
              <div>
                <label className="label">{t("page.planning.materialEstimateAmount")}</label>
                <input
                  className="input"
                  type="number"
                  min={0}
                  step="0.01"
                  value={brandedForm.estimated_material_amount}
                  onChange={(e) => setBrandedForm((prev) => ({ ...prev, estimated_material_amount: parseNumberInput(e.target.value) }))}
                  required
                />
              </div>
              <div>
                <label className="label">{t("page.planning.materialEstimateUnit")}</label>
                <input className="input" value={selectedBrandedFabricBatch?.unit || DEFAULT_MATERIAL_UNIT} readOnly />
              </div>
            </div>
          </div>
          <div className="flex items-center justify-between border-b border-[#ecebe3] px-5 py-4">
            <div>
              <h2 className="app-card-title">{t("newso.lines")}</h2>
              <p className="mt-1 text-sm text-[#8a8472]">
                {t("newso.linesSummary", { lines: brandedForm.lines.length, qty: brandedTotalQty.toLocaleString() })}
              </p>
            </div>
            <div className="flex items-center gap-2">
              {brandedLinesEditing ? (
                <>
                  {selectedBrandedModelSizes.length > 0 && (
                    <button type="button" className="btn" onClick={restoreBrandedModelSizes}>
                      <RotateCcw />{t("common.cancel")}
                    </button>
                  )}
                  <button type="button" className="btn" onClick={addBrandedLine}><Plus />{t("newso.addLine")}</button>
                </>
              ) : (
                <button type="button" className="btn" onClick={() => setBrandedLinesEditing(true)}>
                  <Pencil />{t("common.edit")}
                </button>
              )}
            </div>
          </div>
          {brandedLinesEditing && (
          <div className="border-b border-[#ecebe3] px-5 py-4">
            <div className="mb-2 text-sm font-semibold text-[#14110b]">{t("newso.sizeHelper")}</div>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-[140px_140px_180px_auto] md:items-end">
              <div>
                <label className="label">{t("newso.sizeFrom")}</label>
                <select className="input" value={brandedSizeFrom} onChange={(e) => setBrandedSizeFrom(e.target.value)}>
                  {brandedSizeOptions.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div>
                <label className="label">{t("newso.sizeTo")}</label>
                <select className="input" value={brandedSizeTo} onChange={(e) => setBrandedSizeTo(e.target.value)}>
                  {brandedSizeOptions.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div>
                <label className="label">{t("newso.sizeTotalQty")}</label>
                <input
                  className="input"
                  type="number"
                  min={1}
                  value={brandedDistributeQty}
                  onChange={(e) => setBrandedDistributeQty(parseNumberInput(e.target.value))}
                />
              </div>
              <div className="flex items-end md:pb-[1px]">
                <button type="button" className="btn btn-primary" onClick={distributeBrandedBySizeRange}>
                  {t("newso.distributeEvenly")}
                </button>
              </div>
            </div>
          </div>
          )}
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>{t("field.color")}</th>
                  <th>{t("field.size")}</th>
                  <th>{t("field.qty")}</th>
                  <th>{t("field.printingRequired")}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {brandedForm.lines.map((line, i) => (
                  <tr key={i}>
                    <td><input className="input min-w-28" value={line.color} onChange={(e) => updateBrandedLine(i, { color: e.target.value })} disabled={!brandedLinesEditing} /></td>
                    <td>
                      <select className="input min-w-24" value={line.size} onChange={(e) => updateBrandedLine(i, { size: e.target.value })} disabled={!brandedLinesEditing}>
                        {brandedSizeOptions.map((s) => <option key={s} value={s}>{s}</option>)}
                      </select>
                    </td>
                    <td>
                      <input
                        className="input w-28"
                        type="number"
                        min={1}
                        value={line.quantity}
                        onChange={(e) => updateBrandedLine(i, { quantity: parseNumberInput(e.target.value) })}
                        disabled={!brandedLinesEditing}
                      />
                    </td>
                    <td>
                      <div className="flex h-9 items-center">
                        <input
                          type="checkbox"
                          checked={line.printing_required}
                          onChange={(e) => updateBrandedLine(i, { printing_required: e.target.checked })}
                          disabled={!brandedLinesEditing}
                        />
                      </div>
                    </td>
                    <td>
                      <button type="button" className="icon-btn text-red-600 disabled:invisible" onClick={() => removeBrandedLine(i)} title={t("newso.remove")} disabled={!brandedLinesEditing}>
                        <Trash2 />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {brandedHasPrintingSelected && (
          <section className="card p-5">
            <div className="mb-4">
              <h2 className="app-card-title">{t("page.newSO.printingDetails")}</h2>
              <p className="mt-1 text-sm text-[#8a8472]">{t("page.newSO.printingVisible")}</p>
            </div>
            <div className="space-y-3">
              <div>
                <label className="label">{t("page.newSO.printingInstructions")}</label>
                <textarea
                  className="input"
                  rows={3}
                  value={brandedPrintingInstructions}
                  onChange={(e) => setBrandedPrintingInstructions(e.target.value)}
                  placeholder={t("page.newSO.printingPlaceholder")}
                />
              </div>
              <div>
                <label className="label">{t("page.newSO.attachPrintingFile")}</label>
                <input
                  className="input"
                  type="file"
                  accept="image/png,image/jpeg,image/webp,image/gif,.pdf,.dxf,.ai"
                  multiple
                  disabled={brandedUploadingPrintFile}
                  onChange={(e) => {
                    onPickBrandedPrintingFiles(e.target.files);
                    e.currentTarget.value = "";
                  }}
                />
                <p className="mt-1 text-xs text-[#8a8472]">{t("page.newSO.printingAttachHelp")}</p>
              </div>
              {brandedUploadingPrintFile && <div className="text-sm text-[#8a8472]">{t("common.uploading")}</div>}
              {brandedPrintingAttachments.length > 0 && (
                <div className="space-y-2">
                  {brandedPrintingAttachments.map((file, idx) => (
                    <div key={`${file.file_url}-${idx}`} className="flex flex-wrap items-center gap-3 rounded-md border border-[#ecebe3] p-2">
                      {isImageAttachment(file) && (
                        <img src={file.file_url} alt={file.file_name || "print"} className="h-12 w-12 rounded object-cover" />
                      )}
                      <a className="text-sm text-[#3b3528] underline" href={file.file_url} target="_blank" rel="noreferrer">
                        {file.file_name || file.file_url}
                      </a>
                      <button
                        type="button"
                        className="btn"
                        onClick={() => setBrandedPrintingAttachments((prev) => prev.filter((_, j) => j !== idx))}
                      >
                        {t("common.remove")}
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </section>
        )}
        </div>

        <aside className="card self-start">
          <div className="border-b border-[#ecebe3] px-5 py-4">
            <h2 className="app-card-title">{t("newso.orderSummary")}</h2>
            <p className="mt-1 text-sm text-[#8a8472]">{t("newso.orderSummarySub")}</p>
          </div>
          <div className="space-y-5 p-5">
            <div className="rounded-lg bg-[#f1efe8] p-4">
              <div className="label">{t("newso.totalQuantity")}</div>
              <div className="mt-1 text-3xl font-semibold">{brandedTotalQty.toLocaleString()}</div>
              <div className="mt-1 text-sm text-[#8a8472]">
                {t("newso.piecesAcross", { qty: brandedTotalQty.toLocaleString(), lines: brandedForm.lines.length })}
              </div>
            </div>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between gap-4">
                <span className="text-[#8a8472]">{t("page.planning.planningOrder")}</span>
                <span className="mono text-right">{selectedBrandedOrder?.order_no || "-"}</span>
              </div>
              <div className="flex justify-between gap-4">
                <span className="text-[#8a8472]">{t("field.model")}</span>
                <span className="text-right">{selectedBrandedModel ? `${selectedBrandedModel.code} - ${selectedBrandedModel.name}` : "-"}</span>
              </div>
              <div className="flex justify-between gap-4">
                <span className="text-[#8a8472]">{t("field.brand")}</span>
                <span className="text-right">{selectedBrandedBrand?.name || "-"}</span>
              </div>
              <div className="flex justify-between gap-4">
                <span className="text-[#8a8472]">{t("field.deadline")}</span>
                <span>{brandedForm.deadline || "-"}</span>
              </div>
              <div className="flex justify-between gap-4">
                <span className="text-[#8a8472]">{t("newso.lines")}</span>
                <span>{brandedForm.lines.length}</span>
              </div>
              <div className="flex justify-between gap-4">
                <span className="text-[#8a8472]">{t("field.printingRequired")}</span>
                <span>{brandedPrintingLineCount}</span>
              </div>
            </div>
            {brandedSuccess ? (
              <div className="rounded-md border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">
                {t("page.planning.productionAdded", { orderNo: brandedSuccess.orderNo })}{" "}
                <Link className="font-semibold underline" href={`/production-orders/${brandedSuccess.id}`}>{t("common.view")}</Link>
              </div>
            ) : null}
            {brandedErr && <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">{brandedErr}</div>}
            <button className="btn btn-primary w-full" disabled={brandedSaving || !selectedBrandedOrderId}>
              {brandedSaving ? t("newso.creating") : t("page.planning.addProduction")}
            </button>
          </div>
        </aside>
      </form>
      ) : null}
        </>
      ) : null}

      <Modal
        open={newBrandTarget !== null}
        onClose={closeNewBrand}
        title={`${t("common.add")} ${t("field.brand")}`}
      >
        <form onSubmit={createNewBrand} className="space-y-3">
          <div>
            <label className="label">{t("common.name")}</label>
            <input
              className="input"
              value={newBrandForm.name}
              onChange={(e) => setNewBrandForm((prev) => ({ ...prev, name: e.target.value }))}
              autoFocus
              required
            />
          </div>
          <div>
            <label className="label">{t("field.description")}</label>
            <textarea
              className="input"
              rows={3}
              value={newBrandForm.description}
              onChange={(e) => setNewBrandForm((prev) => ({ ...prev, description: e.target.value }))}
            />
          </div>
          {newBrandError && <div className="text-sm text-red-600">{newBrandError}</div>}
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" className="btn" onClick={closeNewBrand} disabled={newBrandSaving}>
              {t("btn.cancel")}
            </button>
            <button type="submit" className="btn btn-primary" disabled={newBrandSaving || !newBrandForm.name.trim()}>
              {newBrandSaving ? t("common.creating") : t("btn.create")}
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
