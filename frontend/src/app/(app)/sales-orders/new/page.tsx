"use client";
import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { ArrowLeft, Plus, Trash2 } from "lucide-react";
import { fetcher, api } from "@/lib/api";
import { modelOptionsByIdsFetcher, modelOptionsByIdsKey } from "@/lib/useModelOptions";
import PageHeader from "@/components/PageHeader";
import Modal from "@/components/Modal";
import ModelAsyncSelect from "@/components/ModelAsyncSelect";
import SearchableSelect from "@/components/SearchableSelect";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { readySalesText } from "@/lib/readySalesLocale";
import { GARMENT_SIZE_OPTIONS } from "@/lib/garmentSizes";
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
  color: string;
  size: string;
  quantity: NumberInputValue;
  pack_count: NumberInputValue;
  unit_price: NumberInputValue;
  printing_required: boolean;
};
type PrintingAttachment = { file_url: string; file_name?: string | null; content_type?: string | null };
type ReadyStockOption = {
  model_id: number;
  brand_id: number | null;
  pack_count: number;
  quantity: number;
};
type AvailableModelOption = {
  model: any;
  saleablePacks: number;
  saleableQty: number;
};
type Customer = {
  id: number;
  name: string;
  phone?: string | null;
  email?: string | null;
  address?: string | null;
};
type CustomerDraft = {
  name: string;
  phone: string;
  email: string;
  address: string;
};

const SIZE_OPTIONS = GARMENT_SIZE_OPTIONS;
const DEFAULT_SIZE = SIZE_OPTIONS[0];
const BRANDED_PACK_SIZE = "any";
const BRANDED_PACK_COLOR = "mixed";
const EMPTY_CUSTOMER: CustomerDraft = { name: "", phone: "", email: "", address: "" };

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
    quantity: "",
    pack_count: "",
    unit_price: "",
    printing_required: false,
    ...overrides,
  };
}

export default function NewSalesOrderPage() {
  const { t, lang } = useT();
  const packText = readySalesText(lang);
  const { me } = useMe();
  const { data: customers, mutate: mutateCustomers } = useSWR<Customer[]>("/api/customers", fetcher);
  const { data: brands } = useSWR<any[]>("/api/brands", fetcher);
  const { data: readyStockOptions, error: stockError, isLoading: stockLoading } = useSWR<ReadyStockOption[]>("/api/sales-orders/ready-stock-options", fetcher);
  const [customerId, setCustomerId] = useState<number | "">("");
  const [customerModalOpen, setCustomerModalOpen] = useState(false);
  const [customerDraft, setCustomerDraft] = useState<CustomerDraft>(EMPTY_CUSTOMER);
  const [customerSaving, setCustomerSaving] = useState(false);
  const [customerError, setCustomerError] = useState("");
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
  const [err, setErr] = useState("");
  const [saving, setSaving] = useState(false);
  const salesModelOptionsKey = modelOptionsByIdsKey([
    ...(readyStockOptions || []).map((row) => row.model_id),
    ...lines.map((line) => line.model_id),
  ]);
  const { data: models } = useSWR<any[]>(salesModelOptionsKey, modelOptionsByIdsFetcher);

  const isBrandedOrder = orderType === "branded_stock_sale";
  const canCreateCustomer = can(me, "sales.customers");
  const brandedPackSize = BRANDED_PACK_SIZE;
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
  const availableModelOptions = useMemo<AvailableModelOption[]>(() => {
    const map = new Map<number, AvailableModelOption>();
    for (const row of readyStockOptions || []) {
      if (brandId && row.brand_id !== Number(brandId)) continue;
      const model = modelMap.get(row.model_id);
      if (!model) continue;
      const option = map.get(row.model_id) || { model, saleablePacks: 0, saleableQty: 0 };
      option.saleablePacks += row.pack_count;
      option.saleableQty += row.quantity;
      map.set(row.model_id, option);
    }
    return Array.from(map.values()).sort((a, b) => String(a.model.code).localeCompare(String(b.model.code)));
  }, [brandId, readyStockOptions, modelMap]);

  const availableModelGroups = useMemo(() => {
    const grouped = new Map<string, { key: string; label: string; items: AvailableModelOption[] }>();
    for (const item of availableModelOptions) {
      const modelId = Number(item.model.id);
      const key = modelGroupKeyByModelId.get(modelId) || modelVariantGroupKey(item.model);
      const group = modelGroupByKey.get(key);
      const label = group ? modelGroupLabel(group) : modelOrderLabel(item.model);
      const current = grouped.get(key);
      if (current) current.items.push(item);
      else grouped.set(key, { key, label, items: [item] });
    }
    return Array.from(grouped.values())
      .map((group) => ({
        ...group,
        items: group.items.slice().sort((a, b) => modelVariantLabel(modelVariantOption(a.model)).localeCompare(
          modelVariantLabel(modelVariantOption(b.model)),
          undefined,
          { numeric: true, sensitivity: "base" },
        )),
      }))
      .sort((a, b) => a.label.localeCompare(b.label, undefined, { numeric: true, sensitivity: "base" }));
  }, [availableModelOptions, modelGroupByKey, modelGroupKeyByModelId]);

  const availableModelSelectOptions = useMemo(() => availableModelGroups.flatMap((group) => (
    group.items.map((item) => {
      const variant = modelVariantLabel(modelVariantOption(item.model));
      const packLabel = `${item.saleablePacks.toLocaleString()} ${t("newso.packsShort")}`;
      return {
        value: Number(item.model.id),
        label: `${variant} - ${packLabel}`,
        searchText: `${group.label} ${modelOrderLabel(item.model)}`,
      };
    })
  )), [availableModelGroups, t]);

  const availableModelOptionById = useMemo(() => {
    return new Map(availableModelOptions.map((item) => [Number(item.model.id), item]));
  }, [availableModelOptions]);

  const availableModelQtyById = useMemo(() => {
    return new Map(availableModelOptions.map((item) => [Number(item.model.id), Number(item.saleableQty || 0)]));
  }, [availableModelOptions]);

  const availableModelCount = availableModelOptions.length;
  const totalBrandedPieces = availableModelOptions.reduce((sum, item) => sum + Number(item.saleableQty || 0), 0);
  const totalBrandedPacks = availableModelOptions.reduce((sum, item) => sum + Number(item.saleablePacks || 0), 0);

  useEffect(() => {
    setLines((prev) => prev.map((line) => ({
      ...line,
      color: isBrandedOrder ? BRANDED_PACK_COLOR : (line.color === BRANDED_PACK_COLOR ? "white" : line.color),
      size: isBrandedOrder ? BRANDED_PACK_SIZE : (line.size === BRANDED_PACK_SIZE ? DEFAULT_SIZE : line.size),
      quantity: isBrandedOrder ? "" : line.quantity,
      printing_required: isBrandedOrder ? false : line.printing_required,
    })));
  }, [isBrandedOrder]);

  function linePieces(line: Line): number {
    return isBrandedOrder ? 0 : Math.max(0, numberOrZero(line.quantity));
  }

  function linePacks(line: Line): number {
    return Math.max(0, numberOrZero(line.pack_count));
  }

  function updateLine(index: number, field: keyof Omit<Line, "row_id">, value: Line[keyof Omit<Line, "row_id">]) {
    setLines((prev) => prev.map((line, i) => {
      if (index !== i) return line;
      const next = { ...line, [field]: value };

      return next;
    }));
  }

  async function selectLineModel(index: number, modelId: number) {
    setLines((prev) => prev.map((line, i) => {
      if (index !== i) return line;
      const next = { ...line, model_id: modelId, unit_price: "" as NumberInputValue };

      return next;
    }));
    if (!modelId) return;
    try {
      const price = await api.get<{
        id: number;
        selling_price: number | null;
        selling_price_currency: string | null;
      }>(`/api/models/${modelId}/selling-price`);
      const parsedPrice = price.selling_price === null ? NaN : Number(price.selling_price);
      if (!Number.isFinite(parsedPrice) || parsedPrice < 0) return;
      setLines((prev) => prev.map((line, i) => (
        i === index && line.model_id === modelId && line.unit_price === ""
          ? { ...line, unit_price: parsedPrice }
          : line
      )));
    } catch (error) {
      setErr(error instanceof Error ? error.message : "Unable to load the variant price");
    }
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
        color: base.color,
        size,
        quantity: qtyPerSize + addOne,
        pack_count: base.pack_count,
        unit_price: base.unit_price,
        printing_required: base.printing_required,
      });
    });

    setLines(nextLines);
  }

  const subtotal = lines.reduce((s, l) => s + linePieces(l) * numberOrZero(l.unit_price), 0);
  const qty = lines.reduce((s, l) => s + linePieces(l), 0);
  const totalPacksSelected = lines.reduce((s, l) => s + linePacks(l), 0);
  const hasPrintingSelected = !isBrandedOrder && lines.some((line) => Boolean(line.printing_required));

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

  async function createCustomer(e: React.FormEvent) {
    e.preventDefault();
    setCustomerError("");
    setCustomerSaving(true);
    try {
      const created = await api.post<Customer>("/api/customers", customerDraft);
      await mutateCustomers(
        (current) => [created, ...(current || []).filter((customer) => customer.id !== created.id)],
        { revalidate: false },
      );
      setCustomerId(created.id);
      setCustomerDraft(EMPTY_CUSTOMER);
      setCustomerModalOpen(false);
    } catch (e: any) {
      setCustomerError(e.message || t("newso.customerCreateFailed"));
    } finally {
      setCustomerSaving(false);
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
          if (!Number.isInteger(linePacks(line)) || linePacks(line) <= 0) {
            setErr(t("newso.invalidPackQty"));
            setSaving(false);
            return;
          }
        }

        const requestedByModel = new Map<number, { requested: number; available: number; model: string }>();
        for (const line of lines) {
          const key = Number(line.model_id || 0);
          const available = Number(availableModelOptionById.get(key)?.saleablePacks || 0);
          const modelName = modelLabelById(line.model_id) || `#${line.model_id}`;
          const current = requestedByModel.get(key);
          if (current) {
            setErr(packText.duplicateVariant);
            setSaving(false);
            return;
          } else {
            requestedByModel.set(key, {
              requested: linePacks(line),
              available,
              model: modelName,
            });
          }
        }
        for (const row of requestedByModel.values()) {
          if (row.requested > row.available) {
            setErr(
              `${row.model}: ${packText.insufficientPacks} (${row.requested} / ${row.available})`,
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
          ...(isBrandedOrder ? { requested_pack_count: linePacks(line) } : { quantity: linePieces(line) }),
          unit_price: line.unit_price === "" ? null : numberOrZero(line.unit_price),
          printing_required: isBrandedOrder ? false : line.printing_required,
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
        subtitle={isBrandedOrder ? packText.scanTotals : t("newso.subtitle")}
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
                <div className="flex items-center justify-between gap-2">
                  <label className="label">{t("field.customer")}</label>
                  {canCreateCustomer && (
                    <button
                      type="button"
                      className="mb-1 inline-flex items-center gap-1 text-xs font-medium text-[#56503f] hover:text-[#14110b] hover:underline"
                      onClick={() => {
                        setCustomerError("");
                        setCustomerModalOpen(true);
                      }}
                    >
                      <Plus className="h-3.5 w-3.5" aria-hidden="true" />
                      {t("newso.addCustomer")}
                    </button>
                  )}
                </div>
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
              <div className="mt-4 border-t border-[#ecebe3] pt-3 text-sm text-[#56503f]">
                {stockLoading ? t("common.loading") : stockError ? packText.stockLoadFailed : (
                  <p>{availableModelCount.toLocaleString()} {t("newso.modelsInStorage")} · {totalBrandedPacks.toLocaleString()} {t("newso.packsInStorage")} · {totalBrandedPieces.toLocaleString()} {t("newso.pcsShort")}</p>
                )}
                <p className="mt-1">{packText.scanTotals}</p>
              </div>
            )}
          </section>

          <section className="card">
            <div className="flex items-center justify-between border-b border-[#ecebe3] px-5 py-4">
              <div>
                <h2 className="app-card-title">{t("newso.lines")}</h2>
                <p className="mt-1 text-sm text-[#8a8472]">
                  {isBrandedOrder
                    ? `${totalPacksSelected.toLocaleString()} ${t("newso.packsShort")}`
                    : t("newso.linesSummary", { lines: lines.length, qty: qty.toLocaleString() })}
                </p>
              </div>
              <div className="flex flex-wrap items-end gap-3">
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
                    <th>{t("field.model")}</th>
                    {!isBrandedOrder && <><th>{t("field.color")}</th><th>{t("field.size")}</th></>}
                    <th>{isBrandedOrder ? packText.packCount : t("field.qty")}</th>
                    <th>{t("field.unitPrice")}</th>{!isBrandedOrder && <th>{t("field.printingRequired")}</th>}<th></th>
                  </tr>
                </thead>
                <tbody>
                  {lines.map((l, i) => {
                    const modelOption = availableModelOptionById.get(Number(l.model_id));
                    const modelTotal = Number(availableModelQtyById.get(Number(l.model_id)) || 0);
                    const lineAvailablePacks = Number(modelOption?.saleablePacks || 0);
                    return (
                      <tr key={l.row_id}>
                        <td className="min-w-72 align-top">
                          {isBrandedOrder ? (
                            <>
                              <SearchableSelect<number>
                                value={l.model_id || null}
                                options={availableModelSelectOptions}
                                onChange={(modelId) => void selectLineModel(i, modelId)}
                                placeholder={t("newso.selectModel")}
                                noResultsText={t("page.search.noMatches")}
                                disabled={!availableModelOptions.length}
                                required
                              />
                              {l.model_id > 0 && (
                                <div className="inline-flex rounded-md bg-[#edf7f1] px-2.5 py-1 text-xs font-medium text-[#246845]">
                                  {t("newso.modelInStockPack", {
                                    packs: lineAvailablePacks.toLocaleString(),
                                    qty: modelTotal.toLocaleString(),
                                  })}
                                </div>
                              )}
                            </>
                          ) : (
                            <div className="min-w-72">
                              <ModelAsyncSelect
                                value={l.model_id || null}
                                onChange={(modelId) => void selectLineModel(i, modelId)}
                                placeholder={t("newso.selectModel")}
                                noResultsText={t("page.search.noMatches")}
                                loadingText={t("common.loading")}
                                loadMoreText={t("common.loadMore")}
                                required
                              />
                            </div>
                          )}
                        </td>
                        {!isBrandedOrder && <>
                          <td className="align-top"><input className="input min-w-28" value={l.color} onChange={(e) => updateLine(i, "color", e.target.value)} /></td>
                          <td className="align-top"><select className="input w-24 !min-w-24" value={l.size} onChange={(e) => updateLine(i, "size", e.target.value)}>
                            {SIZE_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
                          </select></td>
                        </>}
                        <td className="align-top">
                          {isBrandedOrder ? (
                            <input
                              className="input h-9 w-28"
                              type="number"
                              inputMode="numeric"
                              aria-label={packText.packCount}
                              min={1}
                              step={1}
                              max={lineAvailablePacks}
                              value={l.pack_count}
                              onChange={(e) => updateLine(i, "pack_count", parseNumberInput(e.target.value))}
                              required
                            />
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
                        {!isBrandedOrder && <td className="align-top"><div className="flex h-9 items-center"><input type="checkbox" checked={l.printing_required} onChange={(e) => updateLine(i, "printing_required", e.target.checked)} /></div></td>}
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
            <p className="mt-1 text-sm text-[#8a8472]">{isBrandedOrder ? packText.scanTotals : t("newso.orderSummarySub")}</p>
          </div>
          <div className="space-y-5 p-5">
            <div className="rounded-lg bg-[#f1efe8] p-4">
              <div className="label">{isBrandedOrder ? packText.packCount : t("newso.totalQuantity")}</div>
              <div className="mt-1 text-3xl font-semibold">{(isBrandedOrder ? totalPacksSelected : qty).toLocaleString()}</div>
              <div className="mt-1 text-sm text-[#8a8472]">
                {isBrandedOrder
                  ? `${totalPacksSelected.toLocaleString()} ${t("newso.packsShort")}`
                  : t("newso.piecesAcross", { qty: qty.toLocaleString(), lines: lines.length })}
              </div>
            </div>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between text-base font-semibold"><span>{t("field.totalAmount")}</span><span className="mono">{isBrandedOrder ? packText.warehouseConfirms : `$${subtotal.toFixed(2)}`}</span></div>
            </div>
            {err && <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">{err}</div>}
            <button className="btn btn-primary w-full" disabled={saving || (isBrandedOrder && (stockLoading || !!stockError))}>{saving ? t("newso.creating") : t("newso.createOrder")}</button>
            <p className="text-xs text-[#8a8472]">{isBrandedOrder ? t("newso.afterCreateBranded") : t("newso.afterCreate")}</p>
          </div>
        </aside>
      </form>

      <Modal
        open={customerModalOpen}
        onClose={() => {
          if (!customerSaving) setCustomerModalOpen(false);
        }}
        title={t("newso.addCustomer")}
        closeOnOutsideClick={!customerSaving}
      >
        <form onSubmit={createCustomer} className="space-y-3">
          <div>
            <label className="label" htmlFor="new-sales-order-customer-name">{t("common.name")}</label>
            <input
              id="new-sales-order-customer-name"
              className="input"
              value={customerDraft.name}
              onChange={(e) => setCustomerDraft((current) => ({ ...current, name: e.target.value }))}
              required
              autoFocus
            />
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label className="label" htmlFor="new-sales-order-customer-phone">{t("field.phone")}</label>
              <input
                id="new-sales-order-customer-phone"
                className="input"
                value={customerDraft.phone}
                onChange={(e) => setCustomerDraft((current) => ({ ...current, phone: e.target.value }))}
              />
            </div>
            <div>
              <label className="label" htmlFor="new-sales-order-customer-email">{t("field.email")}</label>
              <input
                id="new-sales-order-customer-email"
                className="input"
                type="email"
                value={customerDraft.email}
                onChange={(e) => setCustomerDraft((current) => ({ ...current, email: e.target.value }))}
              />
            </div>
          </div>
          <div>
            <label className="label" htmlFor="new-sales-order-customer-address">{t("field.address")}</label>
            <input
              id="new-sales-order-customer-address"
              className="input"
              value={customerDraft.address}
              onChange={(e) => setCustomerDraft((current) => ({ ...current, address: e.target.value }))}
            />
          </div>
          {customerError && <div className="text-sm text-red-600">{customerError}</div>}
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" className="btn" disabled={customerSaving} onClick={() => setCustomerModalOpen(false)}>
              {t("btn.cancel")}
            </button>
            <button type="submit" className="btn btn-primary" disabled={customerSaving}>
              {customerSaving ? t("common.saving") : t("newso.addCustomer")}
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
