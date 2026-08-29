"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Download, Edit3, PackageCheck, Plus, QrCode, Search, Trash2, X } from "lucide-react";
import useSWR from "swr";
import Modal from "@/components/Modal";
import { api, fetcher } from "@/lib/api";
import { modelOptionsByIdsFetcher, modelOptionsByIdsKey } from "@/lib/useModelOptions";
import { can, useMe } from "@/lib/auth";
import PageHeader from "@/components/PageHeader";
import PaginationControls from "@/components/PaginationControls";
import { useT } from "@/lib/i18n";
import { compositionTotal, type MaterialComposition } from "@/lib/materialComposition";
import { imagePreviewHref, storageThumbnailUrl } from "@/lib/modelImages";
import { orderReference } from "@/lib/orderRef";
import { useDialogs } from "@/components/DialogProvider";
import MaterialQrStickerModal, { type MaterialQrStickerData } from "@/components/MaterialQrStickerModal";

type InventoryGroup = "materials" | "accessories";
const INVENTORY_RENDER_PAGE_SIZE = 80;

type AccessoryIssueRow = {
  production_order_id: number;
  production_no: string;
  order_no?: string | null;
  model_id: number;
  model_code?: string | null;
  model_name?: string | null;
  item_id: number;
  item_sku: string;
  item_name: string;
  item_image_url?: string | null;
  category: string;
  unit: string;
  issued_quantity: number;
  movement_count: number;
  last_issued_at?: string | null;
};

type AccessoryIssueRequestRow = {
  production_order_id: number;
  production_no: string;
  order_no?: string | null;
  model_id: number;
  model_code?: string | null;
  model_name?: string | null;
  planned_quantity: number;
  item_id: number;
  item_sku: string;
  item_name: string;
  item_image_url?: string | null;
  category: string;
  unit: string;
  required_quantity: number;
  issued_quantity: number;
  remaining_quantity: number;
  available_quantity: number;
  shortage: number;
  status: string;
};

type AccessoryIssuePlanRow = {
  item_id: number;
  item_sku: string;
  item_name: string;
  item_image_url?: string | null;
  category: string;
  unit: string;
  required_quantity: number;
  issued_quantity: number;
  remaining_quantity: number;
  available_quantity: number;
  shortage: number;
  status: string;
};

type AccessoryIssuePlan = {
  production_order_id: number;
  production_no: string;
  order_no?: string | null;
  model_id: number;
  model_code?: string | null;
  model_name?: string | null;
  planned_quantity: number;
  rows: AccessoryIssuePlanRow[];
};

type ExtraAccessoryIssueLine = {
  key: string;
  item_id: number;
  item_query: string;
  quantity: string;
  unit: string;
};

type Item = {
  id: number;
  sku: string;
  name: string;
  category: string;
  unit: string;
  default_cost: number;
  reorder_level: number;
  track_batch: boolean;
  is_active: boolean;
  image_url?: string | null;
  composition?: MaterialComposition[] | null;
};

type StockBatch = {
  id: number;
  item_id: number;
  item_sku?: string | null;
  item_name?: string | null;
  batch_no: string;
  internal_batch_no?: string | null;
  supplier_id?: number | null;
  supplier_name?: string | null;
  color?: string | null;
  old_code?: string | null;
  color_code?: string | null;
  color_status?: string | null;
  order_no?: string | null;
  width?: number | string | null;
  gsm?: number | string | null;
  quantity: number;
  piece_count?: number | null;
  roll_weights_kg?: number[] | null;
  processes?: string | null;
  unit: string;
  cost_per_unit: number;
  image_url?: string | null;
  received_date?: string | null;
  warehouse_id?: number | null;
  warehouse_name?: string | null;
  qc_status: string;
  reserved_quantity?: number;
  available_quantity?: number;
};

type BatchForm = {
  item_id: string;
  batch_no: string;
  supplier_id: string;
  color: string;
  old_code: string;
  color_code: string;
  color_status: string;
  order_no: string;
  width: string;
  gsm: string;
  quantity: string;
  piece_count: string;
  processes: string;
  unit: string;
  cost_per_unit: string;
  image_url: string;
  received_date: string;
  warehouse_id: string;
  qc_status: string;
};

type ItemForm = {
  id?: number;
  sku: string;
  name: string;
  category: string;
  unit: string;
  stock_quantity: string;
  default_cost: string;
  reorder_level: string;
  track_batch: boolean;
  is_active: boolean;
  image_url: string;
  composition: Array<{ name: string; percentage: string }>;
};

const GROUPS: { value: InventoryGroup; titleKey: string; subtitleKey: string }[] = [
  { value: "materials", titleKey: "page.inventory.materialTitle", subtitleKey: "page.inventory.materialSubtitle" },
  { value: "accessories", titleKey: "page.inventory.accessoryTitle", subtitleKey: "page.inventory.accessorySubtitle" },
];
const MATERIAL_CATEGORIES = ["fabric", "semi_finished"];
const ACCESSORY_CATEGORIES = ["accessory", "packaging"];
const UNITS = ["kg", "m", "pcs", "roll", "carton"];
const ACCESSORY_ISSUE_UNITS = [
  { value: "pcs", label: "piece" },
  { value: "kg", label: "kg" },
  { value: "m", label: "m" },
];
const EMPTY_MATERIAL_FORM: ItemForm = {
  sku: "",
  name: "",
  category: "fabric",
  unit: "kg",
  stock_quantity: "0",
  default_cost: "0",
  reorder_level: "0",
  track_batch: true,
  is_active: true,
  image_url: "",
  composition: [{ name: "", percentage: "" }],
};
const EMPTY_BATCH_FORM: BatchForm = {
  item_id: "",
  batch_no: "",
  supplier_id: "",
  color: "",
  old_code: "",
  color_code: "",
  color_status: "",
  order_no: "",
  width: "",
  gsm: "",
  quantity: "0",
  piece_count: "",
  processes: "",
  unit: "",
  cost_per_unit: "0",
  image_url: "",
  received_date: "",
  warehouse_id: "",
  qc_status: "pending",
};

function dateTimeLocalValue(value: string | null | undefined) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

function batchToForm(batch: StockBatch): BatchForm {
  return {
    item_id: String(batch.item_id),
    batch_no: batch.batch_no || "",
    supplier_id: batch.supplier_id ? String(batch.supplier_id) : "",
    color: batch.color || "",
    old_code: batch.old_code || "",
    color_code: batch.color_code || "",
    color_status: batch.color_status || "",
    order_no: batch.order_no || "",
    width: batch.width == null ? "" : String(batch.width),
    gsm: batch.gsm == null ? "" : String(batch.gsm),
    quantity: String(Number(batch.quantity || 0)),
    piece_count: batch.piece_count == null ? "" : String(batch.piece_count),
    processes: batch.processes || "",
    unit: batch.unit || "",
    cost_per_unit: String(Number(batch.cost_per_unit || 0)),
    image_url: batch.image_url || "",
    received_date: dateTimeLocalValue(batch.received_date),
    warehouse_id: batch.warehouse_id ? String(batch.warehouse_id) : "",
    qc_status: batch.qc_status || "pending",
  };
}

function optionalNumber(value: string) {
  const trimmed = value.trim();
  return trimmed === "" ? null : Number(trimmed);
}

function batchPayload(form: BatchForm) {
  return {
    item_id: Number(form.item_id),
    batch_no: form.batch_no.trim(),
    supplier_id: form.supplier_id ? Number(form.supplier_id) : null,
    color: form.color.trim() || null,
    old_code: form.old_code.trim() || null,
    color_code: form.color_code.trim() || null,
    color_status: form.color_status.trim() || null,
    order_no: form.order_no.trim() || null,
    width: optionalNumber(form.width),
    gsm: optionalNumber(form.gsm),
    quantity: Number(form.quantity),
    piece_count: optionalNumber(form.piece_count),
    processes: form.processes.trim() || null,
    unit: form.unit.trim(),
    cost_per_unit: Number(form.cost_per_unit || 0),
    image_url: form.image_url.trim() || null,
    received_date: form.received_date ? new Date(form.received_date).toISOString() : null,
    warehouse_id: Number(form.warehouse_id),
    qc_status: form.qc_status,
  };
}

function itemToForm(item: Item, stockQuantity = 0): ItemForm {
  return {
    id: item.id,
    sku: item.sku,
    name: item.name,
    category: item.category,
    unit: item.unit,
    stock_quantity: String(Number(stockQuantity || 0)),
    default_cost: String(Number(item.default_cost || 0)),
    reorder_level: String(Number(item.reorder_level || 0)),
    track_batch: Boolean(item.track_batch),
    is_active: Boolean(item.is_active),
    image_url: item.image_url || "",
    composition: (item.composition || []).length
      ? (item.composition || []).map((row) => ({
          name: String(row.name || ""),
          percentage: String(Number(row.percentage || 0)),
        }))
      : [{ name: "", percentage: "" }],
  };
}

function itemPayload(form: ItemForm) {
  return {
    sku: form.sku.trim(),
    name: form.name.trim(),
    category: form.category,
    unit: form.unit.trim(),
    default_cost: Number(form.default_cost || 0),
    reorder_level: Number(form.reorder_level || 0),
    track_batch: form.track_batch,
    is_active: form.is_active,
    image_url: form.image_url.trim() || null,
    composition: form.composition
      .map((row) => ({ name: row.name.trim(), percentage: Number(row.percentage || 0) }))
      .filter((row) => row.name && Number.isFinite(row.percentage) && row.percentage > 0),
  };
}

function normalizeAccessoryIssueUnit(value: string | null | undefined) {
  const unit = String(value || "").trim().toLowerCase();
  if (unit === "piece" || unit === "pc" || unit === "pcs") return "pcs";
  if (unit === "kg" || unit === "m") return unit;
  return "pcs";
}

function normalizeAccessorySearchText(value: unknown) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[()]/g, " ")
    .replace(/\s+/g, " ");
}

function isItemImageUrl(value: unknown): boolean {
  const url = String(value || "").trim();
  return url.startsWith("/storage/model-files/") || /\.(png|jpe?g|webp|gif)(?:[?#].*)?$/i.test(url);
}

function fmtQty(value: number | string | null | undefined) {
  const n = Number(value || 0);
  return Number.isFinite(n) ? n.toFixed(2) : "0.00";
}

function fmtDecimal(value: number | string | null | undefined, digits = 2) {
  if (value === null || value === undefined || value === "") return "-";
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  return n.toFixed(digits).replace(/\.?0+$/, "") || "0";
}

function textOrDash(value: number | string | null | undefined) {
  const text = String(value ?? "").trim();
  return text || "-";
}

export default function InventoryPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const q = (searchParams.get("q") ?? "").trim();
  const scannedRoll = Math.max(0, Math.floor(Number(searchParams.get("roll") || 0) || 0));
  const scannedRollTotal = Math.max(scannedRoll, Math.floor(Number(searchParams.get("roll_total") || 0) || 0));
  const createdFrom = (searchParams.get("created_from") ?? "").trim();
  const createdTo = (searchParams.get("created_to") ?? "").trim();
  const initialSupplierFilter = Math.max(0, Number(searchParams.get("supplier_id") || 0) || 0);
  const group: InventoryGroup = searchParams.get("group") === "accessories" ? "accessories" : "materials";
  const selectedGroup = GROUPS.find((g) => g.value === group) ?? GROUPS[0];
  const { t, lang } = useT();
  const dialogs = useDialogs();
  const { me } = useMe();
  const canEditItems = can(me, "storage.items", "*");
  const canDeleteBatches = can(me, "inventory.batches.delete", "*");
  const [searchDraft, setSearchDraft] = useState(q);
  const searchTimerRef = useRef<number | null>(null);
  const [supplierFilter, setSupplierFilter] = useState(initialSupplierFilter);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [inventoryRenderLimit, setInventoryRenderLimit] = useState(INVENTORY_RENDER_PAGE_SIZE);
  const [issuePage, setIssuePage] = useState(1);
  const [issuePageSize, setIssuePageSize] = useState(50);
  const [requestPage, setRequestPage] = useState(1);
  const [requestPageSize, setRequestPageSize] = useState(50);
  const [issuePoFilter, setIssuePoFilter] = useState(0);
  const [issueModelFilter, setIssueModelFilter] = useState(0);
  const [editingItem, setEditingItem] = useState<Item | null>(null);
  const [editingBatch, setEditingBatch] = useState<StockBatch | null>(null);
  const [editingStock, setEditingStock] = useState<{ quantity: number; reservedQuantity: number; unit: string } | null>(null);
  const [itemForm, setItemForm] = useState<ItemForm>(EMPTY_MATERIAL_FORM);
  const [batchForm, setBatchForm] = useState<BatchForm>(EMPTY_BATCH_FORM);
  const [savingItem, setSavingItem] = useState(false);
  const [uploadingItemImage, setUploadingItemImage] = useState(false);
  const [editMessage, setEditMessage] = useState("");
  const [issueModalOpen, setIssueModalOpen] = useState(false);
  const [issuingProductionOrderId, setIssuingProductionOrderId] = useState(0);
  const [manualIssueModelId, setManualIssueModelId] = useState(0);
  const [issueQuantities, setIssueQuantities] = useState<Record<number, string>>({});
  const [extraIssueLines, setExtraIssueLines] = useState<ExtraAccessoryIssueLine[]>([]);
  const [issueMessage, setIssueMessage] = useState("");
  const [issueSaving, setIssueSaving] = useState(false);
  const [deletingBatchId, setDeletingBatchId] = useState<number | null>(null);
  const [downloadingReport, setDownloadingReport] = useState<"xlsx" | "pdf" | null>(null);
  const [stickerData, setStickerData] = useState<MaterialQrStickerData | null>(null);
  const stockParams = new URLSearchParams({
    group,
    include_total: "true",
    page: String(page),
    page_size: String(pageSize),
  });
  if (q) stockParams.set("q", q);
  if (createdFrom) stockParams.set("created_from", createdFrom);
  if (createdTo) stockParams.set("created_to", createdTo);
  if (group === "materials" && supplierFilter) stockParams.set("supplier_id", String(supplierFilter));
  const stockUrl = `/api/inventory/stock?${stockParams.toString()}`;
  const { data: stockPage, mutate: refreshStock } = useSWR<any>(stockUrl, fetcher);
  const stock = useMemo<any[]>(() => stockPage?.rows || [], [stockPage]);
  const { data: allAccessoryStock } = useSWR<any[]>(
    group === "accessories" ? "/api/inventory/stock?group=accessories&page_size=500" : null,
    fetcher,
  );
  const itemParams = new URLSearchParams({ group, page_size: "500" });
  const { data: items, mutate: refreshItems } = useSWR<Item[]>(`/api/inventory/items?${itemParams.toString()}`, fetcher);
  const { data: selectableItems } = useSWR<Item[]>(
    editingBatch && canEditItems ? `/api/inventory/items?group=${group}&page_size=500` : null,
    fetcher,
  );
  const { data: warehouses } = useSWR<any[]>(canEditItems ? "/api/inventory/warehouses" : null, fetcher);
  const { data: suppliers } = useSWR<any[]>(group === "materials" || canEditItems ? "/api/suppliers" : null, fetcher);
  const { data: productionOrders } = useSWR<any[]>(group === "accessories" ? "/api/production-orders?page_size=500" : null, fetcher);
  const inventoryModelOptionsKey = group === "accessories"
    ? modelOptionsByIdsKey((productionOrders || []).map((row) => row.model_id))
    : null;
  const { data: models } = useSWR<any[]>(inventoryModelOptionsKey, modelOptionsByIdsFetcher);
  const issueParams = useMemo(() => {
    const params = new URLSearchParams({
      include_total: "true",
      page: String(issuePage),
      page_size: String(issuePageSize),
    });
    if (q) params.set("q", q);
    if (issuePoFilter) params.set("production_order_id", String(issuePoFilter));
    if (issueModelFilter) params.set("model_id", String(issueModelFilter));
    return params.toString();
  }, [issueModelFilter, issuePage, issuePageSize, issuePoFilter, q]);
  const requestParams = useMemo(() => {
    const params = new URLSearchParams({
      include_total: "true",
      page: String(requestPage),
      page_size: String(requestPageSize),
    });
    if (q) params.set("q", q);
    if (issuePoFilter) params.set("production_order_id", String(issuePoFilter));
    if (issueModelFilter) params.set("model_id", String(issueModelFilter));
    return params.toString();
  }, [issueModelFilter, issuePoFilter, q, requestPage, requestPageSize]);
  const { data: requestData, mutate: refreshRequests } = useSWR<any>(
    group === "accessories" ? `/api/inventory/accessory-issue-requests?${requestParams}` : null,
    fetcher,
  );
  const { data: issueData, mutate: refreshIssues } = useSWR<any>(
    group === "accessories" ? `/api/inventory/accessory-issues?${issueParams}` : null,
    fetcher,
  );
  const { data: issuePlan, mutate: refreshIssuePlan } = useSWR<AccessoryIssuePlan>(
    group === "accessories" && issueModalOpen && issuingProductionOrderId
      ? `/api/inventory/accessory-issue-plan?production_order_id=${issuingProductionOrderId}`
      : null,
    fetcher,
  );
  const activeSearch = searchDraft.trim().toLowerCase();
  const issueRows = useMemo<AccessoryIssueRow[]>(() => issueData?.rows || [], [issueData]);
  const issueTotal = Number(issueData?.total || 0);
  const requestRows = useMemo<AccessoryIssueRequestRow[]>(() => requestData?.rows || [], [requestData]);
  const requestTotal = Number(requestData?.total || 0);
  const itemById = useMemo(() => new Map((items || []).map((item) => [Number(item.id), item])), [items]);
  const accessoryStockByItemId = useMemo(() => {
    const map = new Map<number, any>();
    for (const row of allAccessoryStock || []) {
      map.set(Number(row.item_id), row);
    }
    return map;
  }, [allAccessoryStock]);
  const plannedIssueItemIds = useMemo(() => new Set((issuePlan?.rows || []).map((row) => Number(row.item_id))), [issuePlan]);
  const modelAccessoryItems = useMemo(
    () => (items || []).filter((item) => ACCESSORY_CATEGORIES.includes(item.category)),
    [items],
  );
  const accessoryItemsForIssue = useMemo(() => {
    const byId = new Map<number, Item>();
    for (const item of modelAccessoryItems) {
      byId.set(Number(item.id), item);
    }
    for (const row of allAccessoryStock || []) {
      const itemId = Number(row.item_id || 0);
      if (!itemId || byId.has(itemId)) continue;
      const knownItem = itemById.get(itemId);
      if (knownItem) {
        byId.set(itemId, knownItem);
        continue;
      }
      byId.set(itemId, {
        id: itemId,
        sku: String(row.item_sku || ""),
        name: String(row.item_name || ""),
        category: String(row.category || "accessory"),
        unit: normalizeAccessoryIssueUnit(row.unit || "pcs"),
        default_cost: 0,
        reorder_level: 0,
        track_batch: true,
        is_active: true,
        image_url: row.item_image_url || row.image_url || null,
        composition: null,
      });
    }
    return Array.from(byId.values()).filter((item) => item.sku || item.name);
  }, [allAccessoryStock, itemById, modelAccessoryItems]);
  const modelById = useMemo(() => new Map((models || []).map((m) => [Number(m.id), m])), [models]);
  const issueOrderOptions = useMemo(() => {
    return (productionOrders || []).filter((po) => !manualIssueModelId || Number(po.model_id) === Number(manualIssueModelId));
  }, [manualIssueModelId, productionOrders]);
  // The server search also matches batch numbers, purchase orders, suppliers,
  // and warehouse names. Keep the last server result visible while the 350 ms
  // debounced request is pending instead of applying an incomplete item-only
  // filter that can incorrectly flash an empty table for a valid batch number.
  const rows = stock;
  const visibleItemIds = useMemo(() => {
    const ids = rows.map((row) => Number(row.item_id)).filter((id) => Number.isFinite(id) && id > 0);
    return Array.from(new Set(ids));
  }, [rows]);
  const batchUrl = useMemo(() => {
    if (!visibleItemIds.length) return null;
    const params = new URLSearchParams({
      group,
      include_total: "true",
      hide_empty: "true",
      page: "1",
      page_size: "500",
      item_ids: visibleItemIds.join(","),
    });
    if (q) params.set("q", q);
    if (createdFrom) params.set("created_from", createdFrom);
    if (createdTo) params.set("created_to", createdTo);
    if (group === "materials" && supplierFilter) params.set("supplier_id", String(supplierFilter));
    return `/api/inventory/batches?${params.toString()}`;
  }, [createdFrom, createdTo, group, q, supplierFilter, visibleItemIds]);
  const { data: batchPage, mutate: refreshBatches } = useSWR<any>(batchUrl, fetcher);
  const receiveBatches = useMemo<StockBatch[]>(() => batchPage?.rows || [], [batchPage]);
  const batchesByItemId = useMemo(() => {
    const map = new Map<number, StockBatch[]>();
    for (const batch of receiveBatches) {
      const itemId = Number(batch.item_id);
      if (!Number.isFinite(itemId)) continue;
      const current = map.get(itemId) || [];
      current.push(batch);
      map.set(itemId, current);
    }
    return map;
  }, [receiveBatches]);
  const inventoryRows = useMemo(() => {
    return rows.flatMap((itemRow) => {
      const itemBatches = batchesByItemId.get(Number(itemRow.item_id)) || [];
      if (!itemBatches.length) {
        const hasStock =
          Number(itemRow.quantity || 0) > 0 ||
          Number(itemRow.reserved_quantity || 0) > 0 ||
          Number(itemRow.available_quantity || 0) > 0;
        if (!hasStock) return [];
        return [{ key: `item-${itemRow.item_id}`, item: itemRow, batch: null as StockBatch | null }];
      }
      return itemBatches.map((batch) => ({
        key: `batch-${batch.id}`,
        item: itemRow,
        batch,
      }));
    });
  }, [batchesByItemId, rows]);
  const visibleInventoryRows = useMemo(
    () => inventoryRows.slice(0, inventoryRenderLimit),
    [inventoryRenderLimit, inventoryRows],
  );
  const hasMoreInventoryRows = visibleInventoryRows.length < inventoryRows.length;
  const searchApplied = activeSearch === q.toLowerCase();
  const totalLines = activeSearch
    ? (searchApplied ? Number(stockPage?.total || rows.length) : rows.length)
    : Number(stockPage?.total || 0);

  useEffect(() => {
    setPage(1);
    setIssuePage(1);
    setRequestPage(1);
    setInventoryRenderLimit(INVENTORY_RENDER_PAGE_SIZE);
  }, [createdFrom, createdTo, group, q, supplierFilter]);

  useEffect(() => {
    setIssuePage(1);
    setRequestPage(1);
  }, [issueModelFilter, issuePoFilter]);

  useEffect(() => {
    setSearchDraft(q);
  }, [q]);

  useEffect(() => {
    setSupplierFilter(initialSupplierFilter);
  }, [initialSupplierFilter]);

  useEffect(() => {
    const nextQuery = searchDraft.trim();
    if (nextQuery === q) return;

    const timer = window.setTimeout(() => {
      searchTimerRef.current = null;
      const params = new URLSearchParams();
      params.set("group", group);
      if (nextQuery) params.set("q", nextQuery);
      if (createdFrom) params.set("created_from", createdFrom);
      if (createdTo) params.set("created_to", createdTo);
      if (group === "materials" && supplierFilter) params.set("supplier_id", String(supplierFilter));
      router.replace(`/inventory?${params.toString()}`);
      setPage(1);
    }, 200);
    searchTimerRef.current = timer;

    return () => {
      window.clearTimeout(timer);
      if (searchTimerRef.current === timer) searchTimerRef.current = null;
    };
  }, [createdFrom, createdTo, group, q, router, searchDraft, supplierFilter]);

  useEffect(() => {
    if (!issuePlan?.rows) {
      setIssueQuantities({});
      return;
    }
    const next: Record<number, string> = {};
    for (const row of issuePlan.rows) {
      const suggested = Math.min(Number(row.remaining_quantity || 0), Number(row.available_quantity || 0));
      next[row.item_id] = suggested > 0 ? String(Number(suggested.toFixed(4))) : "";
    }
    setIssueQuantities(next);
  }, [issuePlan]);

  function inventoryHref(nextGroup: InventoryGroup, query = q, nextCreatedFrom = createdFrom, nextCreatedTo = createdTo, nextSupplierId = supplierFilter) {
    const params = new URLSearchParams();
    params.set("group", nextGroup);
    const trimmed = query.trim();
    if (trimmed) params.set("q", trimmed);
    if (nextCreatedFrom) params.set("created_from", nextCreatedFrom);
    if (nextCreatedTo) params.set("created_to", nextCreatedTo);
    if (nextGroup === "materials" && nextSupplierId) params.set("supplier_id", String(nextSupplierId));
    const qs = params.toString();
    return `/inventory${qs ? `?${qs}` : ""}`;
  }

  function applySearch() {
    if (searchTimerRef.current !== null) {
      window.clearTimeout(searchTimerRef.current);
      searchTimerRef.current = null;
    }
    router.push(inventoryHref(group, searchDraft));
    setPage(1);
  }

  function submitSearch(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    applySearch();
  }

  function clearSearch() {
    if (searchTimerRef.current !== null) {
      window.clearTimeout(searchTimerRef.current);
      searchTimerRef.current = null;
    }
    setSearchDraft("");
    router.push(inventoryHref(group, ""));
    setPage(1);
  }

  function itemPicture(imageUrl: string | null | undefined, alt: string) {
    const url = String(imageUrl || "").trim();
    if (!url) {
      return (
        <div className="flex h-12 w-12 items-center justify-center rounded-md border border-dashed border-[#ded9ca] bg-[#f8f6ef] text-[10px] leading-tight text-[#8a8472]">
          {t("page.masterData.noImage")}
        </div>
      );
    }
    const isImage = isItemImageUrl(url);
    return (
      <a
        href={isImage ? imagePreviewHref(url, alt) : url}
        target="_blank"
        rel="noreferrer"
        className="flex h-12 w-12 items-center justify-center overflow-hidden rounded-md border border-[#ded9ca] bg-white text-[11px] text-[#8a8472]"
      >
        {isImage ? <img src={storageThumbnailUrl(url, 320)} alt={alt} className="h-full w-full object-cover" /> : t("field.preview")}
      </a>
    );
  }

  function editableItemForRow(row: any, batch: StockBatch | null): Item | null {
    const itemId = Number(row.item_id || batch?.item_id);
    if (!itemId) return null;
    return itemById.get(itemId) || {
      id: itemId,
      sku: String(batch?.item_sku || row.item_sku || ""),
      name: String(batch?.item_name || row.item_name || ""),
      category: group === "materials" ? "fabric" : "accessory",
      unit: rowUnit(row, batch),
      default_cost: Number(batch?.cost_per_unit || 0),
      reorder_level: 0,
      track_batch: true,
      is_active: false,
      image_url: batch?.image_url || row.item_image_url || row.image_url || null,
      composition: null,
    };
  }

  function hasEditableItem(row: { item_id?: number | string | null }, batch: StockBatch | null = null) {
    return canEditItems && Number(row.item_id || batch?.item_id) > 0;
  }

  function itemCost(row: { item_id?: number | string | null }) {
    const item = itemById.get(Number(row.item_id));
    return item ? Number(item.default_cost || 0).toFixed(4) : "-";
  }

  function rowQuantity(row: any, batch: StockBatch | null) {
    return batch ? Number(batch.quantity || 0) : Number(row.quantity || 0);
  }

  function rowReserved(row: any, batch: StockBatch | null) {
    return batch ? Number(batch.reserved_quantity || 0) : Number(row.reserved_quantity || 0);
  }

  function rowAvailable(row: any, batch: StockBatch | null) {
    return batch ? Number(batch.available_quantity ?? batch.quantity) : Number(row.available_quantity ?? row.quantity);
  }

  function rowUnit(row: any, batch: StockBatch | null) {
    return batch?.unit || row.unit;
  }

  function rowCost(row: any, batch: StockBatch | null) {
    return batch ? fmtDecimal(batch.cost_per_unit, 4) : itemCost(row);
  }

  function rowImageUrl(row: any, batch: StockBatch | null) {
    return batch ? batch.image_url : row.item_image_url;
  }

  function batchColorDetails(batch: StockBatch | null) {
    if (!batch) return [];
    return [
      { label: t("field.materialColor"), value: batch.color },
      { label: t("field.oldCode"), value: batch.old_code },
      { label: t("field.colorCode"), value: batch.color_code },
      { label: t("field.colorStatus"), value: batch.color_status },
    ].filter((detail) => textOrDash(detail.value) !== "-");
  }

  function batchReceiveDetails(batch: StockBatch | null) {
    if (!batch) return [];
    return [
      { label: t("field.orderNo"), value: batch.order_no },
      { label: t("field.gramaj"), value: fmtDecimal(batch.gsm, 6) },
      { label: t("field.pieceCount"), value: batch.piece_count },
      { label: t("field.processes"), value: batch.processes },
      { label: t("page.receiveStock.qcStatus"), value: qcLabel(batch.qc_status) },
      { label: t("field.received"), value: receivedDateLabel(batch.received_date) },
    ].filter((detail) => textOrDash(detail.value) !== "-");
  }

  function openMaterialQrSticker(row: any, batch: StockBatch | null) {
    if (!batch) return;
    const sku = String(batch.item_sku || row.item_sku || "").trim();
    const materialName = String(batch?.item_name || row.item_name || "").trim();
    const batchNo = String(batch?.batch_no || "").trim();
    setStickerData({
      batchId: batch.id,
      materialName,
      batchNo,
      color: String(batch?.color || "").trim(),
      batchQuantity: Number(batch.quantity || 0),
      pieceCount: Math.max(1, Math.floor(Number(batch?.piece_count) || 1)),
      supplier: String(batch?.supplier_name || "").trim(),
      searchValue: batchNo || sku || materialName,
    });
  }

  function openEditItem(row: any, batch: StockBatch | null = null) {
    const item = editableItemForRow(row, batch);
    if (!item) {
      setEditMessage(t("page.masterData.actionFailed"));
      return;
    }
    setEditingItem(item);
    setEditingBatch(batch);
    setEditingStock({
      quantity: rowQuantity(row, batch),
      reservedQuantity: rowReserved(row, batch),
      unit: rowUnit(row, batch),
    });
    setItemForm(itemToForm(item, rowQuantity(row, batch)));
    setBatchForm(batch ? batchToForm(batch) : EMPTY_BATCH_FORM);
    setEditMessage("");
  }

  async function deleteBatch(batch: StockBatch) {
    const confirmed = await dialogs.ask({
      message: t("page.inventory.deleteBatchConfirm", { batchNo: batch.batch_no }),
      tone: "danger",
    });
    if (!confirmed) return;
    setDeletingBatchId(batch.id);
    try {
      await api.del(`/api/inventory/batches/${batch.id}`);
      await Promise.all([refreshStock(), refreshBatches()]);
      await dialogs.notify(t("page.inventory.batchDeleted"));
    } catch (error: any) {
      await dialogs.notify(error?.message || t("page.inventory.batchDeleteFailed"));
    } finally {
      setDeletingBatchId(null);
    }
  }

  function openIssueModal(row: AccessoryIssueRequestRow) {
    setIssueModalOpen(true);
    setIssuingProductionOrderId(Number(row.production_order_id));
    setManualIssueModelId(Number(row.model_id || 0));
    setIssueMessage("");
    setExtraIssueLines([]);
  }

  function openManualIssueModal() {
    const selectedOrderId = Number(issuePoFilter || 0);
    const selectedOrder = (productionOrders || []).find((po) => Number(po.id) === selectedOrderId);
    setIssueModalOpen(true);
    setManualIssueModelId(Number(selectedOrder?.model_id || issueModelFilter || 0));
    setIssuingProductionOrderId(selectedOrderId);
    setIssueMessage("");
    setExtraIssueLines([]);
  }

  function closeIssueModal() {
    setIssueModalOpen(false);
    setIssuingProductionOrderId(0);
    setManualIssueModelId(0);
    setIssueMessage("");
    setIssueQuantities({});
    setExtraIssueLines([]);
  }

  function selectIssueModel(modelId: number) {
    setManualIssueModelId(modelId);
    setIssueMessage("");
    setExtraIssueLines([]);
    if (!modelId) return;
    const currentOrder = (productionOrders || []).find((po) => Number(po.id) === Number(issuingProductionOrderId));
    if (currentOrder && Number(currentOrder.model_id) !== Number(modelId)) {
      setIssuingProductionOrderId(0);
    }
  }

  function selectIssueOrder(orderId: number) {
    setIssuingProductionOrderId(orderId);
    setIssueMessage("");
    setExtraIssueLines([]);
    const order = (productionOrders || []).find((po) => Number(po.id) === Number(orderId));
    if (order?.model_id) {
      setManualIssueModelId(Number(order.model_id));
    }
  }

  function accessoryAvailable(itemId: number) {
    const stockRow = accessoryStockByItemId.get(Number(itemId));
    return Number(stockRow?.available_quantity ?? stockRow?.quantity ?? 0);
  }

  function accessoryOptionLabel(item: Item) {
    const available = accessoryAvailable(Number(item.id));
    return `${item.sku} - ${item.name} (${fmtQty(available)} ${item.unit})`;
  }

  function accessoryIssueSearchChoices(item: Item) {
    const sku = String(item.sku || "").trim();
    const name = String(item.name || "").trim();
    return [
      accessoryOptionLabel(item),
      sku,
      name,
      sku && name ? `${sku} - ${name}` : "",
      sku && name ? `${sku} ${name}` : "",
    ].map(normalizeAccessorySearchText).filter(Boolean);
  }

  function accessoryIssueMatches(item: Item, query: string) {
    const normalizedQuery = normalizeAccessorySearchText(query);
    if (!normalizedQuery) return false;
    return accessoryIssueSearchChoices(item).some(
      (choice) => choice === normalizedQuery || choice.includes(normalizedQuery) || normalizedQuery.includes(choice),
    );
  }

  function extraIssueLabel(line: ExtraAccessoryIssueLine) {
    return String(line.item_query || "").trim() || `#${line.key.slice(0, 6)}`;
  }

  function receivedDateLabel(value: string | null | undefined) {
    if (!value) return "-";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "-";
    return date.toLocaleDateString();
  }

  function qcLabel(status: string | null | undefined) {
    const value = String(status || "").trim();
    if (!value) return "-";
    const key = `qc.${value}`;
    const label = t(key);
    return label === key ? value : label;
  }

  function availableExtraAccessoryItems(lineKey: string) {
    const selectedIds = new Set(
      extraIssueLines
        .filter((line) => line.key !== lineKey)
        .map((line) => Number(line.item_id))
        .filter(Boolean),
    );
    return accessoryItemsForIssue.filter(
      (item) => !plannedIssueItemIds.has(Number(item.id)) && !selectedIds.has(Number(item.id)),
    );
  }

  function resolveExtraIssueItem(line: ExtraAccessoryIssueLine, queryOverride?: string) {
    const itemId = Number(line.item_id || 0);
    if (itemId) {
      return accessoryItemsForIssue.find((item) => Number(item.id) === itemId) || itemById.get(itemId) || null;
    }
    const query = queryOverride ?? line.item_query;
    return availableExtraAccessoryItems(line.key).find((item) => accessoryIssueMatches(item, query)) || null;
  }

  function addExtraIssueLine() {
    setExtraIssueLines((current) => [
      ...current,
      {
        key: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
        item_id: 0,
        item_query: "",
        quantity: "",
        unit: "pcs",
      },
    ]);
  }

  function updateExtraIssueLine(lineKey: string, patch: Partial<ExtraAccessoryIssueLine>) {
    setExtraIssueLines((current) => current.map((line) => (line.key === lineKey ? { ...line, ...patch } : line)));
  }

  function updateExtraIssueItem(lineKey: string, value: string) {
    const line = extraIssueLines.find((row) => row.key === lineKey);
    const selected = resolveExtraIssueItem(
      {
        key: lineKey,
        item_id: 0,
        item_query: value,
        quantity: line?.quantity || "",
        unit: line?.unit || "pcs",
      },
      value,
    );
    updateExtraIssueLine(lineKey, {
      item_query: value,
      item_id: selected ? Number(selected.id) : 0,
      unit: selected ? normalizeAccessoryIssueUnit(selected.unit) : normalizeAccessoryIssueUnit(line?.unit || "pcs"),
    });
  }

  function removeExtraIssueLine(lineKey: string) {
    setExtraIssueLines((current) => current.filter((line) => line.key !== lineKey));
  }

  async function submitAccessoryIssue(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIssueMessage("");
    if (!issuingProductionOrderId || !issuePlan) {
      setIssueMessage(t("page.receiveStock.selectPoFirst"));
      return;
    }
    const plannedLines = (issuePlan.rows || [])
      .map((row) => ({
        item_id: row.item_id,
        quantity: Number(issueQuantities[row.item_id] || 0),
        unit: row.unit,
      }))
      .filter((line) => Number.isFinite(line.quantity) && line.quantity > 0);
    const resolvedExtraLines = extraIssueLines.map((line) => {
      const selectedItem = resolveExtraIssueItem(line);
      const label = extraIssueLabel(line);
      return {
        item_id: selectedItem ? Number(selectedItem.id) : undefined,
        item_sku: selectedItem?.sku || label,
        item_name: selectedItem?.name || label,
        quantity: Number(line.quantity || 0),
        unit: normalizeAccessoryIssueUnit(line.unit || selectedItem?.unit || "pcs"),
        manual: true,
      };
    });
    const extraLines = resolvedExtraLines
      .map((line) => ({
        item_id: line.item_id,
        item_sku: line.item_sku,
        item_name: line.item_name,
        quantity: line.quantity,
        unit: line.unit,
        manual: line.manual,
      }))
      .filter((line) => String(line.item_name || "").trim() && Number.isFinite(line.quantity) && line.quantity > 0);
    const lines = [...plannedLines, ...extraLines];
    if (!lines.length) {
      setIssueMessage(t("page.receiveStock.noIssueQty"));
      return;
    }
    setIssueSaving(true);
    try {
      await api.post("/api/inventory/accessory-issues", {
        production_order_id: issuingProductionOrderId,
        lines,
      });
      setIssueMessage(t("msg.recorded"));
      await Promise.all([refreshIssuePlan(), refreshRequests(), refreshIssues(), refreshStock()]);
      closeIssueModal();
    } catch (error: any) {
      setIssueMessage(error?.message || t("page.masterData.actionFailed"));
    } finally {
      setIssueSaving(false);
    }
  }

  function updateCompositionRow(index: number, patch: Partial<{ name: string; percentage: string }>) {
    setItemForm((current) => ({
      ...current,
      composition: current.composition.map((row, rowIndex) => rowIndex === index ? { ...row, ...patch } : row),
    }));
  }

  function addCompositionRow() {
    setItemForm((current) => ({
      ...current,
      composition: [...current.composition, { name: "", percentage: "" }],
    }));
  }

  function removeCompositionRow(index: number) {
    setItemForm((current) => {
      const nextRows = current.composition.filter((_, rowIndex) => rowIndex !== index);
      return { ...current, composition: nextRows.length ? nextRows : [{ name: "", percentage: "" }] };
    });
  }

  async function uploadItemImage(file?: File | null) {
    if (!file) return;
    setUploadingItemImage(true);
    setEditMessage("");
    try {
      const form = new FormData();
      form.append("file", file);
      const response = await api.postForm<{ file_url: string }>("/api/inventory/items/image/upload", form);
      if (editingBatch) {
        setBatchForm((current) => ({ ...current, image_url: response.file_url }));
      } else {
        setItemForm((current) => ({ ...current, image_url: response.file_url }));
      }
    } catch (error: any) {
      setEditMessage(error?.message || t("page.masterData.imageUploadFailed"));
    } finally {
      setUploadingItemImage(false);
    }
  }

  async function downloadMaterialReport(format: "xlsx" | "pdf") {
    setDownloadingReport(format);
    try {
      const reportParams = new URLSearchParams({ lang });
      if (supplierFilter) reportParams.set("supplier_id", String(supplierFilter));
      if (createdFrom) reportParams.set("created_from", createdFrom);
      if (createdTo) reportParams.set("created_to", createdTo);
      const response = await fetch(`/api/inventory/reports/material-stock.${format}?${reportParams.toString()}`, {
        credentials: "same-origin",
      });
      if (!response.ok) {
        let detail = response.statusText;
        try {
          const body = await response.json();
          detail = body.detail || detail;
        } catch {}
        throw new Error(`${response.status}: ${detail}`);
      }
      const blob = await response.blob();
      const disposition = response.headers.get("content-disposition") || "";
      const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1]
        || `material_inventory_report.${format}`;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (error: any) {
      await dialogs.notify(error?.message || t("page.inventory.reportDownloadFailed"));
    } finally {
      setDownloadingReport(null);
    }
  }

  async function saveItem(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editingItem || !canEditItems) return;
    const compositionPercent = compositionTotal(itemForm.composition.map((row) => ({ name: row.name, percentage: Number(row.percentage || 0) })));
    const stockQuantity = Number(itemForm.stock_quantity || 0);
    if (!editingBatch && group === "materials" && compositionPercent > 100.0001) {
      setEditMessage(t("page.masterData.compositionOverLimit"));
      return;
    }
    if (!editingBatch && (!Number.isFinite(stockQuantity) || stockQuantity < 0)) {
      setEditMessage(`${t("field.quantity")} must be zero or greater`);
      return;
    }
    setSavingItem(true);
    setEditMessage("");
    try {
      if (editingBatch) {
        await api.patch(`/api/inventory/batches/${editingBatch.id}?force=true`, batchPayload(batchForm));
      } else {
        await api.patch(`/api/inventory/items/${editingItem.id}`, itemPayload(itemForm));
        await api.patch(`/api/inventory/stock/${editingItem.id}?force=true`, { quantity: stockQuantity, unit: itemForm.unit });
      }
      await Promise.all([refreshItems(), refreshStock(), refreshBatches()]);
      setEditingItem(null);
      setEditingBatch(null);
      setEditingStock(null);
      setItemForm(EMPTY_MATERIAL_FORM);
      setBatchForm(EMPTY_BATCH_FORM);
    } catch (error: any) {
      setEditMessage(error?.message || t("page.masterData.actionFailed"));
    } finally {
      setSavingItem(false);
    }
  }

  const activeCategories = group === "materials" ? MATERIAL_CATEGORIES : ACCESSORY_CATEGORIES;
  const compositionPercent = compositionTotal(itemForm.composition.map((row) => ({ name: row.name, percentage: Number(row.percentage || 0) })));
  const compositionOverLimit = !editingBatch && compositionPercent > 100.0001;
  const stockQuantity = Number(itemForm.stock_quantity || 0);
  const stockQuantityInvalid = !Number.isFinite(stockQuantity) || stockQuantity < 0;
  const stockBelowReserved = Boolean(editingStock && stockQuantity + 0.0001 < editingStock.reservedQuantity);
  const batchQuantity = Number(batchForm.quantity);
  const batchQuantityInvalid = !Number.isFinite(batchQuantity) || batchQuantity < 0;
  const batchBelowReserved = Boolean(editingStock && batchQuantity + 0.0001 < editingStock.reservedQuantity);
  const availableBatchItems = selectableItems || items || [];
  const selectedBatchItem = availableBatchItems.find((item) => item.id === Number(batchForm.item_id)) || editingItem;
  const batchMaterialOptions = [
    ...availableBatchItems,
    ...(editingItem && !availableBatchItems.some((item) => item.id === editingItem.id) ? [editingItem] : []),
  ]
    .filter((item) => item.unit === batchForm.unit || item.id === editingItem?.id)
    .sort((left, right) => left.name.localeCompare(right.name));

  return (
    <div>
      <PageHeader title={t(selectedGroup.titleKey)} subtitle={t(selectedGroup.subtitleKey)} />
      {group === "materials" && scannedRoll > 0 && (
        <div className="mb-4 rounded-md border border-[#cfc7b4] bg-[#f5f2e9] px-3 py-2 text-sm text-[#332d20]" role="status">
          {t("page.inventory.scannedRoll", {
            roll: scannedRoll,
            count: scannedRollTotal || scannedRoll,
            batch: q || "-",
          })}
        </div>
      )}
      {group === "materials" && (
        <div className="mb-4 flex justify-end gap-2">
            <button
              type="button"
              className="btn"
              disabled={Boolean(downloadingReport)}
              onClick={() => void downloadMaterialReport("xlsx")}
            >
              <Download />
              {downloadingReport === "xlsx" ? t("common.loading") : t("page.inventory.excelReport")}
            </button>
            <button
              type="button"
              className="btn"
              disabled={Boolean(downloadingReport)}
              onClick={() => void downloadMaterialReport("pdf")}
            >
              <Download />
              {downloadingReport === "pdf" ? t("common.loading") : t("page.inventory.pdfReport")}
            </button>
        </div>
      )}
      <form onSubmit={submitSearch} className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-center">
        <div className="flex h-10 min-w-0 flex-1 items-center gap-2 rounded-md border border-[#ded9ca] bg-[#fdfcf8] px-3">
          <Search className="h-4 w-4 shrink-0 text-[#8a8472]" />
          <input
            className="w-full min-w-0 bg-transparent text-sm text-[#14110b] placeholder:text-[#8a8472] focus:outline-none"
            placeholder={t("page.inventory.searchPlaceholder")}
            value={searchDraft}
            onChange={(e) => setSearchDraft(e.target.value)}
          />
          {q ? (
            <button type="button" className="icon-btn" onClick={clearSearch} title={t("common.clear")}>
              <X />
            </button>
          ) : null}
        </div>
        <button type="button" className="btn btn-primary sm:w-auto" onClick={applySearch}>
          <Search />
          {t("common.search")}
        </button>
      </form>
      <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:w-[720px] lg:grid-cols-3">
        <label className="block">
          <span className="label">{t("common.createdFrom")}</span>
          <input
            className="input"
            type="date"
            value={createdFrom}
            onChange={(e) => router.push(inventoryHref(group, searchDraft, e.target.value, createdTo))}
          />
        </label>
        <label className="block">
          <span className="label">{t("common.createdTo")}</span>
          <input
            className="input"
            type="date"
            value={createdTo}
            onChange={(e) => router.push(inventoryHref(group, searchDraft, createdFrom, e.target.value))}
          />
        </label>
        {group === "materials" && (
          <label className="block">
            <span className="label">{t("field.supplier")}</span>
            <select
              id="inventory-supplier-filter"
              className="input"
              value={supplierFilter || ""}
              onChange={(event) => {
                const nextSupplierId = Number(event.currentTarget.value) || 0;
                setSupplierFilter(nextSupplierId);
                setPage(1);
              }}
            >
              <option value="">-</option>
              {(suppliers || []).map((supplier) => (
                <option key={supplier.id} value={supplier.id}>{supplier.name}</option>
              ))}
            </select>
          </label>
        )}
      </div>
      <div className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 lg:gap-4">
        <div className="card p-4"><div className="text-xs text-slate-500">{t("page.inventory.itemTypes")}</div><div className="text-2xl font-semibold">{supplierFilter || createdFrom || createdTo ? totalLines : (items?.length ?? 0)}</div></div>
        <div className="card p-4"><div className="text-xs text-slate-500">{t("page.inventory.linesTracked")}</div><div className="text-2xl font-semibold">{totalLines}</div></div>
      </div>
      <div className="card overflow-hidden">
        <div className="divide-y divide-[#ecebe3] md:hidden">
          {visibleInventoryRows.map(({ key, item: s, batch }) => {
            const unit = rowUnit(s, batch);
            const details = batch
              ? [
                  ...batchColorDetails(batch),
                  { label: t("field.supplier"), value: batch.supplier_name },
                  { label: t("field.warehouse"), value: batch.warehouse_name },
                  ...batchReceiveDetails(batch),
                ].filter((detail) => textOrDash(detail.value) !== "-")
              : [];
            return (
              <article key={key} className="flex gap-3 p-4">
                <div className="shrink-0">{itemPicture(rowImageUrl(s, batch), s.item_name || t("field.picture"))}</div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="text-sm font-medium text-[#14110b]">{s.item_name}</div>
                      {batch && (
                        <div className="mt-1 text-xs text-[#6f684f]">
                          {t("field.batch")}: <span className="mono text-[#14110b]">{batch.batch_no}</span>
                        </div>
                      )}
                      {batch?.internal_batch_no && (
                        <div className="mt-1 text-xs text-[#6f684f]">
                          {t("field.internalBatchNo")}: <span className="mono text-[#14110b]">{batch.internal_batch_no}</span>
                        </div>
                      )}
                    </div>
                    <div className="flex shrink-0 gap-1">
                      {group === "materials" && batch && (
                        <button type="button" className="icon-btn" onClick={() => openMaterialQrSticker(s, batch)} title={t("page.inventory.printQrSticker")}>
                          <QrCode />
                        </button>
                      )}
                      {hasEditableItem(s, batch) && (
                        <button type="button" className="icon-btn" onClick={() => openEditItem(s, batch)} title={t("btn.edit")}>
                          <Edit3 />
                        </button>
                      )}
                      {batch && canDeleteBatches && (
                        <button type="button" className="icon-btn text-red-700" disabled={deletingBatchId === batch.id} onClick={() => deleteBatch(batch)} title={t("btn.delete")}>
                          <Trash2 />
                        </button>
                      )}
                    </div>
                  </div>
                  {details.length > 0 && (
                    <div className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
                      {details.map((detail) => (
                        <div key={`${key}-${detail.label}`}>
                          <div className="label mb-0">{detail.label}</div>
                          <div className="break-words text-[#14110b]">{textOrDash(detail.value)}</div>
                        </div>
                      ))}
                    </div>
                  )}
                  <div className="mt-3 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
                    <div>
                      <div className="label mb-0">{t("field.quantity")}</div>
                      <div className="mono font-semibold">{fmtQty(rowQuantity(s, batch))} {unit}</div>
                    </div>
                    <div>
                      <div className="label mb-0">{t("field.reserved")}</div>
                      <div className="mono">{fmtQty(rowReserved(s, batch))} {unit}</div>
                    </div>
                    <div>
                      <div className="label mb-0">{t("field.available")}</div>
                      <div className="mono">{fmtQty(rowAvailable(s, batch))} {unit}</div>
                    </div>
                    <div>
                      <div className="label mb-0">{t("field.cost")}</div>
                      <div className="mono">{rowCost(s, batch)} / {unit}</div>
                    </div>
                  </div>
                </div>
              </article>
            );
          })}
          {inventoryRows.length === 0 && <div className="p-4 text-sm text-[#8a8472]">{t("common.matches", { count: 0 })}</div>}
        </div>
        <div className="hidden overflow-x-auto md:block">
          <table className="table min-w-[1320px]">
            <thead>
              <tr>
                <th>{t("field.picture")}</th>
                <th>{t("field.batch")} / {t("field.internalBatchNo")}</th>
                <th>{t("common.name")} / {t("field.materialColor")}</th>
                <th>{t("field.quantity")}</th>
                <th>{t("field.reserved")}</th>
                <th>{t("field.available")}</th>
                <th>{t("field.unit")}</th>
                <th>{t("field.cost")}</th>
                <th>{t("field.supplier")} / {t("field.warehouse")}</th>
                <th>{t("field.orderNo")} / {t("page.receiveStock.qcStatus")}</th>
                {(group === "materials" || canEditItems || canDeleteBatches) && <th>{t("field.actions")}</th>}
              </tr>
            </thead>
            <tbody>
              {visibleInventoryRows.map(({ key, item: s, batch }) => {
                const unit = rowUnit(s, batch);
                const colorDetails = batchColorDetails(batch);
                const receiveDetails = batchReceiveDetails(batch);
                return (
                  <tr key={key}>
                    <td>{itemPicture(rowImageUrl(s, batch), s.item_name || t("field.picture"))}</td>
                    <td>
                      {batch ? (
                        <div>
                          <div className="mono font-semibold text-[#14110b]">{batch.batch_no}</div>
                          {batch.internal_batch_no && (
                            <div className="mt-1 text-xs text-[#6f684f]">
                              {t("field.internalBatchNo")}: <span className="mono text-[#14110b]">{batch.internal_batch_no}</span>
                            </div>
                          )}
                        </div>
                      ) : "-"}
                    </td>
                    <td className="min-w-[220px]">
                      <div className="font-medium text-[#14110b]">{s.item_name}</div>
                      {colorDetails.length > 0 && (
                        <div className="mt-1 flex max-w-[280px] flex-wrap gap-x-3 gap-y-1 text-xs text-[#6f684f]">
                          {colorDetails.map((detail) => (
                            <span key={`${key}-${detail.label}`}>
                              {detail.label}: <span className="text-[#14110b]">{textOrDash(detail.value)}</span>
                            </span>
                          ))}
                        </div>
                      )}
                    </td>
                    <td className="mono">{fmtQty(rowQuantity(s, batch))}</td>
                    <td className="mono">{fmtQty(rowReserved(s, batch))}</td>
                    <td className="mono">{fmtQty(rowAvailable(s, batch))}</td>
                    <td>{unit}</td>
                    <td className="mono">{rowCost(s, batch)}</td>
                    <td className="min-w-[170px]">
                      {batch ? (
                        <div className="space-y-1 text-sm">
                          <div>{textOrDash(batch.supplier_name)}</div>
                          <div className="text-xs text-[#6f684f]">{textOrDash(batch.warehouse_name)}</div>
                        </div>
                      ) : "-"}
                    </td>
                    <td className="min-w-[210px]">
                      {receiveDetails.length > 0 ? (
                        <div className="flex max-w-[260px] flex-wrap gap-x-3 gap-y-1 text-xs text-[#6f684f]">
                          {receiveDetails.map((detail) => (
                            <span key={`${key}-${detail.label}`}>
                              {detail.label}: <span className="text-[#14110b]">{textOrDash(detail.value)}</span>
                            </span>
                          ))}
                        </div>
                      ) : "-"}
                    </td>
                    {(group === "materials" || canEditItems || canDeleteBatches) && (
                      <td>
                        <div className="flex gap-1">
                          {group === "materials" && batch && (
                            <button type="button" className="icon-btn" onClick={() => openMaterialQrSticker(s, batch)} title={t("page.inventory.printQrSticker")}>
                              <QrCode />
                            </button>
                          )}
                          {hasEditableItem(s, batch) && (
                            <button type="button" className="icon-btn" onClick={() => openEditItem(s, batch)} title={t("btn.edit")}>
                              <Edit3 />
                            </button>
                          )}
                          {batch && canDeleteBatches && (
                            <button type="button" className="icon-btn text-red-700" disabled={deletingBatchId === batch.id} onClick={() => deleteBatch(batch)} title={t("btn.delete")}>
                              <Trash2 />
                            </button>
                          )}
                        </div>
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
          {inventoryRows.length === 0 && <div className="border-t border-[#ecebe3] p-4 text-sm text-[#8a8472]">{t("common.matches", { count: 0 })}</div>}
        </div>
        {hasMoreInventoryRows && (
          <div className="border-t border-[#ecebe3] p-3 text-center">
            <button
              type="button"
              className="btn"
              onClick={() => setInventoryRenderLimit((current) => (
                Math.min(current + INVENTORY_RENDER_PAGE_SIZE, inventoryRows.length)
              ))}
            >
              {t("common.loadMore")}
            </button>
          </div>
        )}
        <PaginationControls
          page={page}
          pageSize={pageSize}
          total={totalLines || rows.length}
          count={inventoryRows.length}
          onPageChange={setPage}
          onPageSizeChange={(size) => { setPageSize(size); setPage(1); }}
        />
      </div>
      <MaterialQrStickerModal
        data={stickerData}
        onClose={() => setStickerData(null)}
      />
      <Modal
        open={Boolean(editingItem)}
        onClose={() => {
          setEditingItem(null);
          setEditingBatch(null);
          setEditingStock(null);
          setBatchForm(EMPTY_BATCH_FORM);
          setEditMessage("");
        }}
        title={t("page.masterData.editItem")}
        wide
      >
        <form onSubmit={saveItem} className="space-y-3">
          {editMessage && (
            <div className="rounded-md border border-[#ded9ca] bg-[#fbfaf6] px-3 py-2 text-sm text-[#56503f]">
              {editMessage}
            </div>
          )}
          {editingBatch ? (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <label className="label">{t("field.materialName")}</label>
                <select
                  className="input"
                  value={batchForm.item_id}
                  onChange={(event) => setBatchForm({ ...batchForm, item_id: event.target.value })}
                  required
                >
                  <option value="">-</option>
                  {batchMaterialOptions.map((item) => (
                    <option key={item.id} value={item.id}>{item.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="label">{t("field.supplier")}</label>
                <select className="input" value={batchForm.supplier_id} onChange={(event) => setBatchForm({ ...batchForm, supplier_id: event.target.value })}>
                  <option value="">{t("ph.supplier")}</option>
                  {(suppliers || []).map((supplier) => <option key={supplier.id} value={supplier.id}>{supplier.name}</option>)}
                </select>
              </div>
            </div>
          ) : (
            <>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <label className="label">{t("field.sku")}</label>
                  <input className="input" value={itemForm.sku} onChange={(event) => setItemForm({ ...itemForm, sku: event.target.value })} required />
                </div>
                <div>
                  <label className="label">{t("common.name")}</label>
                  <input className="input" value={itemForm.name} onChange={(event) => setItemForm({ ...itemForm, name: event.target.value })} required />
                </div>
              </div>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <label className="label">{t("field.category")}</label>
                  <select className="input" value={itemForm.category} onChange={(event) => setItemForm({ ...itemForm, category: event.target.value })}>
                    {activeCategories.map((category) => (
                      <option key={category} value={category}>{t(`itemCategory.${category}`)}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="label">{t("field.unit")}</label>
                  <select className="input" value={itemForm.unit} onChange={(event) => setItemForm({ ...itemForm, unit: event.target.value })}>
                    {UNITS.map((unit) => <option key={unit} value={unit}>{unit}</option>)}
                  </select>
                </div>
              </div>
            </>
          )}
          <div>
            <label className="label">{editingBatch ? t("page.inventory.batchPicture") : t("field.picture")}</label>
            <div className="rounded-md border border-[#ecebe3] bg-[#fbfaf6] p-3">
              <div className="flex items-start gap-3">
                <div className="shrink-0">{itemPicture(editingBatch ? batchForm.image_url : itemForm.image_url, selectedBatchItem?.name || itemForm.name || t("field.picture"))}</div>
                <div className="min-w-0 flex-1 space-y-2">
                  <input
                    className="input"
                    value={editingBatch ? batchForm.image_url : itemForm.image_url}
                    onChange={(event) => {
                      if (editingBatch) {
                        setBatchForm({ ...batchForm, image_url: event.target.value });
                      } else {
                        setItemForm({ ...itemForm, image_url: event.target.value });
                      }
                    }}
                    placeholder={t("page.masterData.imageUrl")}
                  />
                  <label className={`btn inline-flex cursor-pointer px-3 py-2 text-sm ${uploadingItemImage || savingItem ? "pointer-events-none opacity-60" : ""}`}>
                    {uploadingItemImage ? t("common.uploading") : t("page.masterData.uploadImage")}
                    <input
                      type="file"
                      accept="image/png,image/jpeg,image/webp,image/gif"
                      className="hidden"
                      disabled={uploadingItemImage || savingItem}
                      onChange={(event) => {
                        void uploadItemImage(event.currentTarget.files?.[0] || null);
                        event.currentTarget.value = "";
                      }}
                    />
                  </label>
                </div>
              </div>
            </div>
          </div>
          {group === "materials" && !editingBatch && (
            <div className="space-y-2 rounded-md border border-[#ecebe3] bg-[#fbfaf6] p-3">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-medium text-[#14110b]">{t("field.composition")}</div>
                  <div className={`text-xs ${compositionOverLimit ? "text-red-700" : "text-[#8a8472]"}`}>
                    {t("page.masterData.compositionTotal", { total: Number(compositionPercent.toFixed(2)) })}
                  </div>
                </div>
                <button type="button" className="btn h-8 px-2 text-xs" onClick={addCompositionRow}>
                  <Plus className="h-3.5 w-3.5" />
                  {t("page.masterData.addCompositionRow")}
                </button>
              </div>
              <div className="space-y-2">
                {itemForm.composition.map((row, index) => (
                  <div key={index} className="grid grid-cols-[minmax(0,1fr)_96px_32px] gap-2">
                    <input
                      className="input"
                      placeholder={t("page.masterData.compositionName")}
                      value={row.name}
                      onChange={(event) => updateCompositionRow(index, { name: event.target.value })}
                    />
                    <input
                      className="input"
                      type="number"
                      min={0}
                      max={100}
                      step="0.01"
                      placeholder="%"
                      value={row.percentage}
                      onChange={(event) => updateCompositionRow(index, { percentage: event.target.value })}
                    />
                    <button type="button" className="icon-btn" onClick={() => removeCompositionRow(index)} title={t("common.remove")}>
                      <Trash2 />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
          {editingBatch && (
            <section className="space-y-3 rounded-md border border-[#ded9ca] bg-[#fbfaf6] p-3">
              <div>
                <div className="text-sm font-medium text-[#14110b]">{t("field.batch")}</div>
                <div className="text-xs text-[#8a8472]">Edit the receipt-specific values for this stock row.</div>
              </div>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                <div>
                  <label className="label">{t("field.batchNo")}</label>
                  <input className="input" value={batchForm.batch_no} onChange={(event) => setBatchForm({ ...batchForm, batch_no: event.target.value })} required />
                </div>
                <div>
                  <label className="label">{t("field.quantity")} ({batchForm.unit || "-"})</label>
                  <input className={`input ${batchBelowReserved || batchQuantityInvalid ? "border-red-400" : ""}`} type="number" min={0} step="0.0001" value={batchForm.quantity} onChange={(event) => setBatchForm({ ...batchForm, quantity: event.target.value })} required />
                  {editingStock && <div className={`mt-1 text-xs ${batchBelowReserved ? "text-red-700" : "text-[#8a8472]"}`}>{t("field.reserved")}: {editingStock.reservedQuantity.toFixed(2)} {editingStock.unit}</div>}
                </div>
                <div>
                  <label className="label">{`${t("field.cost")} / ${t("field.unit")}`}</label>
                  <input className="input" type="number" min={0} step="0.0001" value={batchForm.cost_per_unit} onChange={(event) => setBatchForm({ ...batchForm, cost_per_unit: event.target.value })} required />
                </div>
                <div>
                  <label className="label">{t("field.warehouse")}</label>
                  <select className="input" value={batchForm.warehouse_id} onChange={(event) => setBatchForm({ ...batchForm, warehouse_id: event.target.value })} required>
                    <option value="">-</option>
                    {(warehouses || []).map((warehouse) => <option key={warehouse.id} value={warehouse.id}>{warehouse.name}</option>)}
                  </select>
                </div>
                <div>
                  <label className="label">{t("page.receiveStock.qcStatus")}</label>
                  <select className="input" value={batchForm.qc_status} onChange={(event) => setBatchForm({ ...batchForm, qc_status: event.target.value })}>
                    {['pending', 'passed', 'failed', 'rejected', 'hold'].map((status) => <option key={status} value={status}>{qcLabel(status)}</option>)}
                  </select>
                </div>
                <div>
                  <label className="label">{t("field.materialColor")}</label>
                  <input className="input" value={batchForm.color} onChange={(event) => setBatchForm({ ...batchForm, color: event.target.value })} />
                </div>
                <div>
                  <label className="label">{t("field.oldCode")}</label>
                  <input className="input" value={batchForm.old_code} onChange={(event) => setBatchForm({ ...batchForm, old_code: event.target.value })} />
                </div>
                <div>
                  <label className="label">{t("field.colorCode")}</label>
                  <input className="input" value={batchForm.color_code} onChange={(event) => setBatchForm({ ...batchForm, color_code: event.target.value })} />
                </div>
                <div>
                  <label className="label">{t("field.colorStatus")}</label>
                  <input className="input" value={batchForm.color_status} onChange={(event) => setBatchForm({ ...batchForm, color_status: event.target.value })} />
                </div>
                <div>
                  <label className="label">{t("field.orderNo")}</label>
                  <input className="input" value={batchForm.order_no} onChange={(event) => setBatchForm({ ...batchForm, order_no: event.target.value })} />
                </div>
                <div>
                  <label className="label">{t("field.gramaj")}</label>
                  <input className="input" type="number" min={0} step="0.000001" value={batchForm.gsm} onChange={(event) => setBatchForm({ ...batchForm, gsm: event.target.value })} />
                </div>
                <div>
                  <label className="label">Width</label>
                  <input className="input" type="number" min={0} step="0.01" value={batchForm.width} onChange={(event) => setBatchForm({ ...batchForm, width: event.target.value })} />
                </div>
                <div>
                  <label className="label">{t("field.pieceCount")}</label>
                  <input className="input" type="number" min={0} step="1" value={batchForm.piece_count} onChange={(event) => setBatchForm({ ...batchForm, piece_count: event.target.value })} />
                </div>
                <div>
                  <label className="label">{t("field.received")}</label>
                  <input className="input" type="datetime-local" value={batchForm.received_date} onChange={(event) => setBatchForm({ ...batchForm, received_date: event.target.value })} required />
                </div>
                <div className="sm:col-span-2">
                  <label className="label">{t("field.processes")}</label>
                  <input className="input" value={batchForm.processes} onChange={(event) => setBatchForm({ ...batchForm, processes: event.target.value })} />
                </div>
              </div>
            </section>
          )}
          {!editingBatch && (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <div>
                <label className="label">{t("field.quantity")} ({itemForm.unit || editingStock?.unit || "-"})</label>
                <input
                  className={`input ${stockBelowReserved || stockQuantityInvalid ? "border-red-400" : ""}`}
                  type="number"
                  min={0}
                  step="0.0001"
                  value={itemForm.stock_quantity}
                  onChange={(event) => setItemForm({ ...itemForm, stock_quantity: event.target.value })}
                  required
                />
                {editingStock && (
                  <div className={`mt-1 text-xs ${stockBelowReserved ? "text-red-700" : "text-[#8a8472]"}`}>
                    {t("field.reserved")}: {editingStock.reservedQuantity.toFixed(2)} {editingStock.unit}
                  </div>
                )}
              </div>
              <div>
                <label className="label">Default {t("field.cost").toLowerCase()}</label>
                <input className="input" type="number" min={0} step="0.0001" value={itemForm.default_cost} onChange={(event) => setItemForm({ ...itemForm, default_cost: event.target.value })} />
              </div>
              <div>
                <label className="label">{t("page.masterData.reorderLevel")}</label>
                <input className="input" type="number" min={0} step="0.0001" value={itemForm.reorder_level} onChange={(event) => setItemForm({ ...itemForm, reorder_level: event.target.value })} />
              </div>
            </div>
          )}
          {!editingBatch && (
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              <label className="flex items-center gap-2 text-sm text-[#56503f]">
                <input type="checkbox" checked={itemForm.track_batch} onChange={(event) => setItemForm({ ...itemForm, track_batch: event.target.checked })} />
                {t("page.masterData.trackBatch")}
              </label>
              <label className="flex items-center gap-2 text-sm text-[#56503f]">
                <input type="checkbox" checked={itemForm.is_active} onChange={(event) => setItemForm({ ...itemForm, is_active: event.target.checked })} />
                {t("page.masterData.active")}
              </label>
            </div>
          )}
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" className="btn" onClick={() => { setEditingItem(null); setEditingBatch(null); setEditingStock(null); setBatchForm(EMPTY_BATCH_FORM); }}>
              {t("btn.cancel")}
            </button>
            <button className="btn btn-primary" disabled={savingItem || uploadingItemImage || !canEditItems || (editingBatch ? (batchQuantityInvalid || !batchForm.item_id || !batchForm.warehouse_id || !batchForm.batch_no.trim()) : stockQuantityInvalid) || compositionOverLimit}>
              {savingItem ? t("common.saving") : t("btn.save")}
            </button>
          </div>
        </form>
      </Modal>
      <Modal
        open={issueModalOpen}
        onClose={closeIssueModal}
        title={t("page.receiveStock.issueAccessories")}
        wide
      >
        <form onSubmit={submitAccessoryIssue} className="space-y-4">
          {issueMessage && (
            <div className="rounded-md border border-[#ded9ca] bg-[#fbfaf6] px-3 py-2 text-sm text-[#56503f]">
              {issueMessage}
            </div>
          )}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label className="label">{t("field.modelNumber")}</label>
              <select
                className="input"
                value={manualIssueModelId}
                onChange={(event) => selectIssueModel(Number(event.target.value))}
              >
                <option value={0}>{t("common.all")}</option>
                {models?.map((model) => (
                  <option key={model.id} value={model.id}>
                    {[model.code, model.name].filter(Boolean).join(" - ") || `#${model.id}`}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="label">{t("field.orderNo")}</label>
              <select
                className="input"
                value={issuingProductionOrderId}
                onChange={(event) => selectIssueOrder(Number(event.target.value))}
              >
                <option value={0}>{t("page.receiveStock.selectProductionOrder")}</option>
                {issueOrderOptions.map((po) => {
                  const model = modelById.get(Number(po.model_id));
                  const modelLabel = [model?.code, model?.name].filter(Boolean).join(" - ") || po.model_id;
                  return (
                    <option key={po.id} value={po.id}>
                      {[orderReference(po, `#${po.id}`), modelLabel].filter(Boolean).join(" - ")}
                    </option>
                  );
                })}
              </select>
            </div>
          </div>
          {issuePlan && (
            <div className="rounded-md border border-[#ecebe3] bg-[#fbfaf6] p-3 text-sm text-[#56503f]">
              <div className="mono font-semibold text-[#14110b]">{orderReference(issuePlan, issuePlan.production_no)}</div>
              <div className="mt-1">
                {[issuePlan.model_code, issuePlan.model_name].filter(Boolean).join(" - ") || `#${issuePlan.model_id}`}
                {" - "}
                {t("page.poDetail.plannedQty")}: {issuePlan.planned_quantity}
              </div>
            </div>
          )}
          <div className="overflow-x-auto rounded-md border border-[#ecebe3]">
            <table className="table">
              <thead>
                <tr>
                  <th>{t("field.picture")}</th>
                  <th>{t("field.accessory")}</th>
                  <th>{t("field.required")}</th>
                  <th>{t("page.receiveStock.issuedQty")}</th>
                  <th>{t("field.remaining")}</th>
                  <th>{t("field.available")}</th>
                  <th>{t("page.receiveStock.issueNow")}</th>
                </tr>
              </thead>
              <tbody>
                {issuePlan?.rows?.map((row) => (
                  <tr key={`${row.item_id}-${row.unit}`}>
                    <td>{itemPicture(row.item_image_url, row.item_name || t("field.picture"))}</td>
                    <td>
                      <div className="max-w-[220px] truncate text-sm text-[#56503f]">{row.item_name}</div>
                    </td>
                    <td className="mono">{fmtQty(row.required_quantity)} {row.unit}</td>
                    <td className="mono">{fmtQty(row.issued_quantity)} {row.unit}</td>
                    <td className="mono font-semibold text-[#14110b]">{fmtQty(row.remaining_quantity)} {row.unit}</td>
                    <td className={`mono ${Number(row.shortage || 0) > 0 ? "text-red-700" : ""}`}>{fmtQty(row.available_quantity)} {row.unit}</td>
                    <td>
                      <input
                        className="input min-w-[112px]"
                        type="number"
                        min={0}
                        step="0.0001"
                        max={Math.min(Number(row.remaining_quantity || 0), Number(row.available_quantity || 0))}
                        value={issueQuantities[row.item_id] ?? ""}
                        onChange={(event) => setIssueQuantities({ ...issueQuantities, [row.item_id]: event.target.value })}
                      />
                    </td>
                  </tr>
                ))}
                {issuingProductionOrderId > 0 && issuePlan?.rows?.length === 0 && (
                  <tr>
                    <td colSpan={7} className="text-sm text-slate-400">{t("page.receiveStock.noAccessoryBom")}</td>
                  </tr>
                )}
                {!issuingProductionOrderId && (
                  <tr>
                    <td colSpan={7} className="text-sm text-slate-400">{t("page.receiveStock.selectPoFirst")}</td>
                  </tr>
                )}
                {issuingProductionOrderId > 0 && !issuePlan && (
                  <tr>
                    <td colSpan={7} className="text-sm text-slate-400">{t("common.loading")}</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="rounded-md border border-[#ecebe3] p-3">
            <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <div className="text-sm font-semibold text-[#14110b]">{t("common.add")} {t("field.accessory").toLowerCase()}</div>
              <button type="button" className="btn h-8 px-2 text-xs" onClick={addExtraIssueLine}>
                <Plus className="h-3.5 w-3.5" />
                {t("common.add")} {t("field.accessory").toLowerCase()}
              </button>
            </div>
            <div className="space-y-2">
              {extraIssueLines.map((line) => {
                const options = availableExtraAccessoryItems(line.key);
                const selectedItem = resolveExtraIssueItem(line);
                const available = selectedItem ? accessoryAvailable(Number(selectedItem.id)) : 0;
                return (
                  <div key={line.key} className="grid grid-cols-1 gap-2 sm:grid-cols-[minmax(0,1fr)_120px_96px_36px]">
                    <div>
                      <input
                        className="input"
                        list={`accessory-options-${line.key}`}
                        placeholder={t("page.inventory.searchPlaceholder")}
                        value={line.item_query}
                        onChange={(event) => updateExtraIssueItem(line.key, event.target.value)}
                      />
                      <datalist id={`accessory-options-${line.key}`}>
                        {options.map((item) => (
                          <option key={item.id} value={accessoryOptionLabel(item)} />
                        ))}
                      </datalist>
                      {selectedItem && (
                        <div className="mt-1 text-xs text-[#8a8472]">
                          {t("field.available")}: {fmtQty(available)} {selectedItem.unit}
                        </div>
                      )}
                    </div>
                    <input
                      className="input"
                      type="number"
                      min={0}
                      step="0.0001"
                      max={selectedItem ? available : undefined}
                      placeholder={t("field.quantity")}
                      value={line.quantity}
                      onChange={(event) => updateExtraIssueLine(line.key, { quantity: event.target.value })}
                    />
                    <select
                      className="input"
                      value={normalizeAccessoryIssueUnit(line.unit || selectedItem?.unit || "pcs")}
                      onChange={(event) => updateExtraIssueLine(line.key, { unit: event.target.value })}
                    >
                      {ACCESSORY_ISSUE_UNITS.map((unit) => (
                        <option key={unit.value} value={unit.value}>{unit.label}</option>
                      ))}
                    </select>
                    <button type="button" className="icon-btn" onClick={() => removeExtraIssueLine(line.key)} title={t("common.remove")}>
                      <Trash2 />
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <button type="button" className="btn" onClick={closeIssueModal}>{t("btn.cancel")}</button>
            <button className="btn btn-primary" disabled={issueSaving || !issuingProductionOrderId || !issuePlan}>
              {issueSaving ? t("common.saving") : t("page.receiveStock.issueAccessories")}
            </button>
          </div>
        </form>
      </Modal>
      {group === "accessories" && (
        <div className="card mt-6 overflow-hidden">
          <div className="border-b border-[#ecebe3] p-4">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
              <div>
                <div className="app-card-title">{t("page.inventory.accessoryRequestsTitle")}</div>
                <div className="mt-1 text-sm text-[#6f684f]">{t("page.inventory.accessoryRequestsSubtitle")}</div>
              </div>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-[minmax(180px,220px)_minmax(180px,220px)_auto]">
                <div>
                  <label className="label">{t("field.orderNo")}</label>
                  <select className="input" value={issuePoFilter} onChange={(e) => setIssuePoFilter(Number(e.target.value))}>
                    <option value={0}>{t("common.all")}</option>
                    {productionOrders?.map((po) => (
                      <option key={po.id} value={po.id}>
                        {orderReference(po, `#${po.id}`)}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="label">{t("field.modelNumber")}</label>
                  <select className="input" value={issueModelFilter} onChange={(e) => setIssueModelFilter(Number(e.target.value))}>
                    <option value={0}>{t("common.all")}</option>
                    {models?.map((model) => (
                      <option key={model.id} value={model.id}>
                        {[model.code, model.name].filter(Boolean).join(" - ") || `#${model.id}`}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="sm:col-span-2 lg:col-span-1 lg:self-end">
                  <button type="button" className="btn btn-primary h-10 w-full lg:w-auto" onClick={openManualIssueModal}>
                    <PackageCheck className="h-4 w-4" />
                    {t("page.inventory.manualIssue")}
                  </button>
                </div>
              </div>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>{t("field.orderNo")}</th>
                  <th>{t("field.modelNumber")}</th>
                  <th>{t("field.picture")}</th>
                  <th>{t("common.name")}</th>
                  <th>{t("field.required")}</th>
                  <th>{t("page.inventory.issuedQty")}</th>
                  <th>{t("field.remaining")}</th>
                  <th>{t("field.available")}</th>
                  <th>{t("field.shortage")}</th>
                  <th>{t("field.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {requestRows.map((row) => {
                  const model = modelById.get(Number(row.model_id));
                  const modelLabel = [row.model_code || model?.code, row.model_name || model?.name].filter(Boolean).join(" - ") || `#${row.model_id}`;
                  return (
                    <tr key={`${row.production_order_id}-${row.item_id || row.item_sku || row.item_name}-${row.unit}`}>
                      <td className="mono font-semibold text-[#14110b]">{orderReference(row, row.production_no)}</td>
                      <td>
                        <div className="mono font-semibold text-[#14110b]">{row.model_code || model?.code || row.model_id}</div>
                        <div className="max-w-[220px] truncate text-xs text-[#8a8472]">{modelLabel}</div>
                      </td>
                      <td>{itemPicture(row.item_image_url, row.item_name || t("field.picture"))}</td>
                      <td>{row.item_name}</td>
                      <td className="mono">{Number(row.required_quantity || 0).toFixed(2)} {row.unit}</td>
                      <td className="mono">{Number(row.issued_quantity || 0).toFixed(2)} {row.unit}</td>
                      <td className="mono font-semibold text-[#14110b]">{Number(row.remaining_quantity || 0).toFixed(2)} {row.unit}</td>
                      <td className="mono">{Number(row.available_quantity || 0).toFixed(2)} {row.unit}</td>
                      <td className={`mono ${Number(row.shortage || 0) > 0 ? "text-red-700" : ""}`}>{Number(row.shortage || 0).toFixed(2)} {row.unit}</td>
                      <td>
                        <button type="button" className="btn h-8 px-2 text-xs" onClick={() => openIssueModal(row)}>
                          <PackageCheck className="h-3.5 w-3.5" />
                          {t("page.receiveStock.issueAccessories")}
                        </button>
                      </td>
                    </tr>
                  );
                })}
                {requestRows.length === 0 && (
                  <tr>
                    <td colSpan={10} className="text-sm text-slate-400">{t("page.inventory.noAccessoryRequests")}</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <PaginationControls
            page={requestPage}
            pageSize={requestPageSize}
            total={requestTotal}
            count={requestRows.length}
            onPageChange={setRequestPage}
            onPageSizeChange={(size) => { setRequestPageSize(size); setRequestPage(1); }}
          />
        </div>
      )}
      {group === "accessories" && (
        <div className="card mt-6 overflow-hidden">
          <div className="border-b border-[#ecebe3] p-4">
            <div>
              <div className="app-card-title">{t("page.inventory.accessoryIssuesTitle")}</div>
              <div className="mt-1 text-sm text-[#6f684f]">{t("page.inventory.accessoryIssuesSubtitle")}</div>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>{t("field.orderNo")}</th>
                  <th>{t("field.modelNumber")}</th>
                  <th>{t("field.picture")}</th>
                  <th>{t("common.name")}</th>
                  <th>{t("page.inventory.issuedQty")}</th>
                  <th>{t("field.unit")}</th>
                  <th>{t("page.inventory.issueMoves")}</th>
                  <th>{t("page.inventory.lastIssued")}</th>
                </tr>
              </thead>
              <tbody>
                {issueRows.map((row) => {
                  const model = modelById.get(Number(row.model_id));
                  const modelLabel = [row.model_code || model?.code, row.model_name || model?.name].filter(Boolean).join(" - ") || `#${row.model_id}`;
                  return (
                    <tr key={`${row.production_order_id}-${row.item_id || row.item_sku || row.item_name}-${row.unit}`}>
                      <td className="mono font-semibold text-[#14110b]">{orderReference(row, row.production_no)}</td>
                      <td>
                        <div className="mono font-semibold text-[#14110b]">{row.model_code || model?.code || row.model_id}</div>
                        <div className="max-w-[220px] truncate text-xs text-[#8a8472]">{modelLabel}</div>
                      </td>
                      <td>{itemPicture(row.item_image_url, row.item_name || t("field.picture"))}</td>
                      <td>{row.item_name}</td>
                      <td className="mono font-semibold text-[#14110b]">{Number(row.issued_quantity || 0).toFixed(2)}</td>
                      <td>{row.unit}</td>
                      <td>{row.movement_count}</td>
                      <td>{row.last_issued_at ? new Date(row.last_issued_at).toLocaleDateString() : "-"}</td>
                    </tr>
                  );
                })}
                {issueRows.length === 0 && (
                  <tr>
                    <td colSpan={8} className="text-sm text-slate-400">{t("page.inventory.noAccessoryIssues")}</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <PaginationControls
            page={issuePage}
            pageSize={issuePageSize}
            total={issueTotal}
            count={issueRows.length}
            onPageChange={setIssuePage}
            onPageSizeChange={(size) => { setIssuePageSize(size); setIssuePage(1); }}
          />
        </div>
      )}
    </div>
  );
}
