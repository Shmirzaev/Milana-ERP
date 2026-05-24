"use client";
import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { ArrowLeft, Plus, Trash2 } from "lucide-react";
import { fetcher, api } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";

type Line = { row_id: string; model_id: number; color: string; size: string; quantity: number; pack_count: number; unit_price: number; printing_required: boolean };
type PrintingAttachment = { file_url: string; file_name?: string | null; content_type?: string | null };
type BrandedStockRow = {
  id: number;
  model_id: number;
  brand_id?: number | null;
  color: string;
  size: string;
  available_qty: number;
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
    color: "white",
    size: DEFAULT_SIZE,
    quantity: 0,
    pack_count: 0,
    unit_price: 0,
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
  const { data: brandedStockRows } = useSWR<BrandedStockRow[]>("/api/finished-goods/branded-stock", fetcher);
  const [customerId, setCustomerId] = useState<number | "">("");
  const [brandId, setBrandId] = useState<number | "">("");
  const [orderType, setOrderType] = useState("client_order");
  const [deadline, setDeadline] = useState("");
  const [printingInstructions, setPrintingInstructions] = useState("");
  const [printingAttachments, setPrintingAttachments] = useState<PrintingAttachment[]>([]);
  const [uploadingPrintFile, setUploadingPrintFile] = useState(false);
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<Line[]>(() => [createLine()]);
  const [lineModelSearch, setLineModelSearch] = useState<string[]>([""]);
  const [sizeFrom, setSizeFrom] = useState("46");
  const [sizeTo, setSizeTo] = useState("56");
  const [distributeTotalQty, setDistributeTotalQty] = useState(6000);
  const [packPieces, setPackPieces] = useState(DEFAULT_PACK_PIECES);
  const [modelSizeRangeById, setModelSizeRangeById] = useState<Record<number, string>>({});
  const [err, setErr] = useState("");
  const [saving, setSaving] = useState(false);

  const isBrandedOrder = orderType === "branded_stock_sale";
  const brandedPackSize = `pack${packPieces}`;
  const modelMap = useMemo(() => new Map((models ?? []).map((m) => [Number(m.id), m])), [models]);

  const filteredBrandedStockRows = useMemo(() => {
    const selectedBrandId = Number(brandId || 0);
    return (brandedStockRows ?? []).filter((row) => {
      if (Number(row.available_qty || 0) <= 0) return false;
      if (selectedBrandId > 0 && Number(row.brand_id || 0) !== selectedBrandId) return false;
      return true;
    });
  }, [brandId, brandedStockRows]);

  const brandedAvailableByVariant = useMemo(() => {
    const map = new Map<string, number>();
    for (const row of filteredBrandedStockRows) {
      const key = stockVariantKey(Number(row.model_id), row.color, row.size);
      map.set(key, (map.get(key) || 0) + Number(row.available_qty || 0));
    }
    return map;
  }, [filteredBrandedStockRows]);

  const availableModelOptions = useMemo(() => {
    const map = new Map<number, { model: any; available: number }>();
    for (const row of filteredBrandedStockRows) {
      const modelId = Number(row.model_id || 0);
      if (!modelId) continue;
      const model = modelMap.get(modelId);
      if (!model) continue;
      const found = map.get(modelId);
      if (found) {
        found.available += Number(row.available_qty || 0);
      } else {
        map.set(modelId, { model, available: Number(row.available_qty || 0) });
      }
    }
    return Array.from(map.values()).filter((item) => Number(item.available || 0) >= packPieces).sort((a, b) => {
      const ac = String(a.model?.code || "").toLowerCase();
      const bc = String(b.model?.code || "").toLowerCase();
      return ac.localeCompare(bc);
    });
  }, [filteredBrandedStockRows, modelMap, packPieces]);

  const availableModelQtyById = useMemo(() => {
    return new Map(availableModelOptions.map((item) => [Number(item.model.id), Number(item.available || 0)]));
  }, [availableModelOptions]);

  const availableModelIds = useMemo(() => new Set(availableModelOptions.map((item) => Number(item.model.id))), [availableModelOptions]);
  const availableModelCount = availableModelOptions.length;
  const totalBrandedPieces = availableModelOptions.reduce((sum, item) => sum + Number(item.available || 0), 0);
  const totalBrandedPacks = Math.floor(totalBrandedPieces / packPieces);

  useEffect(() => {
    if (isBrandedOrder) {
      setLines((prev) => prev.map((line) => {
        const packCount = Math.max(1, Number(line.pack_count || Math.ceil(Number(line.quantity || 0) / packPieces) || 1));
        const nextModelId = availableModelIds.has(Number(line.model_id)) ? line.model_id : 0;
        return {
          ...line,
          model_id: nextModelId,
          color: BRANDED_PACK_COLOR,
          size: brandedPackSize,
          pack_count: packCount,
          quantity: packCount * packPieces,
        };
      }));
    } else {
      setLines((prev) => prev.map((line) => ({
        ...line,
        color: line.color || "white",
        size: line.size || DEFAULT_SIZE,
      })));
    }
    setLineModelSearch((prev) => prev.map(() => ""));
  }, [isBrandedOrder, availableModelIds, brandedPackSize, packPieces]);

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
    if (!line.model_id) return brandedPackSize;
    return modelSizeRangeById[Number(line.model_id)] || brandedPackSize;
  }

  function availableQtyForLine(line: Line): number {
    if (!line.model_id) return 0;
    if (isBrandedOrder) {
      return Number(availableModelQtyById.get(Number(line.model_id)) || 0);
    }
    const key = stockVariantKey(line.model_id, line.color, line.size);
    return Number(brandedAvailableByVariant.get(key) || 0);
  }

  function linePieces(line: Line): number {
    if (isBrandedOrder) {
      return Math.max(0, Number(line.pack_count || 0)) * packPieces;
    }
    return Math.max(0, Number(line.quantity || 0));
  }

  function linePacks(line: Line): number {
    return Math.max(0, Number(line.pack_count || 0));
  }

  function updateLine(index: number, field: keyof Omit<Line, "row_id">, value: Line[keyof Omit<Line, "row_id">]) {
    setLines((prev) => prev.map((line, i) => {
      if (index !== i) return line;
      const next = { ...line, [field]: value };
      if (isBrandedOrder) {
        const packCount = Math.max(0, Number(next.pack_count || 0));
        next.pack_count = packCount;
        next.quantity = packCount * packPieces;
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
    setLineModelSearch([...lineModelSearch, ""]);
  }
  function removeLine(i: number) {
    setLines(lines.filter((_, j) => j !== i));
    setLineModelSearch(lineModelSearch.filter((_, j) => j !== i));
  }

  function modelLabelById(modelId: number) {
    const m = modelMap.get(Number(modelId));
    return m ? `${m.code} - ${m.name}` : "";
  }

  function setModelSearch(i: number, rawValue: string) {
    const next = [...lineModelSearch];
    next[i] = rawValue;
    setLineModelSearch(next);

    const q = rawValue.trim().toLowerCase();
    if (!q) {
      updateLine(i, "model_id", 0);
      return;
    }

    const searchableModels = isBrandedOrder ? availableModelOptions.map((item) => item.model) : (models ?? []);
    const exact = searchableModels.find((m) => {
      const code = String(m.code ?? "").toLowerCase();
      const name = String(m.name ?? "").toLowerCase();
      const full = `${code} - ${name}`;
      return q === code || q === name || q === full;
    });
    if (exact) {
      updateLine(i, "model_id", Number(exact.id));
    }
  }

  function distributeBySizeRange() {
    setErr("");
    const startIdx = SIZE_OPTIONS.indexOf(sizeFrom);
    const endIdx = SIZE_OPTIONS.indexOf(sizeTo);
    if (startIdx < 0 || endIdx < 0 || startIdx > endIdx) {
      setErr(t("newso.invalidSizeRange"));
      return;
    }
    if (!Number.isFinite(distributeTotalQty) || distributeTotalQty <= 0) {
      setErr(t("newso.invalidTotalQty"));
      return;
    }

    const selectedSizes = SIZE_OPTIONS.slice(startIdx, endIdx + 1);
    const count = selectedSizes.length;
    const qtyPerSize = Math.floor(distributeTotalQty / count);
    let remainder = distributeTotalQty % count;

    const base = lines[0] ?? createLine({ size: sizeFrom });
    const nextLines: Line[] = selectedSizes.map((size) => {
      const addOne = remainder > 0 ? 1 : 0;
      if (remainder > 0) remainder -= 1;
      return createLine({
        model_id: base.model_id,
        color: base.color,
        size,
        quantity: qtyPerSize + addOne,
        pack_count: base.pack_count,
        unit_price: base.unit_price,
        printing_required: base.printing_required,
      });
    });

    setLines(nextLines);
    setLineModelSearch(nextLines.map(() => modelLabelById(base.model_id)));
  }

  const subtotal = lines.reduce((s, l) => s + linePieces(l) * Number(l.unit_price || 0), 0);
  const qty = lines.reduce((s, l) => s + linePieces(l), 0);
  const totalPacksSelected = lines.reduce((s, l) => s + linePacks(l), 0);
  const hasPrintingSelected = lines.some((line) => Boolean(line.printing_required));

  function isImageAttachment(a: PrintingAttachment): boolean {
    const byMime = (a.content_type || "").toLowerCase().startsWith("image/");
    const byName = /\.(png|jpe?g|webp|gif|bmp|svg)$/i.test(a.file_name || a.file_url || "");
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
        if (!availableModelOptions.length) {
          setErr(t("newso.noStockForBrand"));
          setSaving(false);
          return;
        }
        for (const line of lines) {
          if (!line.model_id) {
            setErr(t("newso.selectModel"));
            setSaving(false);
            return;
          }
          if (Number(line.pack_count || 0) <= 0) {
            setErr(t("newso.invalidPackQty"));
            setSaving(false);
            return;
          }
        }

        const requestedByModel = new Map<number, { requested: number; available: number; model: string }>();
        for (const line of lines) {
          const key = Number(line.model_id || 0);
          const available = Number(availableModelQtyById.get(key) || 0);
          const modelName = modelLabelById(line.model_id) || `#${line.model_id}`;
          const current = requestedByModel.get(key);
          if (current) {
            current.requested += linePieces(line);
          } else {
            requestedByModel.set(key, {
              requested: linePieces(line),
              available,
              model: modelName,
            });
          }
        }
        for (const row of requestedByModel.values()) {
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
          model_id: line.model_id,
          color: isBrandedOrder ? BRANDED_PACK_COLOR : line.color,
          size: isBrandedOrder ? brandedPackSize : line.size,
          quantity: linePieces(line),
          unit_price: line.unit_price,
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
                    <div className="text-[11px] uppercase tracking-[0.08em] text-[#6a7f72]">{t("newso.modelsInStorage")}</div>
                    <div className="mt-1 text-2xl font-semibold text-[#1f4032]">{availableModelCount.toLocaleString()}</div>
                  </div>
                  <div className="rounded-lg bg-white/75 p-3">
                    <div className="text-[11px] uppercase tracking-[0.08em] text-[#6a7f72]">{t("newso.packsInStorage")}</div>
                    <div className="mt-1 text-2xl font-semibold text-[#1f4032]">{totalBrandedPacks.toLocaleString()}</div>
                    <div className="mt-1 text-xs text-[#6a7f72]">{`${totalBrandedPieces.toLocaleString()} ${t("newso.pcsShort")}`}</div>
                  </div>
                </div>
                <p className="mt-2 text-xs text-[#53695c]">
                  {availableModelCount > 0 ? t("newso.brandedStockHint") : t("newso.noStockForBrand")}
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
                  <div className="w-40">
                    <label className="label">{t("newso.piecesPerPack")}</label>
                    <input
                      className="input h-8"
                      type="number"
                      min={1}
                      step={1}
                      value={packPieces}
                      onChange={(e) => setPackPieces(normalizePackPieces(e.target.value))}
                    />
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
                    <input className="input" type="number" min={1} value={distributeTotalQty} onChange={(e) => setDistributeTotalQty(Number(e.target.value))} />
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
                    <th>{t("field.model")}</th><th>{t("field.color")}</th><th>{t("field.size")}</th><th>{isBrandedOrder ? t("newso.packs") : t("field.qty")}</th><th>{t("field.unitPrice")}</th><th>{t("field.printingRequired")}</th><th></th>
                  </tr>
                </thead>
                <tbody>
                  {lines.map((l, i) => {
                    const modelTotal = Number(availableModelQtyById.get(Number(l.model_id)) || 0);
                    const lineAvailable = availableQtyForLine(l);
                    const lineAvailablePacks = Math.floor(lineAvailable / packPieces);
                    const qtyTooHigh = isBrandedOrder && linePacks(l) > lineAvailablePacks;
                    return (
                      <tr key={l.row_id}>
                        <td className="min-w-72 align-top">
                          {isBrandedOrder ? (
                            <>
                              <select
                                className="input"
                                value={l.model_id || ""}
                                onChange={(e) => updateLine(i, "model_id", Number(e.target.value) || 0)}
                                disabled={!availableModelOptions.length}
                              >
                                <option value="">{t("newso.selectModel")}</option>
                                {availableModelOptions.map((item) => (
                                  <option key={item.model.id} value={item.model.id}>
                                    {`${item.model.code} - ${item.model.name} - ${Math.floor(Number(item.available || 0) / packPieces).toLocaleString()} ${t("newso.packsShort")}`}
                                  </option>
                                ))}
                              </select>
                              {l.model_id > 0 && (
                                <div className="inline-flex rounded-full bg-[#edf7f1] px-2.5 py-1 text-xs font-medium text-[#246845]">
                                  {t("newso.modelInStockPack", {
                                    packs: Math.floor(modelTotal / packPieces).toLocaleString(),
                                    qty: modelTotal.toLocaleString(),
                                  })}
                                </div>
                              )}
                            </>
                          ) : (
                            <>
                              <input
                                className="input"
                                list={`model-options-${i}`}
                                placeholder={t("newso.selectModel")}
                                value={lineModelSearch[i] ?? modelLabelById(l.model_id)}
                                onChange={(e) => setModelSearch(i, e.target.value)}
                              />
                              <datalist id={`model-options-${i}`}>
                                {models?.map((m) => (
                                  <option key={m.id} value={`${m.code} - ${m.name}`} />
                                ))}
                              </datalist>
                            </>
                          )}
                        </td>
                        <td className="align-top">
                          {isBrandedOrder ? (
                            <input className="input min-w-28 bg-[#f8f7f3]" value={BRANDED_PACK_COLOR} readOnly />
                          ) : (
                            <input className="input min-w-28" value={l.color} onChange={(e) => updateLine(i, "color", e.target.value)} />
                          )}
                        </td>
                        <td className="align-top">
                          {isBrandedOrder ? (
                            <input className="input w-24 bg-[#f8f7f3]" value={brandedLineSizeLabel(l)} readOnly />
                          ) : (
                            <select className="input w-24" value={l.size} onChange={(e) => updateLine(i, "size", e.target.value)}>
                              {SIZE_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
                            </select>
                          )}
                        </td>
                        <td className="align-top">
                          {isBrandedOrder ? (
                            <div className="flex flex-col gap-2">
                              <div className="flex items-center gap-2">
                                <input
                                  className={`input w-28 ${qtyTooHigh ? "border-red-400 bg-red-50" : ""}`}
                                  type="number"
                                  min={1}
                                  value={l.pack_count}
                                  onChange={(e) => updateLine(i, "pack_count", Number(e.target.value) || 0)}
                                />
                                <span className="whitespace-nowrap text-xs text-[#8a8472]">{`${linePieces(l).toLocaleString()} ${t("newso.pcsShort")}`}</span>
                              </div>
                              {l.model_id > 0 && (
                                <div className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${qtyTooHigh ? "bg-red-50 text-red-700" : "bg-emerald-50 text-emerald-700"}`}>
                                  {t("newso.packsInModel", { packs: lineAvailablePacks.toLocaleString() })}
                                </div>
                              )}
                            </div>
                          ) : (
                            <input
                              className="input w-28"
                              type="number"
                              min={1}
                              value={lines[i]?.quantity ?? 0}
                              onChange={(e) => updateLine(i, "quantity", Number(e.target.value) || 0)}
                            />
                          )}
                        </td>
                        <td className="align-top"><input className="input w-32" type="number" step="0.01" value={l.unit_price} onChange={(e) => updateLine(i, "unit_price", Number(e.target.value))} /></td>
                        <td className="align-top"><input type="checkbox" checked={l.printing_required} onChange={(e) => updateLine(i, "printing_required", e.target.checked)} /></td>
                        <td className="align-top">
                          <button type="button" className="icon-btn text-red-600" onClick={() => removeLine(i)} title={t("newso.remove")}>
                            <Trash2 />
                          </button>
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
                <h2 className="app-card-title">Printing details</h2>
                <p className="mt-1 text-sm text-[#8a8472]">Visible to the printing team when this order reaches printing.</p>
              </div>
              <div className="space-y-3">
                <div>
                  <label className="label">Printing instructions</label>
                  <textarea
                    className="input"
                    rows={3}
                    value={printingInstructions}
                    onChange={(e) => setPrintingInstructions(e.target.value)}
                    placeholder="Placement, colors, technique, size, references..."
                  />
                </div>
                <div>
                  <label className="label">Attach picture or file</label>
                  <input
                    className="input"
                    type="file"
                    multiple
                    disabled={uploadingPrintFile}
                    onChange={(e) => {
                      onPickPrintingFiles(e.target.files);
                      e.currentTarget.value = "";
                    }}
                  />
                  <p className="mt-1 text-xs text-[#8a8472]">You can attach artwork, PDF spec, or sample photo.</p>
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
              <div className="flex justify-between"><span className="text-[#8a8472]">{t("sales.subtotal")}</span><span className="mono">${subtotal.toFixed(2)}</span></div>
              <div className="flex justify-between"><span className="text-[#8a8472]">{t("newso.estimatedTax")}</span><span className="mono">${(subtotal * 0.12).toFixed(2)}</span></div>
              <div className="border-t border-[#ecebe3] pt-3 flex justify-between text-base font-semibold"><span>{t("common.total")}</span><span className="mono">${(subtotal * 1.12).toFixed(2)}</span></div>
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
