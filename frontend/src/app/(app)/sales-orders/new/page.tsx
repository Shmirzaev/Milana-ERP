"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { ArrowLeft, Plus, Trash2 } from "lucide-react";
import { fetcher, api } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import SearchableSelect from "@/components/SearchableSelect";
import { useT } from "@/lib/i18n";
import { numberOrZero, parseNumberInput, type NumberInputValue } from "@/lib/numberInput";
import {
  groupModelVariants,
  modelGroupLabel,
  modelOrderLabel,
  modelVariantGroupKey,
  modelVariantLabel,
  modelVariantOption,
} from "@/lib/modelVariants";

type Line = {
  row_id: string;
  model_id: number;
  finished_goods_stock_id: number;
  color: string;
  size: string;
  quantity: NumberInputValue;
  pack_count: NumberInputValue;
  full_pack_count: NumberInputValue;
  partial_pack_count: NumberInputValue;
  unit_price: NumberInputValue;
  printing_required: boolean;
};
type PrintingAttachment = { file_url: string; file_name?: string | null; content_type?: string | null };
type BrandedStockRow = {
  id: number;
  package_id?: number | null;
  model_id?: number | null;
  model_code?: string | null;
  model_name?: string | null;
  brand_id?: number | null;
  color: string;
  size: string;
  quantity?: number;
  available_qty: number;
};
type AvailableModelOption = {
  model: any;
  available: number;
  fullPacks: number;
  partialPacks: number;
  partialQuantities: number[];
  saleablePacks: number;
  saleableQty: number;
};
type AvailableLegacyOption = {
  stock: BrandedStockRow;
  available: number;
  fullPacks: number;
  partialPacks: number;
  partialQuantities: number[];
  saleablePacks: number;
  saleableQty: number;
};
type ModelDetailSize = { size?: string | null };
type ModelDetailResponse = { sizes?: ModelDetailSize[] };

const SIZE_OPTIONS = ["44", "46", "48", "50", "52", "54", "56", "58", "60", "62", "64"];
const DEFAULT_SIZE = SIZE_OPTIONS[0];
const DEFAULT_PACK_PIECES = 60;
const BRANDED_PACK_COLOR = "mixed";

function normalizePackPieces(value: unknown): number {
  const parsed = Math.floor(Number(value));
  if (!Number.isFinite(parsed) || parsed <= 0) return 1;
  return parsed;
}

/**
 * Builds a new UI line with a stable row id so each input stays tied to its own line state.
 */
function createLine(overrides: Partial<Omit<Line, "row_id">> = {}): Line {
  const rowId = typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `row-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  return {
    row_id: rowId,
    model_id: 0,
    finished_goods_stock_id: 0,
    color: "white",
    size: DEFAULT_SIZE,
    quantity: "",
    pack_count: "",
    full_pack_count: "",
    partial_pack_count: "",
    unit_price: "",
    printing_required: false,
    ...overrides,
  };
}

function normalizeStockToken(value: unknown): string {
  return String(value ?? "").trim().toLowerCase();
}

function stockVariantKey(modelId: number, color: string, size: string): string {
  return `${Number(modelId) || 0}|${normalizeStockToken(color)}|${normalizeStockToken(size)}`;
}

function formatNumericSize(value: number): string {
  return Number.isInteger(value) ? String(value) : String(value);
}

function buildModelSizeRange(values: Array<string | null | undefined>): string | null {
  const cleaned = Array.from(
    new Set(values.map((value) => String(value || "").trim()).filter(Boolean)),
  );
  if (!cleaned.length) return null;
  if (cleaned.length === 1) return cleaned[0];

  const numericValues = cleaned.map((value) => Number(value.replace(",", ".")));
  const allNumeric = numericValues.every((value) => Number.isFinite(value));
  if (allNumeric) {
    const min = Math.min(...numericValues);
    const max = Math.max(...numericValues);
    return `${formatNumericSize(min)}-${formatNumericSize(max)}`;
  }

  const sorted = cleaned
    .slice()
    .sort((a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" }));
  return `${sorted[0]}-${sorted[sorted.length - 1]}`;
}

export default function NewSalesOrderPage() {
  const { t } = useT();
  const { data: customers } = useSWR<any[]>("/api/customers", fetcher);
  const { data: models } = useSWR<any[]>("/api/models", fetcher);
  const { data: brands } = useSWR<any[]>("/api/brands", fetcher);
  const {
    data: brandedStockRows,
    error: brandedStockError,
    isLoading: brandedStockLoading,
  } = useSWR<BrandedStockRow[]>("/api/finished-goods/branded-stock", fetcher);
  const [customerId, setCustomerId] = useState<number | "">("");
  const [brandId, setBrandId] = useState<number | "">("");
  const [orderType, setOrderType] = useState("client_order");
  const [deadline, setDeadline] = useState("");
  const [printingInstructions, setPrintingInstructions] = useState("");
  const [printingAttachments, setPrintingAttachments] = useState<PrintingAttachment[]>([]);
  const [uploadingPrintFile, setUploadingPrintFile] = useState(false);
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<Line[]>(() => [createLine()]);
  const [sizeFrom, setSizeFrom] = useState("46");
  const [sizeTo, setSizeTo] = useState("56");
  const [distributeTotalQty, setDistributeTotalQty] = useState<NumberInputValue>(6000);
  const [packPieces, setPackPieces] = useState<NumberInputValue>(DEFAULT_PACK_PIECES);
  const [includePartialPacks, setIncludePartialPacks] = useState(false);
  const [modelSizeRangeById, setModelSizeRangeById] = useState<Record<number, string>>({});
  const [err, setErr] = useState("");
  const [saving, setSaving] = useState(false);

  const isBrandedOrder = orderType === "branded_stock_sale";
  const effectivePackPieces = normalizePackPieces(packPieces);
  const brandedPackSize = `pack${effectivePackPieces}`;
  const modelMap = useMemo(() => new Map((models ?? []).map((m) => [Number(m.id), m])), [models]);
  const modelGroups = useMemo(() => groupModelVariants(models ?? []), [models]);
  const modelGroupByKey = useMemo(() => new Map(modelGroups.map((group) => [group.key, group])), [modelGroups]);
  const modelGroupKeyByModelId = useMemo(() => {
    const map = new Map<number, string>();
    for (const group of modelGroups) {
      for (const variant of group.variants) {
        map.set(Number(variant.id), group.key);
      }
    }
    return map;
  }, [modelGroups]);
  const filteredBrandedStockRows = useMemo(() => {
    const selectedBrandId = Number(brandId || 0);
    return (brandedStockRows ?? []).filter((row) => {
      if (Number(row.available_qty || 0) <= 0) return false;
      if (
        selectedBrandId > 0
        && row.model_id
        && Number(row.brand_id || 0) !== selectedBrandId
      ) return false;
      return true;
    });
  }, [brandId, brandedStockRows]);

  const brandedAvailableByVariant = useMemo(() => {
    const map = new Map<string, number>();
    for (const row of filteredBrandedStockRows) {
      if (!row.model_id) continue;
      const key = stockVariantKey(Number(row.model_id), row.color, row.size);
      map.set(key, (map.get(key) || 0) + Number(row.available_qty || 0));
    }
    return map;
  }, [filteredBrandedStockRows]);

  const availableModelOptions = useMemo<AvailableModelOption[]>(() => {
    const map = new Map<number, { model: any; available: number }>();
    for (const row of filteredBrandedStockRows) {
      const modelId = Number(row.model_id || 0);
      if (!modelId) continue;
      const model = modelMap.get(modelId);
      if (!model) continue;
      const availableQty = Number(row.available_qty || 0);
      const found = map.get(modelId);
      if (found) {
        found.available += availableQty;
      } else {
        map.set(modelId, { model, available: availableQty });
      }
    }
    return Array.from(map.values())
      .map((item) => {
        const fullPacks = Math.floor(item.available / effectivePackPieces);
        const remainder = item.available % effectivePackPieces;
        const partialQuantities = remainder > 0 ? [remainder] : [];
        const partialPacks = partialQuantities.length;
        const saleablePacks = fullPacks + (includePartialPacks ? partialPacks : 0);
        const saleableQty = (fullPacks * effectivePackPieces) + (includePartialPacks ? partialQuantities.reduce((sum, qty) => sum + qty, 0) : 0);
        return { ...item, fullPacks, partialPacks, partialQuantities, saleablePacks, saleableQty };
      })
      .filter((item) => item.saleablePacks > 0)
      .sort((a, b) => {
        const ac = String(a.model?.code || "").toLowerCase();
        const bc = String(b.model?.code || "").toLowerCase();
        return ac.localeCompare(bc);
      });
  }, [effectivePackPieces, filteredBrandedStockRows, includePartialPacks, modelMap]);

  const availableLegacyOptions = useMemo<AvailableLegacyOption[]>(() => (
    filteredBrandedStockRows
      .filter((row) => !row.model_id)
      .map((stock) => {
        const available = Number(stock.available_qty || 0);
        const fullPacks = Math.floor(available / effectivePackPieces);
        const remainder = available % effectivePackPieces;
        const partialQuantities = remainder > 0 ? [remainder] : [];
        const partialPacks = partialQuantities.length;
        const saleablePacks = fullPacks + (includePartialPacks ? partialPacks : 0);
        const saleableQty = (fullPacks * effectivePackPieces)
          + (includePartialPacks ? remainder : 0);
        return {
          stock,
          available,
          fullPacks,
          partialPacks,
          partialQuantities,
          saleablePacks,
          saleableQty,
        };
      })
      .filter((item) => item.saleablePacks > 0)
      .sort((a, b) => (
        String(a.stock.model_code || "").localeCompare(
          String(b.stock.model_code || ""),
          undefined,
          { numeric: true, sensitivity: "base" },
        )
      ))
  ), [effectivePackPieces, filteredBrandedStockRows, includePartialPacks]);

  const availableModelOptionById = useMemo(() => {
    return new Map(availableModelOptions.map((item) => [Number(item.model.id), item]));
  }, [availableModelOptions]);

  const availableModelQtyById = useMemo(() => {
    return new Map(availableModelOptions.map((item) => [Number(item.model.id), Number(item.saleableQty || 0)]));
  }, [availableModelOptions]);

  const availableLegacyOptionById = useMemo(() => (
    new Map(availableLegacyOptions.map((item) => [Number(item.stock.id), item]))
  ), [availableLegacyOptions]);

  const saleableSelectionOptions = useMemo(() => [
    ...availableModelOptions.map((item) => ({
      value: `model:${item.model.id}`,
      label: `${modelOrderLabel(item.model)} — ${item.saleablePacks.toLocaleString()} ${t("newso.packsShort")}`,
      searchText: `${item.model.code || ""} ${item.model.name || ""}`,
    })),
    ...availableLegacyOptions.map((item) => ({
      value: `stock:${item.stock.id}`,
      label: `${t("newso.legacyStockGroup")}: ${item.stock.model_code || `#${item.stock.id}`} — ${item.stock.model_name || ""} · ${item.stock.size || ""} — ${item.saleablePacks.toLocaleString()} ${t("newso.packsShort")}`,
      searchText: `${item.stock.model_code || ""} ${item.stock.model_name || ""} ${item.stock.color || ""} ${item.stock.size || ""}`,
    })),
  ], [availableLegacyOptions, availableModelOptions, t]);

  const availableSelectionKeys = useMemo(
    () => new Set(saleableSelectionOptions.map((option) => option.value)),
    [saleableSelectionOptions],
  );
  const availableProductCount = availableModelOptions.length + availableLegacyOptions.length;
  const totalBrandedPieces = [...availableModelOptions, ...availableLegacyOptions]
    .reduce((sum, item) => sum + Number(item.saleableQty || 0), 0);
  const totalFullPacks = [...availableModelOptions, ...availableLegacyOptions]
    .reduce((sum, item) => sum + Number(item.fullPacks || 0), 0);
  const totalPartialPacks = [...availableModelOptions, ...availableLegacyOptions]
    .reduce((sum, item) => sum + Number(item.partialPacks || 0), 0);
  const totalBrandedPacks = [...availableModelOptions, ...availableLegacyOptions]
    .reduce((sum, item) => sum + Number(item.saleablePacks || 0), 0);

  function selectionKeyForLine(line: Line): string {
    if (line.finished_goods_stock_id) return `stock:${line.finished_goods_stock_id}`;
    if (line.model_id) return `model:${line.model_id}`;
    return "";
  }

  function optionForLine(line: Line): AvailableModelOption | AvailableLegacyOption | undefined {
    if (line.finished_goods_stock_id) {
      return availableLegacyOptionById.get(Number(line.finished_goods_stock_id));
    }
    return availableModelOptionById.get(Number(line.model_id));
  }

  const brandedPackSelection = useCallback((line: Line): {
    fullPackCount: number;
    partialPackCount: number;
    packCount: number;
    quantity: number;
  } => {
    const option = optionForLine(line);
    const fallbackPackCount = Math.max(0, numberOrZero(line.pack_count));
    let fullPackCount = Math.max(0, numberOrZero(line.full_pack_count));
    let partialPackCount = includePartialPacks ? Math.max(0, numberOrZero(line.partial_pack_count)) : 0;

    if (fallbackPackCount > 0 && fullPackCount === 0 && partialPackCount === 0) {
      const availableFullPacks = option ? option.fullPacks : fallbackPackCount;
      fullPackCount = Math.min(fallbackPackCount, availableFullPacks);
      partialPackCount = includePartialPacks ? Math.max(0, fallbackPackCount - fullPackCount) : 0;
    }

    if (option) {
      fullPackCount = Math.min(fullPackCount, option.fullPacks);
      partialPackCount = includePartialPacks ? Math.min(partialPackCount, option.partialPacks) : 0;
    } else if (!includePartialPacks) {
      partialPackCount = 0;
    }

    const partialQty = includePartialPacks && option
      ? option.partialQuantities.slice(0, partialPackCount).reduce((sum, qty) => sum + qty, 0)
      : 0;
    const packCount = fullPackCount + partialPackCount;
    return {
      fullPackCount,
      partialPackCount,
      packCount,
      quantity: (fullPackCount * effectivePackPieces) + partialQty,
    };
  }, [availableLegacyOptionById, availableModelOptionById, effectivePackPieces, includePartialPacks]);

  useEffect(() => {
    if (isBrandedOrder) {
      setLines((prev) => prev.map((line) => {
        const currentKey = selectionKeyForLine(line);
        const keepSelection = availableSelectionKeys.has(currentKey);
        const nextModelId = keepSelection ? line.model_id : 0;
        const nextStockId = keepSelection ? line.finished_goods_stock_id : 0;
        const selection = brandedPackSelection({
          ...line,
          model_id: nextModelId,
          finished_goods_stock_id: nextStockId,
        });
        return {
          ...line,
          model_id: nextModelId,
          finished_goods_stock_id: nextStockId,
          color: BRANDED_PACK_COLOR,
          size: brandedPackSize,
          pack_count: selection.packCount,
          full_pack_count: selection.fullPackCount,
          partial_pack_count: selection.partialPackCount,
          quantity: selection.quantity,
        };
      }));
    } else {
      setLines((prev) => prev.map((line) => ({
        ...line,
        finished_goods_stock_id: 0,
        color: line.color || "white",
        size: line.size || DEFAULT_SIZE,
      })));
    }
  }, [isBrandedOrder, availableSelectionKeys, brandedPackSelection, brandedPackSize]);

  useEffect(() => {
    if (!isBrandedOrder) return;
    const missingModelIds = Array.from(
      new Set(
        lines
          .map((line) => Number(line.model_id || 0))
          .filter((modelId) => modelId > 0 && !modelSizeRangeById[modelId]),
      ),
    );
    if (!missingModelIds.length) return;

    let cancelled = false;
    (async () => {
      const resolvedRanges: Record<number, string> = {};
      await Promise.all(
        missingModelIds.map(async (modelId) => {
          try {
            const detail = await api.get<ModelDetailResponse>(`/api/models/${modelId}`);
            const sizeRange = buildModelSizeRange((detail.sizes || []).map((row) => row.size));
            if (sizeRange) {
              resolvedRanges[modelId] = sizeRange;
            }
          } catch {
            // Fallback stays at packXX when model sizes cannot be loaded.
          }
        }),
      );
      if (cancelled || !Object.keys(resolvedRanges).length) return;
      setModelSizeRangeById((prev) => ({ ...prev, ...resolvedRanges }));
    })();

    return () => {
      cancelled = true;
    };
  }, [isBrandedOrder, lines, modelSizeRangeById]);

  function brandedLineSizeLabel(line: Line): string {
    if (line.finished_goods_stock_id) {
      return availableLegacyOptionById.get(Number(line.finished_goods_stock_id))?.stock.size
        || brandedPackSize;
    }
    if (!line.model_id) return brandedPackSize;
    return modelSizeRangeById[Number(line.model_id)] || brandedPackSize;
  }

  function availableQtyForLine(line: Line): number {
    if (line.finished_goods_stock_id) {
      return Number(
        availableLegacyOptionById.get(Number(line.finished_goods_stock_id))?.saleableQty
        || 0,
      );
    }
    if (!line.model_id) return 0;
    if (isBrandedOrder) {
      return Number(availableModelQtyById.get(Number(line.model_id)) || 0);
    }
    const key = stockVariantKey(line.model_id, line.color, line.size);
    return Number(brandedAvailableByVariant.get(key) || 0);
  }

  function brandedLinePieces(line: Line): number {
    return brandedPackSelection(line).quantity;
  }

  function linePieces(line: Line): number {
    if (isBrandedOrder) {
      return brandedLinePieces(line);
    }
    return Math.max(0, numberOrZero(line.quantity));
  }

  function linePacks(line: Line): number {
    if (isBrandedOrder) {
      return brandedPackSelection(line).packCount;
    }
    return Math.max(0, numberOrZero(line.pack_count));
  }

  function updateLine(index: number, field: keyof Omit<Line, "row_id">, value: Line[keyof Omit<Line, "row_id">]) {
    setLines((prev) => prev.map((line, i) => {
      if (index !== i) return line;
      const next = { ...line, [field]: value };
      if (isBrandedOrder) {
        const selection = brandedPackSelection(next);
        next.full_pack_count = selection.fullPackCount;
        next.partial_pack_count = selection.partialPackCount;
        next.pack_count = selection.packCount;
        next.quantity = selection.quantity;
        next.color = BRANDED_PACK_COLOR;
        next.size = brandedPackSize;
      }
      return next;
    }));
  }
  function addLine() {
    setLines([
      ...lines,
      isBrandedOrder
        ? createLine({ color: BRANDED_PACK_COLOR, size: brandedPackSize })
        : createLine(),
    ]);
  }
  function removeLine(i: number) {
    setLines(lines.filter((_, j) => j !== i));
  }

  function modelLabelById(modelId: number) {
    const m = modelMap.get(Number(modelId));
    return m ? modelOrderLabel(m) : "";
  }

  function productLabelForLine(line: Line): string {
    if (line.finished_goods_stock_id) {
      const stock = availableLegacyOptionById.get(
        Number(line.finished_goods_stock_id),
      )?.stock;
      if (!stock) return `#${line.finished_goods_stock_id}`;
      return [stock.model_code, stock.model_name].filter(Boolean).join(" — ");
    }
    return modelLabelById(line.model_id) || `#${line.model_id}`;
  }

  function selectSaleableProduct(index: number, value: string) {
    const [kind, rawId] = String(value || "").split(":", 2);
    const id = Number(rawId || 0);
    setLines((prev) => prev.map((line, lineIndex) => {
      if (lineIndex !== index) return line;
      const next: Line = {
        ...line,
        model_id: kind === "model" ? id : 0,
        finished_goods_stock_id: kind === "stock" ? id : 0,
      };
      const selection = brandedPackSelection(next);
      return {
        ...next,
        color: BRANDED_PACK_COLOR,
        size: brandedPackSize,
        pack_count: selection.packCount,
        full_pack_count: selection.fullPackCount,
        partial_pack_count: selection.partialPackCount,
        quantity: selection.quantity,
      };
    }));
  }

  function selectModelGroup(index: number, groupKey: string) {
    const group = modelGroupByKey.get(groupKey);
    setLines((prev) => prev.map((line, lineIndex) => (
      lineIndex === index
        ? {
            ...line,
            model_id: Number(group?.variants[0]?.id || 0),
            finished_goods_stock_id: 0,
          }
        : line
    )));
  }

  function selectedModelGroupKey(modelId: number): string {
    return modelGroupKeyByModelId.get(Number(modelId)) || "";
  }

  function distributeBySizeRange() {
    setErr("");
    const distributeQty = numberOrZero(distributeTotalQty);
    const startIdx = SIZE_OPTIONS.indexOf(sizeFrom);
    const endIdx = SIZE_OPTIONS.indexOf(sizeTo);
    if (startIdx < 0 || endIdx < 0 || startIdx > endIdx) {
      setErr(t("newso.invalidSizeRange"));
      return;
    }
    if (distributeQty <= 0) {
      setErr(t("newso.invalidTotalQty"));
      return;
    }

    const selectedSizes = SIZE_OPTIONS.slice(startIdx, endIdx + 1);
    const count = selectedSizes.length;
    const qtyPerSize = Math.floor(distributeQty / count);
    let remainder = distributeQty % count;

    const base = lines[0] ?? createLine({ size: sizeFrom });
    const nextLines: Line[] = selectedSizes.map((size) => {
      const addOne = remainder > 0 ? 1 : 0;
      if (remainder > 0) remainder -= 1;
      return createLine({
        model_id: base.model_id,
        finished_goods_stock_id: base.finished_goods_stock_id,
        color: base.color,
        size,
        quantity: qtyPerSize + addOne,
        pack_count: base.pack_count,
        full_pack_count: base.full_pack_count,
        partial_pack_count: base.partial_pack_count,
        unit_price: base.unit_price,
        printing_required: base.printing_required,
      });
    });

    setLines(nextLines);
  }

  const subtotal = lines.reduce((s, l) => s + linePieces(l) * numberOrZero(l.unit_price), 0);
  const qty = lines.reduce((s, l) => s + linePieces(l), 0);
  const totalPacksSelected = lines.reduce((s, l) => s + linePacks(l), 0);
  const hasPrintingSelected = lines.some((line) => Boolean(line.printing_required));

  function isImageAttachment(a: PrintingAttachment): boolean {
    const byMime = (a.content_type || "").toLowerCase().startsWith("image/");
    const byName = /\.(png|jpe?g|webp|gif)$/i.test(a.file_name || a.file_url || "");
    return byMime || byName;
  }

  async function onPickPrintingFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    setErr("");
    setUploadingPrintFile(true);
    try {
      const uploaded: PrintingAttachment[] = [];
      for (const file of Array.from(files)) {
        const form = new FormData();
        form.append("file", file);
        const saved = await api.postForm<PrintingAttachment>("/api/sales-orders/printing-attachments/upload", form);
        uploaded.push(saved);
      }
      setPrintingAttachments((prev) => [...prev, ...uploaded]);
    } catch (e: any) {
      setErr(e.message || "Failed to upload file");
    } finally {
      setUploadingPrintFile(false);
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    setSaving(true);
    try {
      if (isBrandedOrder) {
        if (!availableProductCount) {
          setErr(t("newso.noStockForBrand"));
          setSaving(false);
          return;
        }
        for (const line of lines) {
          if (!line.model_id && !line.finished_goods_stock_id) {
            setErr(t("newso.selectModel"));
            setSaving(false);
            return;
          }
          if (linePacks(line) <= 0) {
            setErr(t("newso.invalidPackQty"));
            setSaving(false);
            return;
          }
        }

        const requestedByProduct = new Map<string, { requested: number; available: number; model: string }>();
        for (const line of lines) {
          const key = selectionKeyForLine(line);
          const available = availableQtyForLine(line);
          const modelName = productLabelForLine(line);
          const current = requestedByProduct.get(key);
          if (current) {
            current.requested += linePieces(line);
          } else {
            requestedByProduct.set(key, {
              requested: linePieces(line),
              available,
              model: modelName,
            });
          }
        }
        for (const row of requestedByProduct.values()) {
          if (row.requested > row.available) {
            setErr(
              t("newso.stockInsufficient", {
                model: row.model,
                requested: row.requested.toLocaleString(),
                available: row.available.toLocaleString(),
              }),
            );
            setSaving(false);
            return;
          }
        }
      }

      const payload: any = {
        customer_id: customerId || null,
        order_type: orderType,
        deadline: deadline || null,
        printing_instructions: hasPrintingSelected ? (printingInstructions.trim() || null) : null,
        printing_attachments: hasPrintingSelected ? printingAttachments : [],
        notes,
        items: lines.map((line) => ({
          model_id: line.model_id || null,
          finished_goods_stock_id: line.finished_goods_stock_id || null,
          color: isBrandedOrder ? BRANDED_PACK_COLOR : line.color,
          size: isBrandedOrder ? brandedPackSize : line.size,
          quantity: linePieces(line),
          unit_price: numberOrZero(line.unit_price),
          printing_required: line.printing_required,
          brand_id: brandId || null,
        })),
      };
      const so = await api.post("/api/sales-orders", payload);
      window.location.href = `/sales-orders/${so.id}`;
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <PageHeader
        eyebrow={t("newso.eyebrow")}
        title={t("newso.title")}
        subtitle={isBrandedOrder ? t("newso.subtitleBranded") : t("newso.subtitle")}
        actions={<a href="/sales-orders" className="btn"><ArrowLeft />{t("newso.backToOrders")}</a>}
      />

      <form onSubmit={submit} className="grid grid-cols-1 items-start gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="space-y-4">
          <section className="card p-5">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <h2 className="app-card-title">{t("newso.orderDetails")}</h2>
                <p className="mt-1 text-sm text-[#8a8472]">{t("newso.orderDetailsSub")}</p>
              </div>
              <span className="badge bg-[#fbe9dd] text-[#c2410c]">{t("newso.draft")}</span>
            </div>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
              <div>
                <label className="label">{t("sales.orderType")}</label>
                <select className="input" value={orderType} onChange={(e) => setOrderType(e.target.value)}>
                  <option value="client_order">{t("orderType.client")}</option>
                  <option value="branded_stock_sale">{t("orderType.branded")}</option>
                </select>
              </div>
              <div>
                <label className="label">{t("field.customer")}</label>
                <select className="input" value={customerId} onChange={(e) => setCustomerId(Number(e.target.value) || "")}>
                  <option value="">{t("newso.customerSelect")}</option>
                  {customers?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </div>
              <div>
                <label className="label">{t("field.deadline")}</label>
                <input className="input" type="date" value={deadline} onChange={(e) => setDeadline(e.target.value)} />
              </div>
              <div>
                <label className="label">{t("field.brand")}</label>
                <select className="input" value={brandId} onChange={(e) => setBrandId(Number(e.target.value) || "")}>
                  <option value="">{t("newso.brandSelect")}</option>
                  {brands?.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
                </select>
              </div>
            </div>
            {isBrandedOrder && (
              <div className="mt-4 rounded-xl border border-[#d7e5dd] bg-[linear-gradient(145deg,#f8fcfa,#eef5f1)] p-4">
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div className="rounded-lg bg-white/75 p-3">
                    <div className="text-[11px] uppercase tracking-[0.08em] text-[#6a7f72]">{t("newso.productsInStorage")}</div>
                    <div className="mt-1 text-2xl font-semibold text-[#1f4032]">{availableProductCount.toLocaleString()}</div>
                  </div>
                  <div className="rounded-lg bg-white/75 p-3">
                    <div className="text-[11px] uppercase tracking-[0.08em] text-[#6a7f72]">{t("newso.packsInStorage")}</div>
                    <div className="mt-1 text-2xl font-semibold text-[#1f4032]">{totalBrandedPacks.toLocaleString()}</div>
                    <div className="mt-1 text-xs text-[#6a7f72]">{`${totalBrandedPieces.toLocaleString()} ${t("newso.pcsShort")}`}</div>
                    <div className="mt-1 text-xs text-[#6a7f72]">
                      {includePartialPacks && totalPartialPacks > 0
                        ? t("newso.fullAndPartialPacks", { full: totalFullPacks.toLocaleString(), partial: totalPartialPacks.toLocaleString() })
                        : t("newso.fullPacksOnly", { full: totalFullPacks.toLocaleString() })}
                    </div>
                  </div>
                </div>
                <p className="mt-2 text-xs text-[#53695c]">
                  {brandedStockError
                    ? t("newso.stockLoadFailed")
                    : brandedStockLoading
                      ? t("common.loading")
                      : availableProductCount > 0
                        ? t("newso.readyStockHint")
                        : t("newso.noStockForBrand")}
                </p>
              </div>
            )}
          </section>

          <section className="card">
            <div className="flex items-center justify-between border-b border-[#ecebe3] px-5 py-4">
              <div>
                <h2 className="app-card-title">{t("newso.lines")}</h2>
                <p className="mt-1 text-sm text-[#8a8472]">
                  {isBrandedOrder
                    ? t("newso.packsAcross", { packs: totalPacksSelected.toLocaleString(), qty: qty.toLocaleString(), lines: lines.length })
                    : t("newso.linesSummary", { lines: lines.length, qty: qty.toLocaleString() })}
                </p>
              </div>
              <div className="flex flex-wrap items-end gap-3">
                {isBrandedOrder && (
                  <div className="flex flex-wrap items-end gap-3">
                    <div className="w-40">
                      <label className="label">{t("newso.piecesPerPack")}</label>
                      <input
                        className="input h-8"
                        type="number"
                        min={1}
                        step={1}
                        value={packPieces}
                        onChange={(e) => setPackPieces(parseNumberInput(e.target.value))}
                      />
                    </div>
                    <label className="flex max-w-[230px] items-start gap-2 rounded-md border border-[#ddd8c8] bg-[#fdfcf8] px-3 py-2 text-xs text-[#56503f]">
                      <input
                        className="mt-0.5"
                        type="checkbox"
                        checked={includePartialPacks}
                        onChange={(e) => setIncludePartialPacks(e.target.checked)}
                      />
                      <span>
                        <span className="block font-medium text-[#14110b]">{t("newso.includePartialPacks")}</span>
                        <span>{t("newso.includePartialPacksHint")}</span>
                      </span>
                    </label>
                  </div>
                )}
                <button type="button" className="btn" onClick={addLine}><Plus />{t("newso.addLine")}</button>
              </div>
            </div>
            {!isBrandedOrder && (
              <div className="border-b border-[#ecebe3] px-5 py-4">
                <div className="mb-2 text-sm font-semibold text-[#14110b]">{t("newso.sizeHelper")}</div>
                <div className="grid grid-cols-1 gap-3 md:grid-cols-[140px_140px_180px_auto] md:items-end">
                  <div>
                    <label className="label">{t("newso.sizeFrom")}</label>
                    <select className="input" value={sizeFrom} onChange={(e) => setSizeFrom(e.target.value)}>
                      {SIZE_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
                    </select>
                  </div>
                  <div>
                    <label className="label">{t("newso.sizeTo")}</label>
                    <select className="input" value={sizeTo} onChange={(e) => setSizeTo(e.target.value)}>
                      {SIZE_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
                    </select>
                  </div>
                  <div>
                    <label className="label">{t("newso.sizeTotalQty")}</label>
                    <input className="input" type="number" min={1} value={distributeTotalQty} onChange={(e) => setDistributeTotalQty(parseNumberInput(e.target.value))} />
                  </div>
                  <div className="flex items-end md:pb-[1px]">
                    <button type="button" className="btn btn-primary" onClick={distributeBySizeRange}>
                      {t("newso.distributeEvenly")}
                    </button>
                  </div>
                </div>
              </div>
            )}
            <div className="overflow-x-auto">
              <table className="table table--sales-lines">
                <thead>
                  <tr>
                    <th>{t("field.model")}</th><th>{t("field.color")}</th><th>{t("field.size")}</th>
                    <th>
                      {isBrandedOrder ? (
                        <div className="min-w-[252px]">
                          <div>{t("newso.packs")}</div>
                          <div className="mt-1 grid grid-cols-[78px_78px_auto] gap-2 text-[10px] normal-case tracking-normal text-[#6f6858]">
                            <span>{t("newso.fullPacksLabel")}</span>
                            <span>{t("newso.notFullPacksLabel")}</span>
                            <span>{t("field.qty")}</span>
                          </div>
                        </div>
                      ) : t("field.qty")}
                    </th>
                    <th>{t("field.unitPrice")}</th><th>{t("field.printingRequired")}</th><th></th>
                  </tr>
                </thead>
                <tbody>
                  {lines.map((l, i) => {
                    const productOption = optionForLine(l);
                    const productTotal = Number(productOption?.saleableQty || 0);
                    const lineAvailable = availableQtyForLine(l);
                    const lineAvailablePacks = Number(productOption?.saleablePacks || Math.floor(lineAvailable / effectivePackPieces));
                    const selectedFullPacks = Math.max(0, numberOrZero(l.full_pack_count));
                    const selectedPartialPacks = includePartialPacks ? Math.max(0, numberOrZero(l.partial_pack_count)) : 0;
                    const lineFullPacks = Number(productOption?.fullPacks || 0);
                    const linePartialPacks = includePartialPacks ? Number(productOption?.partialPacks || 0) : 0;
                    const selectedGroupKey = selectedModelGroupKey(l.model_id);
                    const selectedGroup = modelGroupByKey.get(selectedGroupKey);
                    const selectedProductKey = selectionKeyForLine(l);
                    return (
                      <tr key={l.row_id}>
                        <td className="min-w-72 align-top">
                          {isBrandedOrder ? (
                            <>
                              <SearchableSelect
                                inputId={`saleable-product-${l.row_id}`}
                                value={selectedProductKey || null}
                                options={saleableSelectionOptions}
                                onChange={(value) => selectSaleableProduct(i, String(value))}
                                placeholder={t("newso.selectModel")}
                                noResultsText={t("newso.noMatchingStock")}
                                disabled={!saleableSelectionOptions.length}
                              />
                              {selectedProductKey && (
                                <div className="inline-flex rounded-md bg-[#edf7f1] px-2.5 py-1 text-xs font-medium text-[#246845]">
                                  {t("newso.modelInStockPack", {
                                    packs: lineAvailablePacks.toLocaleString(),
                                    qty: productTotal.toLocaleString(),
                                  })}
                                </div>
                              )}
                            </>
                          ) : (
                            <div className="grid min-w-72 grid-cols-1 gap-2">
                              <select
                                className="input h-9"
                                value={selectedGroupKey}
                                onChange={(e) => selectModelGroup(i, e.target.value)}
                              >
                                <option value="">{t("newso.selectModel")}</option>
                                {modelGroups.map((group) => (
                                  <option key={group.key} value={group.key}>
                                    {modelGroupLabel(group)}
                                  </option>
                                ))}
                              </select>
                              <select
                                className="input h-9"
                                value={l.model_id || ""}
                                onChange={(e) => updateLine(i, "model_id", Number(e.target.value) || 0)}
                                disabled={!selectedGroup}
                              >
                                <option value="">{t("page.modelDetail.tab.variants")}</option>
                                {(selectedGroup?.variants || []).map((variant) => (
                                  <option key={variant.id} value={variant.id}>
                                    {modelVariantLabel(variant)}
                                  </option>
                                ))}
                              </select>
                            </div>
                          )}
                        </td>
                        <td className="align-top">
                          {isBrandedOrder ? (
                            <input className="input h-9 min-w-28 bg-[#f8f7f3]" value={BRANDED_PACK_COLOR} readOnly />
                          ) : (
                            <input className="input min-w-28" value={l.color} onChange={(e) => updateLine(i, "color", e.target.value)} />
                          )}
                        </td>
                        <td className="align-top">
                          {isBrandedOrder ? (
                            <input className="input h-9 w-24 bg-[#f8f7f3]" value={brandedLineSizeLabel(l)} readOnly />
                          ) : (
                            <select className="input w-24" value={l.size} onChange={(e) => updateLine(i, "size", e.target.value)}>
                              {SIZE_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
                            </select>
                          )}
                        </td>
                        <td className="align-top">
                          {isBrandedOrder ? (
                            <div className="min-w-[252px] space-y-1.5">
                              <div className="grid grid-cols-[78px_78px_auto] items-center gap-2">
                                <div>
                                  <input
                                    className={`input h-9 w-full ${selectedFullPacks > lineFullPacks ? "border-red-400 bg-red-50" : ""}`}
                                    type="number"
                                    min={0}
                                    max={lineFullPacks || undefined}
                                    value={l.full_pack_count}
                                    onChange={(e) => updateLine(i, "full_pack_count", parseNumberInput(e.target.value))}
                                  />
                                </div>
                                <div>
                                  <input
                                    className={`input h-9 w-full ${selectedPartialPacks > linePartialPacks ? "border-red-400 bg-red-50" : ""}`}
                                    type="number"
                                    min={0}
                                    max={linePartialPacks || undefined}
                                    value={l.partial_pack_count}
                                    disabled={!includePartialPacks || linePartialPacks <= 0}
                                    onChange={(e) => updateLine(i, "partial_pack_count", parseNumberInput(e.target.value))}
                                  />
                                </div>
                                <span className="whitespace-nowrap text-xs text-[#8a8472]">
                                  {`${linePieces(l).toLocaleString()} ${t("newso.pcsShort")}`}
                                </span>
                              </div>
                              {selectedProductKey && (
                                <div className="flex flex-wrap gap-1.5">
                                  <span className={`inline-flex rounded-md px-2 py-1 text-xs font-medium ${selectedFullPacks > lineFullPacks ? "bg-red-50 text-red-700" : "bg-emerald-50 text-emerald-700"}`}>
                                    {t("newso.fullPacksAvailable", { count: lineFullPacks.toLocaleString() })}
                                  </span>
                                  <span className={`inline-flex rounded-md px-2 py-1 text-xs font-medium ${selectedPartialPacks > linePartialPacks ? "bg-red-50 text-red-700" : "bg-[#f4f1e9] text-[#5d563f]"}`}>
                                    {t("newso.notFullPacksAvailable", { count: linePartialPacks.toLocaleString() })}
                                  </span>
                                </div>
                              )}
                            </div>
                          ) : (
                            <input
                              className="input w-28"
                              type="number"
                              min={1}
                              value={lines[i]?.quantity ?? ""}
                              onChange={(e) => updateLine(i, "quantity", parseNumberInput(e.target.value))}
                            />
                          )}
                        </td>
                        <td className="align-top"><input className="input h-9 w-32" type="number" step="0.01" value={l.unit_price} onChange={(e) => updateLine(i, "unit_price", parseNumberInput(e.target.value))} /></td>
                        <td className="align-top"><div className="flex h-9 items-center"><input type="checkbox" checked={l.printing_required} onChange={(e) => updateLine(i, "printing_required", e.target.checked)} /></div></td>
                        <td className="align-top">
                          <div className="flex h-9 items-center">
                            <button type="button" className="icon-btn text-red-600" onClick={() => removeLine(i)} title={t("newso.remove")}>
                              <Trash2 />
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          {hasPrintingSelected && (
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
                    value={printingInstructions}
                    onChange={(e) => setPrintingInstructions(e.target.value)}
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
                    disabled={uploadingPrintFile}
                    onChange={(e) => {
                      onPickPrintingFiles(e.target.files);
                      e.currentTarget.value = "";
                    }}
                  />
                  <p className="mt-1 text-xs text-[#8a8472]">{t("page.newSO.printingAttachHelp")}</p>
                </div>
                {uploadingPrintFile && <div className="text-sm text-[#8a8472]">{t("common.uploading")}</div>}
                {printingAttachments.length > 0 && (
                  <div className="space-y-2">
                    {printingAttachments.map((file, idx) => (
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
                          onClick={() => setPrintingAttachments((prev) => prev.filter((_, j) => j !== idx))}
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

          <section className="card p-5">
            <label className="label">{t("field.notes")}</label>
            <textarea className="input" rows={4} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder={t("newso.notesPlaceholder")} />
          </section>
        </div>

        <aside className="card self-start">
          <div className="border-b border-[#ecebe3] px-5 py-4">
            <h2 className="app-card-title">{t("newso.orderSummary")}</h2>
            <p className="mt-1 text-sm text-[#8a8472]">{isBrandedOrder ? t("newso.orderSummaryBrandedSub") : t("newso.orderSummarySub")}</p>
          </div>
          <div className="space-y-5 p-5">
            <div className="rounded-lg bg-[#f1efe8] p-4">
              <div className="label">{t("newso.totalQuantity")}</div>
              <div className="mt-1 text-3xl font-semibold">{qty.toLocaleString()}</div>
              <div className="mt-1 text-sm text-[#8a8472]">
                {isBrandedOrder
                  ? t("newso.packsAcross", { packs: totalPacksSelected.toLocaleString(), qty: qty.toLocaleString(), lines: lines.length })
                  : t("newso.piecesAcross", { qty: qty.toLocaleString(), lines: lines.length })}
              </div>
            </div>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between text-base font-semibold"><span>{t("field.totalAmount")}</span><span className="mono">${subtotal.toFixed(2)}</span></div>
            </div>
            {err && <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">{err}</div>}
            <button className="btn btn-primary w-full" disabled={saving}>{saving ? t("newso.creating") : t("newso.createOrder")}</button>
            <p className="text-xs text-[#8a8472]">{isBrandedOrder ? t("newso.afterCreateBranded") : t("newso.afterCreate")}</p>
          </div>
        </aside>
      </form>
    </div>
  );
}
